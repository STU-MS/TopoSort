#!/usr/bin/env python3
"""从老师下发的模板生成《项目报告》docx（T4 / issue #43）。

方案见 `evidence/decisions/2026-09-26-报告改为模板docx交付.md`：

    老师模板 report-template.doc  --(x2t)-->  report/template.docx
                                          --(本脚本原地填内容)-->  submission/00-项目报告.docx

**为什么不用 pandoc**：老师给的是 `.doc` 模板，交付形态是「doc 主稿 + PDF 另存」。
pandoc 转出的 docx 无法继承模板样式（实测无 TOC 域、无封面版式）。本脚本改为
**在模板副本上原地填内容**，样式（标题/标题 1/标题 2/Tabletext）、页眉页脚域、
页面尺寸全部天然继承，因此版式 100% 与模板一致。

依赖（均为本机外部工具，非仓库依赖）：
    - officecli   AI 友好的 Office 文档 CLI（`officecli` 在 PATH 或 ~/.local/bin）
    - x2t         ONLYOFFICE 自带格式转换器，仅用于「模板缺失时」把 .doc 转成 .docx

用法：
    uv run python tools/build_report.py              # 生成 submission/00-项目报告.docx
    uv run python tools/build_report.py --out /tmp/x.docx
    uv run python tools/build_report.py --no-refresh  # 不刷目录页码

产物：
    submission/00-项目报告.docx

关键坑（实测，勿改）：
    * officecli 的 `--prop width=6` 是 6 EMU，长度值**必须带单位**（`6cm`）；
    * `get /body/tbl[N]` 有 bug（枚举报错），只能 get 到行/单元格一级；
    * `add` 是「插在锚点之后」，同一锚点连续插会**倒序**，故每章内容必须**逆序插入**；
    * 插入会移动其后所有元素的索引，故**按文档倒序处理章节**，锚点索引才不会失效；
    * officecli 会为每个文件路径起一个**常驻进程**；上一次运行的常驻还活着时会用内存里的
      旧文档覆盖刚拷进来的模板（实测把 11 行的分工表变成 6 行），所以拷模板前先 `close`；
    * **不要用 `officecli refresh` 刷新目录**：它把页码算对了，但重建目录条目时丢掉了
      「1.」编号前缀与点线前导符（实测条目退化成 `软硬件环境4`）。改用标准做法：在
      settings.xml 里置 `<w:updateFields w:val="true"/>`，由 Word 打开时自行重算目录
      （`--refresh` 仍保留作诊断用，默认不开）。
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = ROOT / "report" / "template.docx"
SRC_DOC = ROOT / "docs" / "report-template.doc"
DIAGRAM_DIR = ROOT / "report" / "diagrams"
DEFAULT_OUT = ROOT / "submission" / "00-项目报告.docx"

X2T_CANDIDATES = (
    "/Applications/ONLYOFFICE.app/Contents/Resources/converter/x2t",
    "/usr/lib/onlyoffice/documentserver/server/FileConverter/bin/x2t",
    "/usr/bin/x2t",
)

# 模板正文里已存在的标题（锚点），按文档出现顺序排列。
# 内容按这些标题挂载；顺序很重要：插入时按**倒序**处理，索引才不会失效。
CHAPTER_ANCHORS = (
    "软硬件环境",
    "需求分析",
    "详细设计",
    "类设计",
    "核心流程描述",
    "核心算法设计",
    "运行结果截图",
    "测试（测试用例设计、运行结果）",
    "系统特色以及可扩展点",
    "感想",
    "附件（会议记录）",
)

# 模板里需要就地替换/填写的固定位置（转出的 template.docx 上实测得到）
BODY_TITLE_PARA = 52          # “校园行走最优路径查询系统 项目报告”（老师模板的示例标题）
VERSION_PARA = 5              # “版本 1.0”
GROUP_PARA = 7                # “组别”
COVER_HEIGHT_ROW_COUNT = 11   # 分工描述表：1 行表头 + 10 行空行
HISTORY_ROW_COUNT = 10        # 修订历史表：1 行表头 + 9 行空行


def die(msg: str) -> "None":
    print(f"❌ {msg}", file=sys.stderr)
    sys.exit(1)


def which_officecli() -> str:
    found = shutil.which("officecli")
    if found:
        return found
    local = Path.home() / ".local" / "bin" / "officecli"
    if local.exists():
        return str(local)
    die("未找到 officecli。安装见 https://officecli.ai/SKILL.md（单二进制，无需 Office）。")


def ensure_template() -> None:
    """report/template.docx 不存在时，用 x2t 从老师原始 .doc 转一份（可复现）。"""
    if TEMPLATE.exists():
        return
    if not SRC_DOC.exists():
        die(f"找不到老师模板 {SRC_DOC}。")
    x2t = next((c for c in X2T_CANDIDATES if Path(c).exists()), None) or shutil.which("x2t")
    if not x2t:
        die("未找到 x2t（ONLYOFFICE 自带转换器）。请先安装 ONLYOFFICE 或用 Word 另存为 docx 后放到 "
            f"{TEMPLATE}。")
    TEMPLATE.parent.mkdir(parents=True, exist_ok=True)
    res = subprocess.run([x2t, str(SRC_DOC), str(TEMPLATE)], capture_output=True, text=True)
    if res.returncode != 0 or not TEMPLATE.exists():
        die(f"x2t 转换失败：{(res.stderr or res.stdout)[:400]}")
    print(f"→ 由 {SRC_DOC.name} 转出模板：{TEMPLATE.relative_to(ROOT)}")


class Oc:
    """officecli 薄封装：非 0 退出即抛错，避免“静默半成品”。"""

    def __init__(self, binary: str, path: Path) -> None:
        self.binary = binary
        self.path = path

    def _run(self, *args: str) -> str:
        res = subprocess.run([self.binary, *args], capture_output=True, text=True, encoding="utf-8")
        if res.returncode != 0:
            die(f"officecli {' '.join(args[:3])} 失败：{(res.stderr or res.stdout).strip()[:400]}")
        return (res.stdout or "").strip()

    def set(self, target: str, **props: object) -> None:
        args = ["set", str(self.path), target]
        for key, value in props.items():
            args += ["--prop", f"{key}={value}"]
        self._run(*args)

    def add(self, parent: str, *, insert_after: str | None = None, type: str | None = None,
            **props: object) -> str:
        args = ["add", str(self.path), parent]
        if type:
            args += ["--type", type]
        for key, value in props.items():
            args += ["--prop", f"{key}={value}"]
        if insert_after:
            args += ["--after", insert_after]
        out = self._run(*args)
        m = re.search(r"at (\S+)", out)
        return m.group(1) if m else ""

    def remove(self, target: str) -> None:
        self._run("remove", str(self.path), target)

    def query(self, selector: str) -> str:
        return self._run("query", str(self.path), selector)

    def refresh(self) -> str:
        return self._run("refresh", str(self.path))

    def set_update_fields(self) -> None:
        """在 settings.xml 里置 `<w:updateFields w:val="true"/>`，让 Word 打开时重算目录/页码域。

        位置必须在 `w:footnotePr` 之前（CT_Settings 是 sequence，位置错了会引入 schema 错误）。
        模板里没有该元素时静默跳过——不影响其余流程。
        """
        res = subprocess.run(
            [self.binary, "raw-set", str(self.path), "/settings",
             "--xpath", "/w:settings/w:footnotePr", "--action", "insertbefore",
             "--xml", '<w:updateFields w:val="true"/>'],
            capture_output=True, text=True, encoding="utf-8",
        )
        if res.returncode != 0:
            print("  ⚠ 未能置位 updateFields（目录页码将由 Word 自行重算，不影响交付）")

    def save(self) -> None:
        self._run("save", str(self.path))

    def close(self) -> None:
        """冲盘并释放常驻进程（幂等；无常驻时也不报错）。"""
        subprocess.run([self.binary, "close", str(self.path)], capture_output=True, text=True)

    @classmethod
    def release(cls, binary: str, path: Path) -> None:
        """释放该路径上的常驻进程。

        必须做：officecli 会为每个文件路径启一个常驻进程（60s 空闲超时）。若上一次运行
        的常驻还活着，它会用内存里的旧文档覆盖刚拷进来的新模板（实测踩过：分工表 11 行
        变成 6 行）。所以在“拷模板”之前先 close。
        """
        subprocess.run([binary, "close", str(path)], capture_output=True, text=True)


def anchor_map(oc: Oc) -> dict[str, str]:
    """标题文本 → 段落路径（paraId 优先，回退序号）。"""
    out: dict[str, str] = {}
    for selector in ("paragraph[style=标题 1]", "paragraph[style=标题 2]"):
        for path, text in re.findall(r'(/\S+?) \(paragraph\) "([^"]*)"', oc.query(selector)):
            out.setdefault(text, path)
    missing = [a for a in CHAPTER_ANCHORS if a not in out]
    if missing:
        die(f"模板里找不到这些标题：{missing}（模板可能已变，请核对 report/template.docx）")
    return out


TEXT_WIDTH_TWIPS = 9360  # 模板正文宽度（A4 竖版 - 左右 2.54cm 页边距）
MIN_COL_TWIPS = 1100
COL_WEIGHT_EXP = 0.7  # <1：压缩长短列差距，避免编号列被挤成一字一行


def auto_col_widths(header: list[str], rows: list[list[str]]) -> str:
    """按内容宽度比例分配列宽（twips）。

    不给列宽时 officecli 只能建出单列表格；给等宽又会让长文本列挤成窄条、
    或把「FR-01/02」这类编号列挤成两行（两种都实测踩过）。折中：按「单元格最宽
    内容」开方压缩后分配比例，并给每列 1100 twips 下限（中文按 2 字宽计）。
    """

    def width(text: str) -> int:
        return sum(2 if ord(ch) > 0x2E80 else 1 for ch in str(text))

    n = len(header)
    weights = []
    for i in range(n):
        cells = [header[i], *[row[i] for row in rows if i < len(row)]]
        weights.append(max(width(c) for c in cells) ** COL_WEIGHT_EXP)
    total = sum(weights) or 1
    widths = [max(MIN_COL_TWIPS, int(TEXT_WIDTH_TWIPS * w / total)) for w in weights]
    # 把因下限而多占的部分从最宽列扣回，使总和刚好铺满正文宽度
    diff = TEXT_WIDTH_TWIPS - sum(widths)
    widest = widths.index(max(widths))
    widths[widest] = max(MIN_COL_TWIPS, widths[widest] + diff)
    return ",".join(str(w) for w in widths)


def add_table(oc: Oc, anchor: str, spec: dict) -> None:
    """在 anchor 之后建表并填内容（表格行/单元格只能逐条加）。"""
    widths = spec.get("colWidths") or auto_col_widths(spec["header"], spec["rows"])
    path = oc.add("/body", insert_after=anchor, type="table", colWidths=widths)
    rows = [spec["header"], *spec["rows"]]
    for _ in range(len(rows) - 1):
        oc.add(path, type="row")
    for r, row in enumerate(rows, start=1):
        for c, value in enumerate(row, start=1):
            oc.set(f"{path}/tr[{r}]/tc[{c}]", text=value)


def add_figure(oc: Oc, anchor: str, fig: dict) -> None:
    """插图：居中段落 + 图片 + 居中图题（图题在图**下方**，国标惯例）。"""
    caption_path = oc.add("/body", insert_after=anchor, type="paragraph",
                          align="center", text=fig["caption"])
    del caption_path  # 只为拿到“已插入”这个事实；图片段落要插在它前面
    pic_parent = oc.add("/body", insert_after=anchor, type="paragraph", align="center")
    oc.add(pic_parent, type="picture", src=fig["src"], width=fig.get("width", "14cm"))


def fill_items(oc: Oc, anchor: str, items: list[dict], figures: dict[str, dict]) -> int:
    """把一章的元素插到 anchor 之后。注意：**逆序插入**才能得到正序结果。"""
    for item in reversed(items):
        kind = item["kind"]
        if kind == "para":
            kwargs = {"text": item["text"]}
            if item.get("bold"):
                kwargs["bold"] = "true"
            oc.add("/body", insert_after=anchor, type="paragraph", **kwargs)
        elif kind == "heading2":
            oc.add("/body", insert_after=anchor, type="paragraph",
                   styleName="标题 2", text=item["text"])
        elif kind == "caption":
            oc.add("/body", insert_after=anchor, type="paragraph",
                   align="center", text=item["text"])
        elif kind == "table":
            add_table(oc, anchor, item)
        elif kind == "figure":
            fig_id = item["id"]
            if fig_id not in figures:
                die(f"content.py 里图 {fig_id} 未在 FIGURES 中登记")
            add_figure(oc, anchor, {**figures[fig_id], "caption": item["caption"]})
        else:
            die(f"未知元素类型：{kind}")
    return len(items)


def build(out: Path, refresh: bool, content_dir: Path) -> None:
    ensure_template()
    sys.path.insert(0, str(content_dir))
    try:
        import content  # noqa: PLC0415  （内容规格，由 report/content.py 提供）
    except ImportError as exc:
        die(f"无法导入 report/content.py：{exc}")

    out.parent.mkdir(parents=True, exist_ok=True)
    binary = which_officecli()
    # 释放可能还活着的常驻进程，否则它会用旧内容覆盖刚拷进来的模板
    Oc.release(binary, out)
    # 每次都从**原始模板**重建，保证幂等：重跑结果一致，不会叠加。
    shutil.copy2(TEMPLATE, out)
    oc = Oc(binary, out)

    print("① 封面与页眉")
    oc.set(f"/body/p[{VERSION_PARA}]", text=f"版本 {content.COVER['版本']}")
    oc.set(f"/body/p[{GROUP_PARA}]", text=f"组别：{content.COVER['组别']}")
    oc.set("/body/tbl[1]/tr[1]/tc[2]", text=content.COVER["学生"])
    oc.set("/body/tbl[1]/tr[2]/tc[2]", text=content.COVER["指导老师"])
    # 页眉表格第 2 行右格是“日期: <文档标识>”占位
    try:
        oc.set("/header[2]/tbl[1]/tr[2]/tc[2]", text=content.COVER["日期"])
    except SystemExit:
        print("  ⚠ 页眉日期占位未找到，跳过（不影响交付）")

    print("② 分工描述表")
    rows = content.DIVISION_ROWS
    if len(rows) > COVER_HEIGHT_ROW_COUNT - 1:
        die(f"分工描述表只有 {COVER_HEIGHT_ROW_COUNT - 1} 个空行，但给了 {len(rows)} 行")
    for i, row in enumerate(rows, start=2):
        for c, value in enumerate(row, start=1):
            oc.set(f"/body/tbl[2]/tr[{i}]/tc[{c}]", text=value)
    for r in range(COVER_HEIGHT_ROW_COUNT, len(rows) + 1, -1):
        oc.remove(f"/body/tbl[2]/tr[{r}]")

    print("③ 修订历史记录表")
    history = content.HISTORY_ROWS
    if len(history) > HISTORY_ROW_COUNT - 1:
        die(f"修订历史表只有 {HISTORY_ROW_COUNT - 1} 个空行，但给了 {len(history)} 行")
    for i, row in enumerate(history, start=2):
        for c, value in enumerate(row, start=1):
            oc.set(f"/body/tbl[3]/tr[{i}]/tc[{c}]", text=value)
    for r in range(HISTORY_ROW_COUNT, len(history) + 1, -1):
        oc.remove(f"/body/tbl[3]/tr[{r}]")

    print("④ 正文标题")
    oc.set(f"/body/p[{BODY_TITLE_PARA}]", text="拓扑排序应用软件 项目报告")

    print("⑤ 逐章填内容（倒序处理，保证锚点索引不失效）")
    anchors = anchor_map(oc)
    total = 0
    for name in reversed(CHAPTER_ANCHORS):
        items = content.CHAPTERS.get(name) or []
        total += fill_items(oc, anchors[name], items, content.FIGURES)
        print(f"  {name}：{len(items)} 个元素")

    oc.save()
    print("⑥ 置 updateFields：让 Word 打开时自动重算目录页码与 PAGE/NUMPAGES 域")
    oc.set_update_fields()
    oc.save()
    if refresh:
        print("⑦ （诊断）officecli refresh 会重排目录页码，但会丢失编号前缀与点线前导符，默认不开")
        print("  " + oc.refresh())
    oc.close()
    try:
        shown = out.relative_to(ROOT)
    except ValueError:
        shown = out
    print(f"✅ 生成 {shown}（共插入 {total} 个元素）")


def main() -> int:
    ap = argparse.ArgumentParser(description="由老师模板生成《项目报告》docx（issue #43）")
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT, help=f"输出路径（默认 {DEFAULT_OUT}）")
    ap.add_argument("--refresh", action="store_true",
                    help="（诊断用）用 officecli refresh 重排目录页码；会丢失目录编号前缀与点线前导符，默认不开")
    ap.add_argument("--content-dir", type=Path, default=ROOT / "report",
                    help="content.py 所在目录（默认 report/，便于用别的稿子试跑）")
    args = ap.parse_args()
    out = args.out if args.out.is_absolute() else (ROOT / args.out)
    content_dir = args.content_dir if args.content_dir.is_absolute() else (ROOT / args.content_dir)
    build(out, refresh=args.refresh, content_dir=content_dir)
    return 0


if __name__ == "__main__":
    sys.exit(main())
