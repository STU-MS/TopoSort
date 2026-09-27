#!/usr/bin/env python3
"""把 5 份会议记录 Markdown 填进老师下发的《会议记录》模板，产出 5 份 docx。

方案与 `tools/build_report.py`（报告套模板）一致：

    docs/meeting-minutes-template.doc  --(x2t)-->  minutes/template.docx
                                                   --(本脚本原地填内容)-->  deliverables/docx/<slug>.docx

**为什么不用 pandoc**：老师给的是**固定表单**（右上角编号、日期/第几组一行、一张 12 行
表格）。pandoc 渲染出的 docx 只是普通文档，版式（蓝色表头、页边距、表格网格、下划线）
全丢。改为**在模板副本上原地改 XML**，所有版式天然继承。

**为什么不用 officecli**：`tools/build_report.py` 的文档注释里记了它的一堆坑（常驻进程
覆盖文件、`add` 倒序、索引漂移、`\v` 不合法）。本任务只是"定点替换 + 往空单元格塞
若干段落"，用标准库 `zipfile` + `xml.etree.ElementTree` 更直接、更可复现：没有常驻
进程、没有索引漂移、产物字节稳定。

数据层是 `tools/minutes_data.py`（**唯一解析入口**，本脚本只读不算）。PDF 侧
（`tools/minutes_html.py`）读同一份数据，字段"一字不差"。

用法：
    uv run python tools/build_minutes.py                 # 生成全部 5 份
    uv run python tools/build_minutes.py --only 2026-09-14-分组与任务分工
    uv run python tools/build_minutes.py --out-dir /tmp/x
    uv run python tools/build_minutes.py --refresh-template   # 强制用 x2t 重转模板
    uv run python tools/build_minutes.py --check         # 机械自检（生成后校验 XML）

产物：
    minutes/template.docx            模板副本（入库；与 report/template.docx 同样是提交物）
    deliverables/docx/<slug>.docx    5 份会议记录

关键坑（实测，勿改）：
    * x2t 转出的 docx **内容确定但 zip 字节不确定**（压缩时间戳、条目顺序），所以
      `workspace_write` 里重打包时把时间戳钉死、条目按名排序，模板副本才可复现
      （逐字节 `diff -r` 解包后的内容一致，仅 zip 元数据不同）。
    * x2t 偶发报 `Couldn't create temp folder`：换成"临时输出目录再搬回来"并重试一次。
    * 表格 12 行里每个空单元格模板都预置了 2~4 个**空段落**；不能直接替换段落，
      否则长正文（会议内容 25 块）会挤在模板预留的 4 个段落里。做法：清空单元格的
      全部段落，再按 Block 数重建 `<w:p>`。
    * 行高 `w:trHeight` 必须是 `hRule="atLeast"`（允许增长），且**不能**加
      `w:cantSplit`，否则长内容会被整行推到下一页。
    * `w:rPr` 子元素顺序是 OOXML schema 的 sequence，`rFonts` 必须在 `b` 之前、
      `b` 在 `bCs` 之前、`bCs` 在 `sz` 之前。顺序错了 Word 会报"文档已损坏"。
    * 自建段落/run 的字体字号**必须显式复刻模板**（楷体 `sz=24` = 12pt）：模板值格
      空段落的 `w:pPr/w:rPr` 与空 run 的 `w:rPr` 都带着它，但裸造 `<w:p><w:pPr>
      <w:pStyle Normal/></w:pPr><w:r><w:rPr/></w:r></w:p>` 会落到 `Normal`
      （宋体 10.5pt），比模板小 1.5pt 且换字体。故本脚本以模板该格的 `pPr`/`rPr`
      克隆为底（`_template_ppr()` / `_template_run_rpr()`）。
    * 值格对齐也要从模板取：模板行2/行3/行4 的短值格带 `w:jc=center`，行1
      「主持人」「会议主题」与行2「结束时间」没有 `w:jc`。缺 `w:jc` 会落到
      `Normal` 的 `both` 而把短值两端对齐拉伸（实测「黄 应 辉」），故对没有
      显式 `jc` 的值格显式写 `left`。正文区块格保留模板原生的 `jc=start`。
    * 标签格（`主 持 人：` 等）只读不写：`set_cell_paragraphs()` 只清 `w:p`，
      `w:tcPr` 与标签文字一律不碰。
    * 字段值里的空白要归一（`参加人员` 是一长串顿号分隔的姓名，Markdown 里没有换行，
      但行内 Markdown 的 `**` 会被 parse_inline 拆掉，所以必须用 plain() 后的文本）。
"""
from __future__ import annotations

import argparse
import html
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import minutes_data  # noqa: E402  （唯一的解析入口，只读不改）

TEMPLATE = ROOT / "minutes" / "template.docx"
SRC_DOC = ROOT / "docs" / "meeting-minutes-template.doc"
DEFAULT_OUT_DIR = ROOT / "deliverables" / "docx"

# 与 tools/build_report.py 保持一致的 x2t 候选路径
X2T_CANDIDATES = (
    "/Applications/ONLYOFFICE.app/Contents/Resources/converter/x2t",
    "/usr/lib/onlyoffice/documentserver/server/FileConverter/bin/x2t",
    "/usr/bin/x2t",
)

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
NS = {"w": W}
ET.register_namespace("w", W)

# 缩进：每级 360 twips（0.25 英寸），与常见 Word 列表缩进一致
INDENT_PER_LEVEL = 360

# 字段标签 → 表格里的位置
#   (行号从 1 起, 标签所在列, 值所在列) —— 与 docs/meeting-minutes-template.doc 转出的结构一一对应
CELL_FIELDS: dict[str, tuple[int, int, int]] = {
    "主持人": (1, 1, 2),
    "会议主题": (1, 3, 4),
    "开始时间": (2, 1, 2),
    "结束时间": (2, 3, 4),
    "参加人员": (3, 1, 2),
    "记录人员": (4, 1, 2),
    "记录时间": (4, 3, 4),
}

# 区块名 → 正文所在行（标签在上一行）
SECTION_ROWS = {
    "会议内容": 6,
    "已解决问题": 8,
    "待解决问题": 10,
    "备注": 12,
}


def die(msg: str) -> "None":
    print(f"❌ {msg}", file=sys.stderr)
    sys.exit(1)


# --------------------------------------------------------------------------- #
# 1. 模板：x2t 转换（确定性重打包，保证可复现）
# --------------------------------------------------------------------------- #
def find_x2t() -> str | None:
    return next((c for c in X2T_CANDIDATES if Path(c).exists()), None) or shutil.which("x2t")


def _repack_deterministic(src: Path, dst: Path) -> None:
    """把 docx 重打成"时间戳钉死、条目按名排序"的 zip，使产物可复现。

    x2t 每次转出的**内容**一致（逐文件 diff 无差），但 zip 的压缩时间戳/条目顺序会变，
    导致 sha256 不同、`minutes/template.docx` 一提交就"每次都有改动"。这里统一重打包。
    """
    entries: list[tuple[str, bytes]] = []
    with zipfile.ZipFile(src) as zf:
        for info in zf.infolist():
            entries.append((info.filename, zf.read(info.filename)))
    entries.sort(key=lambda e: e[0])
    dst.parent.mkdir(parents=True, exist_ok=True)
    # ZIP 的最小合法日期是 1980-01-01，固定用它
    with zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in entries:
            zi = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            zi.compress_type = zipfile.ZIP_DEFLATED
            zi.external_attr = 0o600 << 16
            zf.writestr(zi, data)


def x2t_convert(src: Path, dst: Path) -> None:
    """x2t 转 .doc → .docx。

    实测 x2t 偶发 `Couldn't create temp folder`（多半是系统临时目录被占满/权限抖动），
    换到独立的临时输出目录再搬回来，并重试一次，能显著提高成功率。
    """
    x2t = find_x2t()
    if not x2t:
        die("未找到 x2t（ONLYOFFICE 自带转换器）。请先安装 ONLYOFFICE，或"
            f"用 Word 把 {SRC_DOC.name} 另存为 .docx 后放到 {TEMPLATE}。\n"
            "  候选路径：" + "、".join(X2T_CANDIDATES))
    last = ""
    with tempfile.TemporaryDirectory(prefix="toposort_minutes_") as tmp:
        tmp_out = Path(tmp) / "template.docx"
        for attempt in (1, 2):
            res = subprocess.run(
                [x2t, str(src), str(tmp_out)], capture_output=True, text=True, encoding="utf-8"
            )
            last = (res.stderr or res.stdout or "").strip()
            if tmp_out.exists() and tmp_out.stat().st_size > 0:
                _repack_deterministic(tmp_out, dst)
                return
            if attempt == 1 and "temp folder" in last:
                # 清掉 x2t 可能留在系统临时目录里的残骸，再试一次
                shutil.rmtree(Path(tempfile.gettempdir()) / "x2t", ignore_errors=True)
                continue
            break
    die(f"x2t 转换失败（已重试）：{last[:400]}\n"
        f"  建议：若报 `Couldn't create temp folder`，清空临时目录后重跑；"
        f"或用 Word 手动另存为 {TEMPLATE.name} 放到 {TEMPLATE.parent}/。")


def ensure_template(refresh: bool = False) -> None:
    """`minutes/template.docx` 不存在时由 x2t 转出；`refresh=True` 强制重转。"""
    if TEMPLATE.exists() and not refresh:
        return
    if not SRC_DOC.exists():
        die(f"找不到老师模板 {SRC_DOC}。")
    before = TEMPLATE.read_bytes() if TEMPLATE.exists() else None
    x2t_convert(SRC_DOC, TEMPLATE)
    after = TEMPLATE.read_bytes()
    if before is not None and before == after:
        print(f"→ 模板已是目标内容（重转结果一致）：{TEMPLATE.relative_to(ROOT)}")
    else:
        print(f"→ 由 {SRC_DOC.name} 转出模板：{TEMPLATE.relative_to(ROOT)}"
              f"（{len(after):,} B）")


# --------------------------------------------------------------------------- #
# 2. XML 小工具
# --------------------------------------------------------------------------- #
def _tag(name: str) -> str:
    return f"{{{W}}}{name}"


def _insert_ordered(parent: ET.Element, child: ET.Element, order: tuple[str, ...]) -> None:
    """按 OOXML 的 schema sequence 把 child 插到正确位置（`w:rPr` 等有固定子序）。"""
    idx = order.index(child.tag) if child.tag in order else len(order) - 1
    for i, existing in enumerate(parent):
        if existing.tag in order and order.index(existing.tag) > idx:
            parent.insert(i, child)
            return
    parent.append(child)


RPR_ORDER = (
    _tag("rFonts"), _tag("b"), _tag("bCs"), _tag("i"), _tag("iCs"),
    _tag("color"), _tag("sz"), _tag("szCs"), _tag("u"), _tag("lang"),
)
PPR_ORDER = (
    _tag("pStyle"), _tag("keepNext"), _tag("keepLines"), _tag("spacing"),
    _tag("ind"), _tag("jc"), _tag("rPr"),
)

# 模板里表格正文的字体/字号（楷体 12pt）。已实测：模板值格空段落的 `w:pPr/w:rPr`
# 与空 run 的 `w:rPr` 都带 `sz=24` + `rFonts ascii/hAnsi/eastAsia=楷体`。
# 自建 run 必须复刻这组属性，否则会落到 Normal（宋体 10.5pt），比模板小 1.5pt 且换字体。
TEMPLATE_FONT = "楷体"
TEMPLATE_SZ = "24"


def _clone(el: ET.Element | None) -> ET.Element | None:
    """深拷贝一个 XML 子树（None 透传）。"""
    return None if el is None else ET.fromstring(ET.tostring(el, encoding="unicode"))


def _template_run_rpr(cell: ET.Element) -> ET.Element:
    """取模板单元格里空 run 的 `w:rPr`（楷体 + sz=24）作为自建 run 的底。

    取不到（模板变了）→ 退化为显式构造一份，保证不会静默退成 Normal。
    """
    for p in cell.findall(_tag("p")):
        for r in p.findall(_tag("r")):
            rpr = r.find(_tag("rPr"))
            if rpr is not None:
                return _clone(rpr)
    fallback = ET.Element(_tag("rPr"))
    ET.SubElement(fallback, _tag("rFonts"), {
        _tag("ascii"): TEMPLATE_FONT, _tag("hAnsi"): TEMPLATE_FONT,
        _tag("eastAsia"): TEMPLATE_FONT,
    })
    ET.SubElement(fallback, _tag("sz"), {_tag("val"): TEMPLATE_SZ})
    ET.SubElement(fallback, _tag("szCs"), {_tag("val"): TEMPLATE_SZ})
    return fallback


def _template_ppr(cell: ET.Element) -> ET.Element | None:
    """取模板单元格首段的 `w:pPr`（`pStyle`/`rPr`(楷体,sz24)/`ind`/`jc` 全在里面）。"""
    for p in cell.findall(_tag("p")):
        ppr = p.find(_tag("pPr"))
        if ppr is not None:
            return _clone(ppr)
    return None


def _sort_children(el: ET.Element, order: tuple[str, ...]) -> None:
    """按 OOXML schema sequence 重排子元素（`w:rPr`/`w:pPr` 子序有固定要求）。"""
    children = list(el)
    el[:] = []
    for c in sorted(children, key=lambda e: order.index(e.tag) if e.tag in order else len(order)):
        el.append(c)


def make_run(text: str, *, bold: bool = False, base_rpr: ET.Element | None = None) -> ET.Element:
    """构造 `<w:r>`，`rPr` 以 `base_rpr`（模板的楷体 + sz=24）为底。

    只加 `bold` 的 `<w:b/><w:bCs/>`。**不再做 Consolas 等宽覆盖**：与 PDF 侧
    `code{font-family:inherit}` 对齐，也避免 docx↔PDF 观感不一致（行内 code 按普通文本渲染）。
    """
    r = ET.Element(_tag("r"))
    rpr = _clone(base_rpr) if base_rpr is not None else ET.Element(_tag("rPr"))
    if bold:
        ET.SubElement(rpr, _tag("b"))
        ET.SubElement(rpr, _tag("bCs"))
    _sort_children(rpr, RPR_ORDER)
    r.append(rpr)
    t = ET.SubElement(r, _tag("t"), {"{http://www.w3.org/XML/1998/namespace}space": "preserve"})
    t.text = text
    return r


def make_paragraph(text: str = "", *, bold: bool = False,
                   base_ppr: ET.Element | None = None,
                   base_rpr: ET.Element | None = None,
                   indent_level: int | None = None,
                   align: str | None = None) -> ET.Element:
    """构造 `<w:p>`，`pPr` 以模板该格原有空段落的 `pPr` 为底。

    `base_ppr` 带来模板的 `pStyle`/`rPr`(楷体,sz24)/`ind`/`jc`；再用 `indent_level`/
    `align` 覆盖 `ind`/`jc`（`align=None` 表示沿用模板）。这样字号字体/对齐/缩进
    全部与模板一致，不会退回 Normal（宋体 10.5pt + 两端对齐）。
    """
    p = ET.Element(_tag("p"))
    ppr = _clone(base_ppr) if base_ppr is not None else ET.Element(_tag("pPr"))
    if ppr.find(_tag("pStyle")) is None:
        ET.SubElement(ppr, _tag("pStyle"), {_tag("val"): "Normal"})
    if indent_level is not None:
        for old in ppr.findall(_tag("ind")):
            ppr.remove(old)
        ET.SubElement(ppr, _tag("ind"), {
            _tag("left"): str(indent_level * INDENT_PER_LEVEL),
            _tag("right"): "105",
        })
    if align is not None:
        for old in ppr.findall(_tag("jc")):
            ppr.remove(old)
        ET.SubElement(ppr, _tag("jc"), {_tag("val"): align})
    _sort_children(ppr, PPR_ORDER)
    p.append(ppr)
    if text:
        p.append(make_run(text, bold=bold, base_rpr=base_rpr))
    else:
        p.append(make_run("", base_rpr=base_rpr))  # 空段也要有 run，与模板一致
    return p


def set_cell_paragraphs(cell: ET.Element, paragraphs: list[ET.Element]) -> None:
    """清空单元格的所有段落，换成本次生成的段落（保留 `w:tcPr`）。

    模板里空单元格预置了 1~4 个空段落（"会议内容"格有 4 个），不清掉会把长正文挤住。
    **只动 `w:p`，标签格的 `w:tcPr` 与标签段落的属性一律不碰**。
    """
    for child in list(cell):
        if child.tag == _tag("p"):
            cell.remove(child)
    for p in paragraphs or [make_paragraph()]:
        cell.append(p)


# --------------------------------------------------------------------------- #
# 3. 填充
# --------------------------------------------------------------------------- #
def _para_text(p: ET.Element) -> str:
    return "".join(t.text or "" for t in p.iter(_tag("t")))


def _find_para(paras: list[ET.Element], needle: str) -> ET.Element | None:
    return next((p for p in paras if needle in _para_text(p)), None)


def fill_header(paras: list[ET.Element], m: minutes_data.Minutes) -> None:
    """右上角 `编号：` 段落 + `日期：…第  N 组` 段落。

    只改文字，保留模板原有的下划线/字体/居中。`编号：` 后面的空 run 直接写值；日期段落
    的"长空格 + 下划线 + 第 X 组"结构照旧，只把空格数量调到能装下 `date`。
    """
    # --- 编号 ---
    p0 = _find_para(paras, "编号：")
    if p0 is None:
        die("模板里找不到「编号：」段落。")
    runs = list(p0.findall(_tag("r")))
    target = next((r for r in runs if "编号：" in _para_text(r)), None)
    if target is None:
        die("「编号：」段落结构异常（找不到含该文字的 run）。")
    # 模板里 `编号：` 后面是两个空格，把值接到它后面
    t = target.find(_tag("t"))
    if t is None or "编号：" not in (t.text or ""):
        die("「编号：」run 里没有 w:t。")
    t.text = f"编号：{m.code}   "
    t.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")

    # --- 日期 / 第几组 ---
    p2 = _find_para(paras, "日期：")
    if p2 is None:
        die("模板里找不到「日期：」段落。")
    # 找"日期："run，重写为 `日期：<date>` + 填充空格；再找"第"run 写入组名
    date_run = next((r for r in p2.findall(_tag("r")) if "日期：" in _para_text(r)), None)
    group_run = next((r for r in p2.findall(_tag("r")) if "第" in _para_text(r)), None)
    if date_run is None or group_run is None:
        die(f"「日期：/第  组」段落结构异常（date_run={date_run is not None}, "
            f"group_run={group_run is not None}）。")
    all_runs = list(p2.findall(_tag("r")))
    trailing = all_runs[all_runs.index(group_run) + 1] if all_runs.index(group_run) + 1 < len(all_runs) else None
    label = f"日期：{m.date}"
    # 模板把标签与值之间的空白做成"尾部空格"；留足空格把下划线的"第 组"推到页右侧。
    # 全角中文按 2 列宽估算，凑到约 74 列宽（与模板观感一致）。
    width = sum(2 if ord(ch) > 0x2E80 else 1 for ch in label)
    pad = max(8, 74 - width)
    dt = date_run.find(_tag("t"))
    dt.text = label + " " * pad
    dt.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
    # `第<ordinal>组`：模板是两个 run——带下划线的 `第  ` + 不带下划线的 `组 `。
    # 字段值形如「第一组」：把序数「一」取出来填进模板的 `第  ` 与 `组 ` 之间的空位，
    # 得「第 一 组」（下划线保持在位）。若值不是 `第…组` 形状，退化为原值并告警。
    # 坑（初版曾踩）：直接把整串「第一组」接到 `第  ` 后面、再把 `组 ` run 清空，
    # 会渲染成「第 第一组」——重复「第」且丢了模板的围栏「组」。
    ordinal = group_ordinal(m.group)
    gt = group_run.find(_tag("t"))
    if ordinal is None:
        # 已是完整 `第…组` 形状→原样写入下划线 run（此时 `组 ` run 要留着当尾围栏，不追加）
        gt.text = m.group
        print(f"  ⚠ 「第几组」值 {m.group!r} 不匹配 `第(.*)组`，按下划线 run 原值填写")
    else:
        gt.text = f"第  {ordinal}"
    gt.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
    if trailing is not None and ordinal is not None:
        # 保留下划线围栏 `组 `（模板原文字），不要清空、不要删除
        tt = trailing.find(_tag("t"))
        if tt is not None and "组" not in (tt.text or ""):
            tt.text = "组 "
            tt.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")


def group_ordinal(value: str) -> str | None:
    """从「第几组」字段值里取序数：`第一组` → `一`，`第12组` → `12`。

    取不到（如值是「第一小组」以外的自由写法）→ 返回 None，由调用方退化处理。
    中间部分允许含空格（`第 一 组` → `一`）。
    """
    m = re.fullmatch(r"第\s*(.+?)\s*组", (value or "").strip())
    if not m:
        return None
    ordinal = m.group(1).strip()
    return ordinal or None


def fill_fields(tbl: ET.Element, m: minutes_data.Minutes) -> int:
    """行 1~4 的空单元格填 7 个字段；返回填入数量。

    复用模板该值格原有空段落的 `pPr`（`pStyle`/`rPr`(楷体,sz24)/`ind`/`jc`）与空 run 的
    `rPr`。对齐：模板原本有显式 `w:jc`（行2「开始时间」、行3「参加人员」、
    行4「记录人员/记录时间」是 `center`）→ 保留；原本没有（「主持人」「会议主题」
    「结束时间」）→ 显式写 `left`，避免短值被 `Normal` 的 `both` 两端对齐拉伸。
    """
    rows = tbl.findall(_tag("tr"))
    filled = 0
    for key, (row_no, _label_col, value_col) in CELL_FIELDS.items():
        value = _clean(m.field(key))
        tr = rows[row_no - 1]
        tcs = tr.findall(_tag("tc"))
        if value_col > len(tcs):
            die(f"表格第 {row_no} 行只有 {len(tcs)} 个单元格，找不到第 {value_col} 格"
                f"（字段「{key}」）。模板可能已变。")
        cell = tcs[value_col - 1]
        base_ppr = _template_ppr(cell)
        base_rpr = _template_run_rpr(cell)
        has_jc = base_ppr is not None and base_ppr.find(_tag("jc")) is not None
        align = None if has_jc else "left"
        set_cell_paragraphs(
            cell,
            [make_paragraph(value, base_ppr=base_ppr, base_rpr=base_rpr, align=align)],
        )
        filled += 1
    return filled


def block_paragraphs(blocks: tuple[minutes_data.Block, ...],
                     base_ppr: ET.Element | None,
                     base_rpr: ET.Element | None) -> list[ET.Element]:
    """把区块的 Block 序列转成 `<w:p>` 序列（列表前缀用 Block.marker()，与 PDF 侧一致）。

    每段都克隆模板该正文格的 `pPr`（含 `jc=start`），仅按层级覆盖 `w:ind`。
    """
    paras: list[ET.Element] = []
    for b in blocks:
        marker = b.marker()
        prefix = f"{marker} " if marker else ""
        inlines = minutes_data.parse_inline(f"{prefix}{b.text}")
        p = ET.Element(_tag("p"))
        ppr = _clone(base_ppr) if base_ppr is not None else ET.Element(_tag("pPr"))
        if ppr.find(_tag("pStyle")) is None:
            ET.SubElement(ppr, _tag("pStyle"), {_tag("val"): "Normal"})
        for old in ppr.findall(_tag("ind")):
            ppr.remove(old)
        ET.SubElement(ppr, _tag("ind"), {
            _tag("left"): str(b.level * INDENT_PER_LEVEL),
            _tag("right"): "105",
        })
        _sort_children(ppr, PPR_ORDER)
        p.append(ppr)
        for inline in inlines:
            if inline.text:
                p.append(make_run(inline.text, bold=inline.bold, base_rpr=base_rpr))
        if not inlines:
            p.append(make_run("", base_rpr=base_rpr))
        paras.append(p)
    return paras


def fill_sections(tbl: ET.Element, m: minutes_data.Minutes) -> tuple[int, int]:
    """行 6/8/10/12 填 4 个区块；返回（区块数, Block 总数）。"""
    rows = tbl.findall(_tag("tr"))
    n_blocks = 0
    for name, row_no in SECTION_ROWS.items():
        blocks = m.sections.get(name, ())
        tcs = rows[row_no - 1].findall(_tag("tc"))
        if not tcs:
            die(f"表格第 {row_no} 行没有单元格（区块「{name}」）。")
        cell = tcs[0]
        base_ppr = _template_ppr(cell)
        base_rpr = _template_run_rpr(cell)
        # 区块为空 → 单元格留空（不写"无"）；模板 `jc=start` 随 base_ppr 保留
        set_cell_paragraphs(cell, block_paragraphs(blocks, base_ppr, base_rpr))
        n_blocks += len(blocks)
    return len(SECTION_ROWS), n_blocks


def relax_row_heights(tbl: ET.Element) -> None:
    """把所有 `w:trHeight` 改成 `hRule="atLeast"`（允许增长），并确保没有 `cantSplit`。

    `exact` 行高会把长正文裁掉；`cantSplit` 会把整行推到下一页，留下大片空白。
    """
    for tr in tbl.findall(_tag("tr")):
        trpr = tr.find(_tag("trPr"))
        if trpr is None:
            continue
        for child in list(trpr):
            if child.tag == _tag("cantSplit"):
                trpr.remove(child)
        for h in trpr.findall(_tag("trHeight")):
            h.set(_tag("hRule"), "atLeast")
            if int(h.get(_tag("val"), "0") or 0) < 240:
                h.set(_tag("val"), "240")


def _clean(value: str) -> str:
    """字段值归一：去首尾空白、折叠内部连续空白（保留单个空格）。"""
    return re.sub(r"\s+", " ", value or "").strip()


# --------------------------------------------------------------------------- #
# 4. 构建
# --------------------------------------------------------------------------- #
XML_DECL = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'


def read_document_xml(path: Path) -> bytes:
    with zipfile.ZipFile(path) as zf:
        return zf.read("word/document.xml")


def _serialize(root: ET.Element) -> str:
    """序列化 document.xml：补回 xml 声明，并补回 ElementTree 会丢掉的
    `mc:Ignorable`（Word 的扩展标记；本模板正文并无 mc 内容，丢了也无害，但保留更稳）。
    """
    body = ET.tostring(root, encoding="unicode")
    return XML_DECL + body


def build_one(m: minutes_data.Minutes, out_dir: Path) -> tuple[Path, int, int, int]:
    """从模板副本生成一份 docx，返回 (路径, 字段数, 区块数, 字节数)。"""
    root = ET.fromstring(read_document_xml(TEMPLATE))
    body = root.find(_tag("body"))
    if body is None:
        die("模板 document.xml 里没有 w:body。")
    paras = [c for c in body if c.tag == _tag("p")]
    tbls = [c for c in body if c.tag == _tag("tbl")]
    if not tbls:
        die("模板里没有表格。")
    tbl = tbls[0]

    fill_header(paras, m)
    n_fields = fill_fields(tbl, m)
    _, n_blocks = fill_sections(tbl, m)
    relax_row_heights(tbl)

    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{m.slug}.docx"
    _write_docx(TEMPLATE, out, _serialize(root))
    return out, n_fields, len(SECTION_ROWS), out.stat().st_size


def _write_docx(template: Path, out: Path, document_xml: str) -> None:
    """把改过的 `word/document.xml` 写回模板 zip 的副本（其余部件原样保留）。

    时间戳钉死、条目顺序固定 → 连跑两次字节一致。
    """
    with zipfile.ZipFile(template) as zin:
        items = [(i.filename, zin.read(i.filename)) for i in zin.infolist()]
    tmp = out.with_suffix(".docx.tmp")
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zout:
        for name, data in items:  # 保持模板条目顺序，只有 document.xml 内容变了
            if name == "word/document.xml":
                data = document_xml.encode("utf-8")
            zi = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            zi.compress_type = zipfile.ZIP_DEFLATED
            zi.external_attr = 0o600 << 16
            zout.writestr(zi, data)
    tmp.replace(out)


# --------------------------------------------------------------------------- #
# 5. 自检
# --------------------------------------------------------------------------- #
def _docx_body_root(path: Path) -> ET.Element:
    return ET.fromstring(zipfile.ZipFile(path).read("word/document.xml").decode("utf-8"))


def _cell_text(tc: ET.Element) -> str:
    """单元格纯文本（不折叠空白，用于"完全相等"断言前先归一）。"""
    return re.sub(r"\s+", "", html.unescape("".join(t.text or "" for t in tc.iter(_tag("t")))))


def check(entries: list[minutes_data.Minutes], out_dir: Path) -> int:
    """机械自检：(a) 9 个值出现 (b) 每个 Block 文本出现 (c) 份数齐全
    (d) 结构回归：表头无重复「第」、日期行/编号行与 md 一致、字段单元格逐格完全相等。

    (d) 是本次缺陷（「第 第一组」）的回归护栏——仅靠"包含"判断会漏掉重复「第」。
    """
    failures: list[str] = []
    print("\n=== 机械自检 ===")
    for m in entries:
        path = out_dir / f"{m.slug}.docx"
        if not path.exists():
            failures.append(f"{m.slug}: docx 不存在")
            continue
        with zipfile.ZipFile(path) as zf:
            xml = zf.read("word/document.xml").decode("utf-8")
        # 归一化：先剥标签，再反转义实体（`<a,b>` 在 XML 里是 `&lt;a,b&gt;`），
        # 最后去所有空白后比对，避开 run 边界/换行带来的干扰。
        text = html.unescape(re.sub(r"<[^>]+>", "", xml))
        text = re.sub(r"\s+", "", text)

        def norm(s: str) -> str:
            return re.sub(r"\s+", "", minutes_data.plain(s))

        # (a) 编号/日期/组（表头段落） + 7 个字段（表格单元格）
        missing = []
        for label, value in (("code", m.code), ("date", m.date)):
            if norm(value) not in text:
                missing.append(f"{label}={value!r}")
        for key in ("主持人", "会议主题", "开始时间", "结束时间",
                    "参加人员", "记录人员", "记录时间"):
            if norm(m.field(key)) not in text:
                missing.append(f"{key}={m.field(key)[:24]!r}")
        if missing:
            failures.append(f"{m.slug}: 字段缺失 {missing}")

        # (b) 四个区块的每个 Block
        total_blocks = 0
        for name in minutes_data.SECTION_KEYS:
            for b in m.sections.get(name, ()):
                total_blocks += 1
                if norm(b.text) not in text:
                    failures.append(f"{m.slug}: 区块「{name}」的块未找到：{b.text[:40]!r}")

        # (d) 结构回归护栏
        regress = _check_structure(_docx_body_root(path), m, text)
        failures.extend(f"{m.slug}: {msg}" for msg in regress)

        ok = not any(f.startswith(m.slug) for f in failures)
        mark = "✔" if ok else "✘"
        print(f"  {m.slug}: 9 个值 {mark}  区块 {total_blocks} 块 {mark}  "
              f"值格 jc∈{{left,center}}/run rPr(sz24+楷体)/标签格不变 {mark}")

    if len(entries) != 5:
        failures.append(f"份数不对：期望 5，实际 {len(entries)}")

    if failures:
        print("\n❌ 自检失败：")
        for f in failures:
            print(f"  - {f}")
        return 1
    print(f"\n✅ 自检通过：{len(entries)} 份，字段/区块文本与源 Markdown 全部一致；"
          f"表头「第 X 组」无重复「第」，7 个字段单元格逐格完全相等")
    return 0


def _check_structure(root: ET.Element, m: minutes_data.Minutes, flat_text: str) -> list[str]:
    r"""本次缺陷的结构化回归断言（返回失败说明列表）。

    1. 表头「第 一 组」行不得出现 `第\s*第`（初版缺陷：「第 第一组」）；
       且必须匹配 `第\s*<ordinal>\s*组`（ordinal 取自 md 的「第几组」）；
    2. 「日期：」「编号：」行文字必须与 md 的 date / code 一致；
    3. 每个字段单元格的纯文本必须**完全等于**对应字段值（不是"包含"）；
    4. 值格段落 `w:jc` ∈ {left, center}（不得缺失、不得 both）——P1 回归护栏；
    5. 自建 run 的 `w:rPr` 含 `sz=24` 与楷体 `rFonts`——P2 回归护栏；
    6. 标签格（`主 持 人：` 等）文本与模板完全一致（不被误改）。
    """
    problems: list[str] = []
    body = root.find(_tag("body"))
    if body is None:
        return ["document.xml 里没有 w:body"]
    paras = [c for c in body if c.tag == _tag("p")]

    # --- 1. 组别行 ---
    header = next((p for p in paras if "日期" in _para_text(p)), None)
    if header is None:
        problems.append("找不到含「日期」的表头段落")
    else:
        htext = _para_text(header)
        if re.search(r"第\s*第", htext):
            problems.append(f"表头出现重复「第」：{htext.strip()!r}")
        ordinal = group_ordinal(m.group)
        if ordinal is None:
            if m.group and m.group not in htext:
                problems.append(f"表头未包含原「第几组」值 {m.group!r}：{htext.strip()!r}")
        elif not re.search(rf"第\s*{re.escape(ordinal)}\s*组", htext):
            problems.append(
                f"表头未匹配 `第 {ordinal} 组`：实际 {htext.strip()!r}")
        if "组" not in htext:
            problems.append(f"表头丢了模板的「组」字：{htext.strip()!r}")

    # --- 2. 编号 / 日期 行 ---
    code_para = next((p for p in paras if "编号" in _para_text(p)), None)
    if code_para is None:
        problems.append("找不到「编号」段落")
    elif m.code not in _para_text(code_para):
        problems.append(f"「编号」行与 md 不一致：期望含 {m.code!r}，实际 "
                        f"{_para_text(code_para).strip()!r}")
    if header is not None and m.date not in _para_text(header):
        problems.append(f"「日期」行与 md 不一致：期望含 {m.date!r}，实际 "
                        f"{_para_text(header).strip()!r}")

    # --- 3. 字段单元格逐格完全相等 ---
    tbls = [c for c in body if c.tag == _tag("tbl")]
    if not tbls:
        problems.append("document.xml 里没有表格")
        return problems
    rows = tbls[0].findall(_tag("tr"))
    for key, (row_no, label_col, value_col) in CELL_FIELDS.items():
        tcs = rows[row_no - 1].findall(_tag("tc"))
        if value_col > len(tcs):
            problems.append(f"行 {row_no} 找不到第 {value_col} 个单元格（字段「{key}」）")
            continue
        cell = tcs[value_col - 1]
        actual = _cell_text(cell)
        expected = re.sub(r"\s+", "", minutes_data.plain(_clean(m.field(key))))
        if actual != expected:
            problems.append(f"字段「{key}」单元格不完全相等：期望 {expected!r}，实际 {actual!r}")

        # --- 4. 值格对齐：必须显式 left/center，不得缺失、不得 both（P1 护栏） ---
        for p in cell.findall(_tag("p")):
            ppr = p.find(_tag("pPr"))
            jc = None if ppr is None else ppr.find(_tag("jc"))
            jc_val = None if jc is None else jc.get(_tag("val"))
            if jc_val not in ("left", "center"):
                problems.append(
                    f"字段「{key}」值格段落 jc={jc_val!r}（应为 left/center，"
                    f"缺失会退成 Normal 的 both 而拉伸短值）")

        # --- 5. 自建 run 的 rPr：sz=24 + 楷体（P2 护栏） ---
        problems.extend(f"字段「{key}」{msg}" for msg in _check_run_rpr(cell))

        # --- 6. 标签格文本与模板一致 ---
        if label_col <= len(tcs):
            label_now = _cell_text(tcs[label_col - 1])
            if label_now != _label_text(key):
                problems.append(f"行 {row_no} 标签格被改动：expected {_label_text(key)!r}，"
                                f"实际 {label_now!r}")

    # 正文区块格的自建 run 也要查（P2 在会议内容里同样相关）
    for name, row_no in SECTION_ROWS.items():
        cell = rows[row_no - 1].findall(_tag("tc"))[0]
        problems.extend(f"区块「{name}」{msg}" for msg in _check_run_rpr(cell))

    # 兜底：正文字段不得靠别处凑数（防止误把值写错格子仍通过）
    del flat_text
    return problems


# 模板标签格的原文字（`主 持 人：` 带空格，不能与字段名直接相等）
LABEL_TEXTS = {
    "主持人": "主 持 人：",
    "会议主题": "会议主题：",
    "开始时间": "开始时间：",
    "结束时间": "结束时间：",
    "参加人员": "参加人员：",
    "记录人员": "记录人员：",
    "记录时间": "记录时间：",
}


def _label_text(key: str) -> str:
    return re.sub(r"\s+", "", LABEL_TEXTS[key])


def _check_run_rpr(cell: ET.Element) -> list[str]:
    """断言单元格里自建 run 的 `w:rPr` 含 `sz=24` 与楷体 `rFonts`（P2 回归护栏）。"""
    problems: list[str] = []
    for r in cell.iter(_tag("r")):
        if not (r.findall(_tag("t")) or r.findall(_tag("tab"))):
            continue
        rpr = r.find(_tag("rPr"))
        if rpr is None:
            problems.append("run 没有 w:rPr（会退成 Normal 宋体 10.5pt）")
            continue
        sz = rpr.find(_tag("sz"))
        if sz is None or sz.get(_tag("val")) != TEMPLATE_SZ:
            got = None if sz is None else sz.get(_tag("val"))
            problems.append(f"run 的 sz={got!r}（应为 {TEMPLATE_SZ!r}）")
        rfonts = rpr.find(_tag("rFonts"))
        fonts = set() if rfonts is None else {v for k, v in rfonts.attrib.items()}
        if TEMPLATE_FONT not in fonts:
            problems.append(f"run 的 rFonts={sorted(fonts)}（应含 {TEMPLATE_FONT!r}）")
    return problems


# --------------------------------------------------------------------------- #
# 6. CLI
# --------------------------------------------------------------------------- #
def main() -> int:
    ap = argparse.ArgumentParser(description="把 minutes/*.md 填进老师《会议记录》模板（T2）")
    ap.add_argument("--only", action="append", default=None,
                    help="只处理指定 slug（可重复）；默认全部")
    ap.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR,
                    help=f"输出目录（默认 {DEFAULT_OUT_DIR}）")
    ap.add_argument("--refresh-template", action="store_true",
                    help="强制用 x2t 从老师 .doc 重转 minutes/template.docx")
    ap.add_argument("--check", action="store_true",
                    help="生成后做机械自检（字段/区块文本是否都进了 XML）")
    args = ap.parse_args()

    out_dir = args.out_dir if args.out_dir.is_absolute() else (ROOT / args.out_dir)

    ensure_template(refresh=args.refresh_template)

    entries = minutes_data.load_all()
    if args.only:
        wanted = set(args.only)
        unknown = wanted - {m.slug for m in entries}
        if unknown:
            die(f"--only 指定的 slug 不存在：{sorted(unknown)}\n可用：" +
                "、".join(m.slug for m in entries))
        entries = [m for m in entries if m.slug in wanted]
    if not entries:
        die("minutes/ 下没有可处理的 .md（跳过 `_` 开头）。")

    print(f"\n模板：{TEMPLATE.relative_to(ROOT)}")
    print(f"输出：{out_dir.relative_to(ROOT) if out_dir.is_relative_to(ROOT) else out_dir}\n")

    header = f"{'slug':<34} {'字段':>4} {'区块':>4} {'块数':>4} {'字节':>9}"
    print(header)
    print("-" * len(header))
    for m in entries:
        path, n_fields, n_sections, size = build_one(m, out_dir)
        n_blocks = sum(len(m.sections.get(k, ())) for k in minutes_data.SECTION_KEYS)
        print(f"{m.slug:<34} {n_fields:>4} {n_sections:>4} {n_blocks:>4} {size:>9,}")
        del path
    print(f"\n✅ 完成：{len(entries)} 份 → "
          f"{out_dir.relative_to(ROOT) if out_dir.is_relative_to(ROOT) else out_dir}")

    if args.check:
        return check(entries, out_dir)
    return 0


if __name__ == "__main__":
    sys.exit(main())
