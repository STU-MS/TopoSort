#!/usr/bin/env python3
r"""《会议记录》成品机械验收（T5 / 独立验收者）。

被验收的对象（已冻结）：老师的《会议记录》固定表单模板
（`docs/meeting-minutes-template.doc` → `minutes/template.docx`）套上 5 份会议记录

    minutes/*.md            ← 源（数据层 tools/minutes_data.py 解析）
    deliverables/docx/<slug>.docx   ← docx 侧（tools/build_minutes.py）
    deliverables/pdf/<slug>.pdf     ← PDF 侧（tools/minutes_html.py + 无头 Chrome）
    submission/会议记录/<slug>.{docx,pdf}  ← 提交目录副本（tools/build_submission.py）

本脚本只做**机械判定**，风格/文风类留给人看。检查项：

  1. 成对性：docx/pdf 各 5 份、文件名一一对应（deliverables 与 submission 都查）；
  2. docx 字段与正文完整：zipfile 读 word/document.xml，**先剥标签、再 html.unescape、
     再空白归一**（否则 `<a,b>` 在 XML 里是 `&lt;a,b&gt;` 会误判缺失）；断言每份里
     都有 code、date、组别序数、7 个字段值、四个区块每个 Block 的 plain(text)；
  3. 字段单元格逐格精确相等（==，不是「包含」）：主持人/会议主题/开始时间/结束时间/
     参加人员/记录人员/记录时间 的值格文本必须等于 md 里的字段值；
  4. 模板保真：与 minutes/template.docx 比部件名集合、w:pgSz / w:pgMar、表格 12 行、
     标签格带 `w:shd ... fill="99ccff"`、w:trHeight 均 hRule="atLeast"、无 cantSplit；
  5. 表头无重复「第」（`第\s*第` 不得命中；实测曾渲染成「第 第一组」）—— 与第 3 项同属
     docx 内容护栏，在 check_docx_content 内一并输出；
  6. 表格 run 回归护栏（T7 修过的两类缺陷）：
     (A) 7 个字段值格的段落 `w:jc` 必须存在且 ∈ {left, center}（不得缺省→继承 Normal
         的 both 而被拉伸，也不得显式 both/justify）；并把每个值格实际取到的值打印出来；
     (B) 表格内每个非空 run 的 `w:rPr` 必须带 `w:sz w:val="24"` 与楷体 rFonts
         （否则退回 Normal 10.5pt 宋体），且 11 个标签格文字逐字节等于模板；
     (C) 产物不得含等宽字体名（Consolas 等；行内 code 已统一为正文体，与 PDF 侧对齐）；
  7. PDF：pdfinfo 每份 ≥1 页且为 A4（≈595×842pt）；pdftotext -layout 抽文本后做**独立于**
     minutes_html.py --check 的完整性比对（每个 Block 前 20 个实义字符命中）；
  8. docx 与 PDF 内容一致性：同一份 docx 抽出的字段值/区块文本与 PDF 抽出的文本对得上；
  9. 副本一致：submission/会议记录/* 与 deliverables/{docx,pdf}/* 逐字节（sha256）一致。
     注：PDF 由无头 Chrome 打印，/Info 里的 CreationDate/ModDate 每次渲染都不同，
     因此 PDF 无法逐字节一致——这里对 PDF 退化为「sha256 相同，或去掉 PDF 时间戳后
     完全相同」，并把时间戳差异作为**告警**报出（不影响交付，属渲染器行为）。

用法：
    uv run python tools/check_minutes.py             # 检查默认成品
    uv run python tools/check_minutes.py --quiet     # 只打印结论与不合格/告警

退出码 0 = 全部通过（时间戳类告警不算失败）；1 = 有不合格项。
"""
from __future__ import annotations

import argparse
import hashlib
import html
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import minutes_data  # noqa: E402  （唯一解析入口，只读）

DOCX_DIR = ROOT / "deliverables" / "docx"
PDF_DIR = ROOT / "deliverables" / "pdf"
SUB_DIR = ROOT / "submission" / "会议记录"
TEMPLATE = ROOT / "minutes" / "template.docx"

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
NS = {"w": W}


def tag(name: str) -> str:
    return f"{{{W}}}{name}"


# 与 tools/build_minutes.py 的 CELL_FIELDS 同义（本脚本独立复写，不 import 它，
# 避免「验收者与被验收者共用同一份可能出错的映射」而漏检）。
#   key → (行号 1 起, 标签列 1 起, 值列 1 起)
CELL_FIELDS: dict[str, tuple[int, int, int]] = {
    "主持人": (1, 1, 2),
    "会议主题": (1, 3, 4),
    "开始时间": (2, 1, 2),
    "结束时间": (2, 3, 4),
    "参加人员": (3, 1, 2),
    "记录人员": (4, 1, 2),
    "记录时间": (4, 3, 4),
}

# 区块名 → 正文行号（0 起）；标签在上一行
SECTION_ROWS = {"会议内容": 6, "已解决问题": 8, "待解决问题": 10, "备注": 12}

# 11 个标签格应当带浅蓝底纹 99ccff（4 行里的 7 个字段标签 + 4 个区块标签；后 4 行各 1 格）
SHADE = "99ccff"

# 表格正文期望的 run 字号（twips 半角）与中文字体：老师模板表格单元格实测为
# sz=24（12pt）+ 楷体。自建 run 必须显式带上，否则会退回 Normal（10.5pt 宋体）。
TEMPLATE_SZ = "24"
TEMPLATE_FONT = "楷体"

# 值格允许的段落对齐：left/center 均可，绝不允许缺省（继承 Normal 的 both=两端对齐，
# 会把「黄应辉（HandyWote，2024611031）」这种短行拉伸成「黄 应 辉」）或显式 justify。
OK_VALUE_JC = {"left", "center"}

# 行内 code 统一为正文体后，产物里不应再出现等宽字体名（与 PDF 侧对齐）。
FORBIDDEN_FONTS = ("Consolas", "Courier", "Monaco", "Menlo")

# 表格行数（模板固定 12 行）
TABLE_ROWS = 12

A4_PT = (595.0, 842.0)  # A4 名义尺寸；Chrome 打印会四舍五入到 594.96×841.92
A4_TOL = 3.0            # pt 容差

FAILURES: list[str] = []
WARNINGS: list[str] = []


def fail(msg: str) -> None:
    FAILURES.append(msg)
    print(f"❌ {msg}")


def warn(msg: str) -> None:
    WARNINGS.append(msg)
    print(f"⚠️  {msg}")


def ok(msg: str) -> None:
    print(f"✅ {msg}")


# --------------------------------------------------------------------------- #
# 文本归一化
# --------------------------------------------------------------------------- #
def strip_tags_unescape(xml: str) -> str:
    """XML → 可见文本：**先剥标签、再 html.unescape**。

    顺序很关键：`<a,b>` 在 document.xml 里是 `&lt;a,b&gt;`，若先 unescape 就会先冒出
    `<a,b>`，再剥标签时被当成标签削掉，于是"正文里明明有 `<a,b>`"被判成缺失。
    """
    return html.unescape(re.sub(r"<[^>]+>", "", xml))


def collapse(s: str) -> str:
    """只做空白归一（用于**已经从 XML/PDF 抽出的文本**）。

    不能对抽出的文本再跑 Markdown 解析：正文里显式的反引号（如 `` `--onefile` ``）
    会被当成 Markdown 代码定界符剥掉，于是「docx 里明明有」被误判为缺失。
    """
    return re.sub(r"\s+", "", s or "")


def collapse_loose(s: str) -> str:
    """更宽的归一：再去掉非汉字/字母/数字（用于 docx ↔ PDF 跨渲染器比对）。"""
    return re.sub(r"[^\w\u4e00-\u9fff]", "", collapse(s))


def expect(text: str) -> str:
    """期望值归一：Markdown → 纯文本（`` `` 会在此剥掉）→ 去空白。

    只用于「来自 minutes/*.md 的期望文本」，绝不用于抽取文本。
    """
    return collapse(minutes_data.plain(text or ""))


def expect_loose(text: str) -> str:
    return collapse_loose(minutes_data.plain(text or ""))


def rel(p: Path) -> str:
    """相对仓库根显示路径；不在仓库内时原样返回（消息不因外部路径而报错）。"""
    try:
        return str(Path(p).resolve().relative_to(ROOT))
    except ValueError:
        return str(p)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _attrs(tags: list[str]) -> list[tuple[tuple[str, str], ...]]:
    """把一组 XML 开始标签归一成「标签名 + 属性集合」，忽略属性顺序与 `/>` 前的空格。

    为什么不能直接比字符串：模板副本由 x2t 转出（`<w:pgSz .../>`），产物由
    ElementTree 序列化（`<w:pgSz ... />`），字节不同但语义完全相同。
    """
    out: list[tuple[str, tuple[tuple[str, str], ...]]] = []
    for t in tags:
        name = re.match(r"<([\w:]+)", t)
        items = re.findall(r'([\w:]+)="([^"]*)"', t)
        out.append((name.group(1) if name else t, tuple(sorted(items))))
    return sorted(out)


def is_subsequence(needle: str, hay: str) -> bool:
    """needle 是否为 hay 的子序列（字符按序出现，允许中间插入其它字符）。

    用于 PDF：6 列表格里一个值格若跨行换行，`pdftotext -layout` 会把续行插到其它列
    文字之后，于是去掉空白后的 haystack 里 needle 不连续。子序列判定既能容忍这种
    交错，又能拦住「字符被丢掉/改写」。
    """
    it = iter(hay)
    return all(ch in it for ch in needle)


# --------------------------------------------------------------------------- #
# docx 读取
# --------------------------------------------------------------------------- #
def docx_xml(path: Path) -> str:
    with zipfile.ZipFile(path) as zf:
        return zf.read("word/document.xml").decode("utf-8")


def docx_root(path: Path) -> ET.Element:
    return ET.fromstring(docx_xml(path))


def cell_text(tc: ET.Element) -> str:
    """单元格可见文本（先剥标签再 unescape 的等价做法，走 ElementTree 更稳）。"""
    return html.unescape("".join(t.text or "" for t in tc.iter(tag("t"))))


def para_text(p: ET.Element) -> str:
    return html.unescape("".join(t.text or "" for t in p.iter(tag("t"))))


# --------------------------------------------------------------------------- #
# 检查 1：成对性
# --------------------------------------------------------------------------- #
def check_pairing(entries: list[minutes_data.Minutes]) -> None:
    slugset = {m.slug for m in entries}

    def have(d: Path, ext: str) -> set[str]:
        return {s for s in slugset if (d / f"{s}.{ext}").exists()}

    # deliverables/docx 只放 docx，deliverables/pdf 只放 pdf，submission/会议记录 两份都要。
    # （deliverables/docx 里还放着报告/个人感想等别的 docx，不能一并算进会议记录的成对性。）
    for label, d, ext in (("deliverables/docx", DOCX_DIR, "docx"),
                          ("deliverables/pdf", PDF_DIR, "pdf")):
        got = have(d, ext)
        missing = sorted(slugset - got)
        if missing:
            fail(f"{label}: 缺 {ext}（{missing}）")
        else:
            ok(f"{label}: 5 份 {ext} 与 minutes/*.md 的 slug 一一对应")

    sub_docx, sub_pdf = have(SUB_DIR, "docx"), have(SUB_DIR, "pdf")
    missing_both = sorted(slugset - (sub_docx & sub_pdf))
    if missing_both:
        fail(f"submission/会议记录: 缺副本（docx/pdf 至少一份缺）：{missing_both}")
    if sub_docx != sub_pdf:
        fail(f"submission/会议记录: docx 与 pdf 不成对，仅 docx 有 {sorted(sub_docx - sub_pdf)}，"
             f"仅 pdf 有 {sorted(sub_pdf - sub_docx)}")
    if not missing_both and sub_docx == sub_pdf:
        ok(f"submission/会议记录: docx/pdf 各 {len(sub_docx)} 份且一一对应"
           f"（{'、'.join(sorted(sub_docx))}）")


# --------------------------------------------------------------------------- #
# 检查 2 + 3：docx 字段/正文完整、字段格精确相等
# --------------------------------------------------------------------------- #
def check_docx_content(entries: list[minutes_data.Minutes]) -> None:
    print("\n=== 2/3. docx 字段与正文完整、字段单元格逐格精确相等 ===")
    for m in entries:
        path = DOCX_DIR / f"{m.slug}.docx"
        if not path.exists():
            fail(f"{m.slug}: deliverables/docx 里没有对应 docx")
            continue
        xml = docx_xml(path)
        flat = collapse(strip_tags_unescape(xml))  # 剥标签 → unescape → 空白归一

        misses: list[str] = []
        # code / date（表头段落）
        if expect(m.code) not in flat:
            misses.append(f"编号 code={m.code!r}")
        if expect(m.date) not in flat:
            misses.append(f"日期 date={m.date!r}")
        # 组别序数（表头行应形如 `第 序数 组`）
        ordinal = re.fullmatch(r"第\s*(.+?)\s*组", m.group.strip())
        if ordinal is None:
            misses.append(f"第几组无法解析序数：{m.group!r}")
        elif not re.search(rf"第\s*{re.escape(ordinal.group(1))}\s*组", html.unescape(
                re.sub(r"<[^>]+>", "", xml))):
            misses.append(f"组别行未匹配 `第 {ordinal.group(1)} 组`（字段值 {m.group!r}）")
        # 7 个字段值
        for key in CELL_FIELDS:
            value = m.field(key)
            if not value:
                misses.append(f"字段「{key}」在 md 里为空")
            elif expect(value) not in flat:
                misses.append(f"字段「{key}」值未出现：{value[:30]!r}")
        # 四个区块的每个 Block
        n_blocks = 0
        for sec in minutes_data.SECTION_KEYS:
            for b in m.sections.get(sec, ()):
                n_blocks += 1
                if expect(b.text) not in flat:
                    misses.append(f"区块「{sec}」的块未出现：{b.text[:40]!r}")

        if misses:
            fail(f"{m.slug}: 正文/字段缺失 {len(misses)} 处 —— " + "；".join(misses[:5])
                 + (" …" if len(misses) > 5 else ""))
        else:
            ok(f"{m.slug}: code/date/组别 + 7 字段 + 四区块 {n_blocks} 块全部出现")

        # ---- 3. 字段单元格逐格精确相等 ----
        rows = docx_table_rows(path)
        if rows is None:
            fail(f"{m.slug}: 找不到表格，无法核对字段单元格")
            continue
        bad: list[str] = []
        for key, (row_no, _lbl, val_col) in CELL_FIELDS.items():
            tcs = rows[row_no - 1].findall(tag("tc"))
            if val_col > len(tcs):
                bad.append(f"「{key}」行 {row_no} 只有 {len(tcs)} 格，取不到第 {val_col} 格")
                continue
            actual = re.sub(r"\s+", "", cell_text(tcs[val_col - 1]))
            want = expect(m.field(key)).strip()
            if actual != want:
                bad.append(f"「{key}」期望 {want!r} 实际 {actual!r}")
        if bad:
            fail(f"{m.slug}: 字段单元格不完全相等 —— " + "；".join(bad))
        else:
            ok(f"{m.slug}: 7 个字段单元格逐格与 md 完全相等（== 而非包含）")

        # ---- 5. 表头无重复「第」 ----
        paras = [c for c in docx_root(path).find(tag("body")) if c.tag == tag("p")]
        header = next((p for p in paras if "日期" in para_text(p)), None)
        htext = para_text(header) if header is not None else ""
        if re.search(r"第\s*第", htext):
            fail(f"{m.slug}: 表头出现重复「第」：{htext.strip()!r}")
        elif header is None:
            fail(f"{m.slug}: 找不到含「日期」的表头段落")
        else:
            ok(f"{m.slug}: 表头无重复「第」：{htext.strip()!r}")


def docx_table_rows(path: Path) -> list[ET.Element] | None:
    body = docx_root(path).find(tag("body"))
    if body is None:
        return None
    tbls = [c for c in body if c.tag == tag("tbl")]
    if not tbls:
        return None
    return tbls[0].findall(tag("tr"))


def docx_table(path: Path) -> ET.Element | None:
    body = docx_root(path).find(tag("body"))
    if body is None:
        return None
    return next((c for c in body if c.tag == tag("tbl")), None)


def _cell_jc(tc: ET.Element) -> list[str]:
    """单元格内所有段落的 `w:jc` 值（按出现顺序；缺失即不在列表里）。"""
    return [j.get(tag("val")) for j in tc.iter(tag("jc"))]


# --------------------------------------------------------------------------- #
# 检查 4：模板保真
# --------------------------------------------------------------------------- #
def check_template_fidelity(entries: list[minutes_data.Minutes]) -> None:
    print("\n=== 4. 模板保真（与 minutes/template.docx 比对）===")
    if not TEMPLATE.exists():
        fail(f"模板副本不存在：{rel(TEMPLATE)}")
        return
    with zipfile.ZipFile(TEMPLATE) as zf:
        tpl_parts = set(zf.namelist())
    tpl_xml = docx_xml(TEMPLATE)
    tpl_pgsz = re.findall(r"<w:pgSz[^>]*>", tpl_xml)
    tpl_pgmar = re.findall(r"<w:pgMar[^>]*>", tpl_xml)
    tpl_rows = len(docx_table_rows(TEMPLATE) or [])

    expected_labels = set(CELL_FIELDS) | {"会议内容", "已解决问题", "待解决问题", "备注"}

    for m in entries:
        path = DOCX_DIR / f"{m.slug}.docx"
        if not path.exists():
            continue
        problems: list[str] = []
        with zipfile.ZipFile(path) as zf:
            parts = set(zf.namelist())
        if parts != tpl_parts:
            only_tpl = sorted(tpl_parts - parts)
            only_out = sorted(parts - tpl_parts)
            problems.append(f"部件名集合不同（模板独有 {only_tpl}，产物独有 {only_out}）")

        xml = docx_xml(path)
        if _attrs(re.findall(r"<w:pgSz[^>]*>", xml)) != _attrs(tpl_pgsz):
            problems.append(f"w:pgSz 与模板不同：{_attrs(re.findall(r'<w:pgSz[^>]*>', xml))} "
                            f"vs {_attrs(tpl_pgsz)}")
        if _attrs(re.findall(r"<w:pgMar[^>]*>", xml)) != _attrs(tpl_pgmar):
            problems.append(f"w:pgMar 与模板不同：{_attrs(re.findall(r'<w:pgMar[^>]*>', xml))} "
                            f"vs {_attrs(tpl_pgmar)}")

        rows = docx_table_rows(path) or []
        if len(rows) != tpl_rows or len(rows) != TABLE_ROWS:
            problems.append(f"表格行数 {len(rows)}（模板 {tpl_rows}，期望 {TABLE_ROWS}）")

        # 标签格底纹：把每行的「标签格」挑出来，断言带 99ccff
        n_shaded = 0
        for row_no, tr in enumerate(rows, 1):
            tcs = tr.findall(tag("tc"))
            for col_no, tc in enumerate(tcs, 1):
                txt = collapse(cell_text(tc))
                is_label = any(lbl in txt for lbl in expected_labels)
                if not is_label:
                    continue
                shd = tc.find(f".//{tag('shd')}")
                fill = (shd.get(tag("fill")) if shd is not None else None)
                if fill != SHADE:
                    problems.append(f"标签格「{txt}」(行{row_no} 列{col_no}) 底纹 {fill!r} ≠ {SHADE!r}")
                else:
                    n_shaded += 1

        # trHeight 必须 hRule="atLeast"；不得有 cantSplit
        heights = re.findall(r"<w:trHeight[^>]*>", xml)
        for h in heights:
            if 'hRule="atLeast"' not in h:
                problems.append(f"存在非 atLeast 的 w:trHeight：{h}")
        if "cantSplit" in xml:
            problems.append("表格里出现 cantSplit（会把整行推到下一页）")

        if problems:
            fail(f"{m.slug}: 模板保真 {len(problems)} 处不符 —— " + "；".join(problems[:4])
                 + (" …" if len(problems) > 4 else ""))
        else:
            ok(f"{m.slug}: 部件集合/pgSz/pgMar 同模板，表格 {len(rows)} 行，"
               f"{n_shaded} 个标签格底纹 {SHADE}，trHeight 全 atLeast，无 cantSplit")


# --------------------------------------------------------------------------- #
# 检查 5：表格 run 回归护栏（值格对齐 / 模板 rPr 继承 / 无等宽残留）
# --------------------------------------------------------------------------- #
def check_table_runs(entries: list[minutes_data.Minutes]) -> None:
    """把 T7 修过的两类缺陷（P1 值格被两端对齐拉伸、P2 退成 10.5pt 宋体）
    以及行内 code 的等宽残留钉成可重复的机械护栏。

    这三条的“期望值”不是凭记忆写的，而是从 minutes/template.docx 实测出来的：
      * 模板 `Normal` 样式带 `w:jc=both`，任何“缺省 jc”的段落都会被两端对齐——
        这正是当初把「黄应辉（HandyWote，2024611031）」渲染成「黄 应 辉」的根因；
      * 模板表格单元格的 run 带 `sz=24`（12pt）+ `rFonts=楷体`，自建 run 必须自带，
        否则退回 Normal（10.5pt 宋体），与模板和 PDF 侧都不同档；
      * 行内 code 已统一为正文体，不得再出现等宽字体名。
    """
    print("\n=== 5. 表格 run 回归护栏（值格对齐 / 模板 rPr 继承 / 无等宽残留）===")
    tpl_labels = _label_cells(TEMPLATE) if TEMPLATE.exists() else []

    for m in entries:
        path = DOCX_DIR / f"{m.slug}.docx"
        if not path.exists():
            continue
        problems: list[str] = []

        # ---- (A) 值格不被拉伸：7 个字段值格的 w:jc 必须存在且属于 {left, center} ----
        rows = docx_table_rows(path) or []
        shown: list[str] = []
        for key, (row_no, _lbl, val_col) in CELL_FIELDS.items():
            tcs = rows[row_no - 1].findall(tag("tc")) if row_no <= len(rows) else []
            if val_col > len(tcs):
                problems.append(f"(A)「{key}」取不到行 {row_no} 第 {val_col} 格")
                continue
            tc = tcs[val_col - 1]
            jcs = _cell_jc(tc)
            value = collapse(cell_text(tc))
            shown.append(f"{key}={value[:18]!r} jc={jcs}")
            if not jcs:
                problems.append(f"(A)「{key}」值格段落没有 w:jc（缺省会继承 Normal 的 both，"
                                f"短行会被两端对齐拉伸）")
            else:
                bad = [j for j in jcs if j not in OK_VALUE_JC]
                if bad:
                    problems.append(f"(A)「{key}」值格 w:jc={jcs} 含禁用值 {bad}"
                                    f"（允许 {sorted(OK_VALUE_JC)}）")

        # ---- (B) 表格内自建 run 继承模板 rPr：sz=24 + 楷体；标签格文字与模板完全一致 ----
        tbl = docx_table(path)
        n_runs = 0
        if tbl is None:
            problems.append("(B) 找不到表格")
        else:
            for r in tbl.iter(tag("r")):
                text = "".join(t.text or "" for t in r.iter(tag("t")))
                if not text.strip():
                    continue
                n_runs += 1
                rpr = r.find(tag("rPr"))
                if rpr is None:
                    problems.append(f"(B) run 无 w:rPr：{text[:20]!r}（会退回 Normal 10.5pt 宋体）")
                    continue
                sz = rpr.find(tag("sz"))
                if sz is None or sz.get(tag("val")) != TEMPLATE_SZ:
                    got = sz.get(tag("val")) if sz is not None else None
                    problems.append(f"(B) run 字号不是 sz={TEMPLATE_SZ}：{text[:20]!r}（实际 {got}）")
                fonts = "".join(rt.get(tag(k), "") or ""
                                for rt in rpr.iter(tag("rFonts"))
                                for k in ("ascii", "hAnsi", "eastAsia", "cs"))
                if TEMPLATE_FONT not in fonts:
                    problems.append(f"(B) run 字体不含「{TEMPLATE_FONT}」：{text[:20]!r}（实际 {fonts!r}）")

            prod_labels = _label_cells(path)
            if prod_labels != tpl_labels:
                diffs = [f"{a!r}→{b!r}" for a, b in zip(tpl_labels, prod_labels) if a != b]
                if len(tpl_labels) != len(prod_labels):
                    diffs.append(f"标签格数 {len(prod_labels)} ≠ 模板 {len(tpl_labels)}")
                problems.append("(B) 标签格文字被改写：" + "；".join(diffs[:4]))

        # ---- (C) 无等宽残留 ----
        xml = docx_xml(path)
        hit_fonts = [f for f in FORBIDDEN_FONTS if f in xml]
        if hit_fonts:
            problems.append(f"(C) 产物仍含等宽字体名 {hit_fonts}（行内 code 已统一为正文体）")

        if problems:
            fail(f"{m.slug}: 表格 run 回归 {len(problems)} 处 —— " + "；".join(problems[:4])
                 + (" …" if len(problems) > 4 else ""))
        else:
            ok(f"{m.slug}: 7 值格 w:jc 均∈{sorted(OK_VALUE_JC)}；表格 {n_runs} 个 run 全带 "
               f"sz={TEMPLATE_SZ}+{TEMPLATE_FONT}；{len(tpl_labels)} 个标签格文字同模板；"
               f"无等宽残留")
            print(f"     值格实测：" + "；".join(shown))


def _label_cells(path: Path) -> list[str]:
    """按表格顺序取出 11 个带 99ccff 底纹的标签格文字（逐字节，不做空白归一）。"""
    tbl = docx_table(path)
    if tbl is None:
        return []
    out: list[str] = []
    for r in tbl.findall(tag("tr")):
        for tc in r.findall(tag("tc")):
            shd = tc.find(f".//{tag('shd')}")
            if shd is not None and shd.get(tag("fill")) == SHADE:
                out.append("".join(t.text or "" for t in tc.iter(tag("t"))))
    return out


# --------------------------------------------------------------------------- #
# 检查 6：PDF（页数 / A4 / 文本完整）
# --------------------------------------------------------------------------- #
def pdfinfo(path: Path) -> dict[str, str]:
    res = subprocess.run(["pdfinfo", str(path)], capture_output=True, text=True, encoding="utf-8")
    out: dict[str, str] = {}
    for line in res.stdout.splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            out[k.strip()] = v.strip()
    return out


def pdftotext_layout(path: Path) -> str:
    res = subprocess.run(["pdftotext", "-layout", str(path), "-"],
                         capture_output=True, text=True, encoding="utf-8")
    if res.returncode != 0:
        raise RuntimeError(f"pdftotext 失败：{(res.stderr or '').strip()[:200]}")
    return res.stdout


def check_pdf(entries: list[minutes_data.Minutes]) -> None:
    print("\n=== 6. PDF：页数 / A4 / 文本完整性（独立于 minutes_html.py --check）===")
    for tool in ("pdfinfo", "pdftotext"):
        if shutil.which(tool) is None:
            fail(f"缺少外部工具 {tool}，无法验收 PDF")
            return
    for m in entries:
        path = PDF_DIR / f"{m.slug}.pdf"
        if not path.exists():
            fail(f"{m.slug}: deliverables/pdf 里没有对应 PDF")
            continue
        info = pdfinfo(path)
        problems: list[str] = []
        try:
            pages = int(info.get("Pages", "0"))
        except ValueError:
            pages = 0
        if pages < 1:
            problems.append(f"页数 {pages} < 1")
        # 页面尺寸
        size = info.get("Page size", "")
        mm = re.search(r"([\d.]+)\s*x\s*([\d.]+)\s*pts", size)
        if mm is None:
            problems.append(f"读不到页面尺寸：{size!r}")
        else:
            w, h = float(mm.group(1)), float(mm.group(2))
            if abs(w - A4_PT[0]) > A4_TOL or abs(h - A4_PT[1]) > A4_TOL:
                problems.append(f"页面尺寸 {w:.1f}×{h:.1f}pt 不是 A4（≈{A4_PT[0]:.0f}×{A4_PT[1]:.0f}）")

        # 文本完整性：每个 Block 前 20 个实义字符命中（与 minutes_html.py --check 独立实现：
        # 本脚本用 collapse_loose + 子序列判定，不 import 那个模块的任何函数）
        text = pdftotext_layout(path)
        haystack = collapse_loose(text)
        total = hit = 0
        misses: list[str] = []
        for sec in minutes_data.SECTION_KEYS:
            for i, blk in enumerate(m.sections.get(sec, ())):
                total += 1
                needle = expect_loose(blk.text)[:20]
                if needle and is_subsequence(needle, haystack):
                    hit += 1
                else:
                    misses.append(f"{sec}[{i}] 未命中前 20 实义字符 {needle!r}")
        if hit != total:
            problems.append(f"正文块命中 {hit}/{total}：" + "；".join(misses[:3]))
        # 字段值也要在 PDF 里（值格会跨行换行，用子序列判定）
        for key in CELL_FIELDS:
            val = expect_loose(m.field(key))
            if val and not is_subsequence(val, haystack):
                problems.append(f"字段「{key}」值未在 PDF 文本里：{m.field(key)[:24]!r}")

        if problems:
            fail(f"{m.slug}.pdf: " + "；".join(problems[:4]))
        else:
            ok(f"{m.slug}.pdf: {pages} 页、{size}（A4）、正文 {hit}/{total} 块 + 7 字段全部命中")


# --------------------------------------------------------------------------- #
# 检查 7：docx ↔ PDF 内容一致
# --------------------------------------------------------------------------- #
def check_cross_renderer(entries: list[minutes_data.Minutes]) -> None:
    print("\n=== 7. docx 与 PDF 内容一致性（同一份记录的两个渲染器）===")
    for m in entries:
        docx = DOCX_DIR / f"{m.slug}.docx"
        pdf = PDF_DIR / f"{m.slug}.pdf"
        if not (docx.exists() and pdf.exists()):
            continue
        dtext = collapse_loose(strip_tags_unescape(docx_xml(docx)))
        ptext = collapse_loose(pdftotext_layout(pdf))

        # 对每个字段值 + 每个块，分别检查在 docx 抽取文本 / PDF 抽取文本里的命中：
        #   * docx 抽取文本：应能“连续”命中（run 边界已被剥标签抹平）；
        #   * PDF 抽取文本：值格/正文可能跨行换行，用子序列判定容忍列间交错。
        # 任一侧命中失败，即视为两个渲染器内容不一致，纳入报告。
        items: list[tuple[str, str]] = []
        for key in CELL_FIELDS:
            items.append((f"字段「{key}」", m.field(key)))
        for sec in minutes_data.SECTION_KEYS:
            for i, blk in enumerate(m.sections.get(sec, ())):
                items.append((f"{sec}[{i}]", blk.text))

        bad: list[str] = []
        for label, raw in items:
            n = expect_loose(raw)[:30]
            if not n:
                continue
            in_d = n in dtext
            in_p = is_subsequence(n, ptext)
            if not (in_d and in_p):
                side = "docx 缺" if not in_d else "PDF 缺"
                bad.append(f"{label}({side}) {n!r}")
        if bad:
            fail(f"{m.slug}: docx/PDF 内容对不上 {len(bad)} 处 —— " + "；".join(bad[:4])
                 + (" …" if len(bad) > 4 else ""))
        else:
            ok(f"{m.slug}: {len(items)} 个比对项（7 字段 + 全部正文块）在 docx 与 PDF 中都命中")


# --------------------------------------------------------------------------- #
# 检查 8：副本一致
# --------------------------------------------------------------------------- #
def _pdf_without_timestamps(blob: bytes) -> bytes:
    """把 PDF /Info 里的 CreationDate / ModDate 抹平后返回（用于「内容一致」退化比对）。"""
    return re.sub(rb"/(CreationDate|ModDate)\s*\([^)]*\)", rb"/\1 ()", blob)


def check_copies(entries: list[minutes_data.Minutes]) -> None:
    print("\n=== 8. submission/会议记录 副本与 deliverables 一致 ===")
    identical = degraded = 0
    for m in entries:
        for kind, src_dir in (("docx", DOCX_DIR), ("pdf", PDF_DIR)):
            src = src_dir / f"{m.slug}.{kind}"
            dst = SUB_DIR / f"{m.slug}.{kind}"
            if not src.exists():
                fail(f"{m.slug}.{kind}: 源不存在 {rel(src)}")
                continue
            if not dst.exists():
                fail(f"{m.slug}.{kind}: 提交目录缺副本 {rel(dst)}")
                continue
            if sha256(src) == sha256(dst):
                identical += 1
                continue
            if kind == "pdf":
                a = _pdf_without_timestamps(src.read_bytes())
                b = _pdf_without_timestamps(dst.read_bytes())
                if a == b:
                    degraded += 1
                    warn(f"{m.slug}.pdf: 副本与源**内容**一致，仅 /Info 时间戳不同"
                         f"（pdfinfo 页数/尺寸/文本相同）—— Chrome 每次打印都会写新的 "
                         f"CreationDate/ModDate，属渲染器行为；如需字节级一致，重跑 "
                         f"tools/build_submission.py 从最新 deliverables 复制即可")
                    continue
            fail(f"{m.slug}.{kind}: 副本与源不一致（sha256 不同，且并非仅时间戳差异）")
    if identical + degraded == len(entries) * 2:
        ok(f"副本 {identical} 个逐字节一致"
           + (f"，{degraded} 个 PDF 仅时间戳差异（内容一致）" if degraded else ""))


# --------------------------------------------------------------------------- #
# main
# --------------------------------------------------------------------------- #
def main() -> int:
    ap = argparse.ArgumentParser(description="《会议记录》成品机械验收（T5）")
    ap.add_argument("--quiet", action="store_true", help="只打印结论与不合格/告警")
    args = ap.parse_args()

    global ok
    if args.quiet:
        def ok(msg: str) -> None:  # noqa: F811
            pass

    print("《会议记录》成品机械验收（check_minutes.py）")
    print("=" * 60)

    for label, p in (("minutes/template.docx", TEMPLATE), ("deliverables/docx", DOCX_DIR),
                     ("deliverables/pdf", PDF_DIR), ("submission/会议记录", SUB_DIR)):
        if not p.exists():
            fail(f"{label} 不存在：{rel(p)}")
    if FAILURES:
        print("\n" + "=" * 60)
        print(f"❌ 验收不通过：{len(FAILURES)} 项不合格（环境不完整，先跑 "
              f"tools/build_minutes.py / tools/minutes_html.py / tools/build_submission.py）")
        return 1

    entries = minutes_data.load_all()
    if len(entries) != 5:
        warn(f"minutes/ 下解析出 {len(entries)} 份记录（期望 5）")

    print(f"\n=== 1. 成对性 ===")
    check_pairing(entries)
    check_docx_content(entries)
    check_template_fidelity(entries)
    check_table_runs(entries)
    check_pdf(entries)
    check_cross_renderer(entries)
    check_copies(entries)

    print("\n" + "=" * 60)
    if FAILURES:
        print(f"❌ 验收不通过：{len(FAILURES)} 项不合格，{len(WARNINGS)} 项告警")
        for i, f in enumerate(FAILURES, 1):
            print(f"   {i}. {f}")
        return 1
    print(f"✅ 验收通过（{len(WARNINGS)} 项告警）")
    for i, w in enumerate(WARNINGS, 1):
        print(f"   ⚠️ {i}. {w}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
