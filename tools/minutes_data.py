#!/usr/bin/env python3
"""会议记录数据层：`minutes/YYYY-MM-DD-主题.md` → 结构化数据（唯一定义处）。

为什么单独一层：老师的《会议记录》模板（`docs/meeting-minutes-template.doc`）是一张
**固定表单**，我们的正文却是 Markdown。两个渲染器——

  * `tools/build_minutes.py` —— 在老师模板 docx 上原地填内容（docx 侧）；
  * `tools/minutes_html.py`  —— 用同版式的 HTML/CSS 打印成 PDF（PDF 侧，Chrome 无头）；

必须出自同一份数据、字段一字不差。因此解析只在这里做一次，渲染器只读不算。

Markdown 约定（由 `minutes/*.md` 的实际结构固化，模板见 `minutes/_模板.md`）：

    第 1 行   `汕头大学计算机系　编号：2026-09-14-01`          → `code`
    字段表    `| 项目 | 内容 |` 共 13 行（日期/第几组/主持人/会议主题/开始时间/
              结束时间/参加人员/记录人员/记录时间/会议内容/已解决问题/待解决问题/备注）
              → `fields`（键为去掉首尾空白的标签）
    二级标题  `## 会议内容` / `## 已解决问题` / `## 待解决问题` / `## 备注`，到下一个
              二级标题为止的正文 → `sections[...]`，逐行解析成 `Block`

用法：
    from minutes_data import load, load_all, parse_inline, FIELD_KEYS, SECTION_KEYS

    uv run python tools/minutes_data.py            # 自检：打印 5 份的结构摘要
"""
from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MINUTES_DIR = ROOT / "minutes"

# 老师模板里需要填入的字段（顺序即模板中出现的顺序）
FIELD_KEYS = (
    "日期",
    "第几组",
    "主持人",
    "会议主题",
    "开始时间",
    "结束时间",
    "参加人员",
    "记录人员",
    "记录时间",
)

# 表单下半部分的长文区块（模板里各有一个空的整行单元格）
SECTION_KEYS = ("会议内容", "已解决问题", "待解决问题", "备注")

# 字段表里写「见下」的占位（正文在 sections 里），不需要原样搬进表单
PLACEHOLDER = "见下"

_HEADER_RE = re.compile(r"^汕头大学计算机系\s*编号：\s*(?P<code>\S+)\s*$")
_FIELD_ROW_RE = re.compile(r"^\|\s*(?P<key>[^|]+?)\s*\|\s*(?P<val>.*?)\s*\|\s*$")
_SECTION_RE = re.compile(r"^##\s+(?P<title>\S.*?)\s*$")
_OL_RE = re.compile(r"^(?P<indent> *)(?P<num>\d+)\.\s+(?P<text>.*)$")
_UL_RE = re.compile(r"^(?P<indent> *)[-*]\s+(?P<text>.*)$")
_BOLD_RE = re.compile(r"\*\*(?P<t>.+?)\*\*")
_CODE_RE = re.compile(r"`(?P<t>[^`]+)`")
_LINK_RE = re.compile(r"\[(?P<t>[^\]]+)\]\((?P<url>[^)]+)\)")


@dataclass(frozen=True)
class Inline:
    """一段行内文本及其样式（渲染器据此决定加粗/等宽）。"""

    text: str
    bold: bool = False
    mono: bool = False


@dataclass(frozen=True)
class Block:
    """正文里的一块：段落、有序列表项或无序列表项。

    `level` 从 0 起（Markdown 里每 2 个空格缩进算一级）；`number` 仅有序块有，
    取自原文的显式序号（不重排，避免与会议记录原文不一致）。
    """

    kind: str  # "p" | "ol" | "ul"
    level: int
    text: str  # 行内 Markdown 原文，用 parse_inline() 拆样式
    number: int | None = None

    def marker(self) -> str:
        """列表项在纯文本渲染时的前缀（docx / HTML 都用它，保持一致）。"""
        if self.kind == "ol":
            return f"{self.number}."
        if self.kind == "ul":
            return "·"
        return ""


@dataclass(frozen=True)
class Minutes:
    slug: str  # 文件名去掉 .md，如 2026-09-14-分组与任务分工
    date: str  # fields["日期"]
    code: str  # 页面右上角的「编号」
    group: str  # fields["第几组"]
    fields: dict[str, str]
    sections: dict[str, tuple[Block, ...]]
    source: Path = field(compare=False, default=Path())

    def field(self, key: str) -> str:
        return self.fields.get(key, "")


def parse_inline(text: str) -> list[Inline]:
    """把行内 Markdown 拆成 [(文本, 样式)]。

    支持 `**加粗**`、`` `等宽` ``、`[文字](链接)`；链接只保留文字（会议记录正文里
    没有外链，保留 URL 会把表单撑爆），其余字符原样保留。
    """
    text = _LINK_RE.sub(lambda m: m.group("t"), text)
    out: list[Inline] = []
    pos = 0
    for m in re.finditer(r"\*\*(?P<b>.+?)\*\*|`(?P<c>[^`]+)`", text):
        if m.start() > pos:
            out.append(Inline(text[pos:m.start()]))
        if m.group("b") is not None:
            out.append(Inline(m.group("b"), bold=True))
        else:
            out.append(Inline(m.group("c"), mono=True))
        pos = m.end()
    if pos < len(text):
        out.append(Inline(text[pos:]))
    return out


def plain(text: str) -> str:
    """行内 Markdown → 纯文本（用于字段值、校验与对比）。"""
    return "".join(i.text for i in parse_inline(text))


def _parse_blocks(lines: list[str]) -> tuple[Block, ...]:
    blocks: list[Block] = []
    for raw in lines:
        if not raw.strip():
            continue
        line = raw.rstrip()
        if (m := _OL_RE.match(line)) is not None:
            blocks.append(Block("ol", len(m.group("indent")) // 2,
                                m.group("text").strip(), int(m.group("num"))))
        elif (m := _UL_RE.match(line)) is not None:
            blocks.append(Block("ul", len(m.group("indent")) // 2, m.group("text").strip()))
        elif line[0] in " \t" and blocks:
            # 续行（缩进且非列表标记）：并入上一块，避免把一句话拆成两块
            last = blocks[-1]
            blocks[-1] = Block(last.kind, last.level, f"{last.text} {line.strip()}", last.number)
        else:
            blocks.append(Block("p", 0, line.strip()))
    return tuple(blocks)


def parse(text: str, slug: str = "", source: Path | None = None) -> Minutes:
    """解析一份会议记录 Markdown。缺字段不报错，交给验收脚本判定。"""
    code, fields, sections = "", {}, {k: [] for k in SECTION_KEYS}
    section: str | None = None
    for line in text.splitlines():
        if (m := _HEADER_RE.match(line.strip())) is not None:
            code = m.group("code")
            continue
        if (m := _SECTION_RE.match(line)) is not None:
            title = m.group("title")
            section = title if title in SECTION_KEYS else None
            continue
        if (m := _FIELD_ROW_RE.match(line)) is not None:
            key, val = m.group("key").strip(), m.group("val").strip()
            if key and key != "项目":  # 表头
                fields[key] = val
            continue
        if section is not None:
            sections[section].append(line)

    return Minutes(
        slug=slug,
        date=fields.get("日期", ""),
        code=code,
        group=fields.get("第几组", ""),
        fields=fields,
        sections={k: _parse_blocks(v) for k, v in sections.items()},
        source=source or Path(),
    )


def load(path: Path) -> Minutes:
    path = Path(path)
    return parse(path.read_text(encoding="utf-8"), slug=path.stem, source=path)


def load_all(minutes_dir: Path | None = None) -> list[Minutes]:
    """按文件名排序读入全部会议记录（跳过 `_` 开头的模板/草稿）。"""
    d = Path(minutes_dir) if minutes_dir else MINUTES_DIR
    return [load(p) for p in sorted(d.glob("*.md")) if not p.name.startswith("_")]


def _selftest() -> int:
    files = load_all()
    if not files:
        print("❌ minutes/ 下没有可解析的 .md")
        return 1
    for m in files:
        print(f"\n=== {m.slug} ===")
        print(f"  编号={m.code}  日期={m.date}  组={m.group}")
        for k in FIELD_KEYS:
            if k in ("日期", "第几组"):
                continue
            print(f"  {k}: {m.field(k)[:60]}")
        for k in SECTION_KEYS:
            blocks = m.sections[k]
            kinds = {}
            for b in blocks:
                kinds[b.kind] = kinds.get(b.kind, 0) + 1
            print(f"  ## {k}: {len(blocks)} 块 {kinds or ''}")
    print(f"\n✅ 共 {len(files)} 份会议记录解析通过")
    return 0


if __name__ == "__main__":
    sys.exit(_selftest())
