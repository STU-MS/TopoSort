#!/usr/bin/env python3
"""会议记录 PDF 侧渲染器：`minutes/*.md` → 老师模板同版式 HTML → A4 PDF。

为什么这样做：老师的《会议记录》模板（`docs/meeting-minutes-template.doc`）是一张
**固定表单**（抬头 + 12 行 6 列表格）。docx 侧由 `tools/build_minutes.py` 在模板副本上
原地填写；PDF 侧没有可复用的 docx 排版，于是本脚本按同一版式用 HTML/CSS 复刻表单，
再用无头 Chrome 打印成 A4 PDF。两个渲染器共用同一份数据层 `tools/minutes_data.py`，
字段一字不差。

版式换算（照 `docs/meeting-minutes-template.doc` 实测）：

    A4 210×297mm；页边距 左右 1800 twips = 31.75mm、上下 1440 twips = 25.4mm
    → 正文宽 = 210 - 2×31.75 = 146.5mm
    表格 6 列（模板 twips 1368/2160/732/1093/1038/2131）等比例 →
        24mm / 38mm / 13mm / 19mm / 18mm / 38mm（合计 146.5mm）
    单元格内边距左右 108 twips ≈ 1.9mm；全边框 0.5pt 实线；正文 10.5pt

用法：
    uv run python tools/minutes_html.py                  # 渲染全部 5 份
    uv run python tools/minutes_html.py --only 2026-09-15-开工定案
    uv run python tools/minutes_html.py --out-dir /tmp/x --keep-html /tmp/html
    uv run python tools/minutes_html.py --check          # 只跑内容完整性核对

依赖（本机外部工具，非仓库依赖）：Google Chrome / Chromium / Edge（设 CHROME_PATH 可覆盖）。
    CI（ubuntu + fonts-noto-cjk）下 Chrome 走 --no-sandbox，由 make_pdf.html_to_pdf 处理。

产物：
    deliverables/pdf/<slug>.pdf     覆盖同名 pandoc 版 PDF，版式为老师模板表单

幂等：输出只由 `minutes/*.md` 内容决定，本脚本不注入时间戳/随机数；同输入重复运行 HTML
逐字节相同、PDF 提取文本相同。注：Chrome 自身会在 PDF `/Info` 里写创建时间
（`CreationDate`/`ModDate`），这是渲染器的行为（`tools/make_pdf.py` 同样如此），
因此 PDF 整文件哈希会变，但**页面数、页面尺寸、正文内容完全一致**。
"""
from __future__ import annotations

import argparse
import html
import re
import sys
import tempfile
from pathlib import Path

# 复用现成实现：数据层（唯一定义处）与 Chrome 打印（含 CI 自动 --no-sandbox）
sys.path.insert(0, str(Path(__file__).resolve().parent))
from make_pdf import find_chrome, html_to_pdf  # noqa: E402
from minutes_data import (  # noqa: E402
    Block,
    Minutes,
    SECTION_KEYS,
    load_all,
    parse_inline,
    plain,
)

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUT_DIR = ROOT / "deliverables" / "pdf"

# 6 列宽度（mm），由模板 twips 1368/2160/732/1093/1038/2131 等比例换算到正文宽
# 146.5mm（210 - 2×31.75），取 0.5mm 整数倍对齐；合计必须为 146.5mm。
COL_MM = (23.5, 37.0, 12.5, 19.0, 18.0, 36.5)
assert abs(sum(COL_MM) - 146.5) < 0.01, "列宽必须合计正文宽 146.5mm"

# 12 行表单结构：每行是 (文本, 跨列数) 序列；跨列数之和必须等于 6 列
#   空文本 = 留给正文的整行大格
TABLE_ROWS: tuple[tuple[tuple[str, int], ...], ...] = (
    (("主 持 人：", 1), ("@主持人", 1), ("会议主题：", 2), ("@会议主题", 2)),
    (("开始时间：", 1), ("@开始时间", 2), ("结束时间：", 2), ("@结束时间", 1)),
    (("参加人员：", 1), ("@参加人员", 5)),
    (("记录人员：", 1), ("@记录人员", 2), ("记录时间：", 2), ("@记录时间", 1)),
    (("会议内容：", 6),),
    (("", 6),),  # 正文①（占位标记在 render_table 里用行号定位）
    (("已解决问题：", 6),),
    (("", 6),),  # 正文②
    (("待解决问题：", 6),),
    (("", 6),),  # 正文③
    (("备注：", 6),),
    (("", 6),),  # 正文④
)

# 正文行号（0 起）→ 区块名，顺序与上表空行一致
BODY_ROW_SECTIONS: tuple[tuple[int, str], ...] = (
    (5, "会议内容"),
    (7, "已解决问题"),
    (9, "待解决问题"),
    (11, "备注"),
)

# 字体栈沿用 tools/make_pdf.py 的 CSS（CI 靠 fonts-noto-cjk 出中文）
CSS = """
@page { size: A4; margin: 25.4mm 31.75mm; }
* { box-sizing: border-box; }
html, body { margin: 0; padding: 0; }
body {
  font-family: "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei",
               "Noto Sans CJK SC", "WenQuanYi Micro Hei", sans-serif;
  font-size: 10.5pt; line-height: 1.5; color: #000;
}
.sheet { width: 146.5mm; margin: 0 auto; }

/* 第 1 行：左「汕头大学计算机系」右「编号：…」两端对齐成一行 */
.head-line { display: flex; justify-content: space-between; align-items: baseline;
             font-size: 9pt; line-height: 1.4; }

/* 第 2 行：居中「会议记录」 */
h1.title { font-size: 18pt; font-weight: 700; text-align: center;
           margin: 2mm 0 2mm; line-height: 1.3; letter-spacing: 0.05em; }

/* 第 3 行：左「日期：…」右「第X组」 */
.sub-line { display: flex; justify-content: space-between; align-items: baseline;
            font-family: KaiTi, STKaiti, "楷体", "Kaiti SC", serif;
            font-size: 10.5pt; margin-bottom: 1.5mm; }
.sub-line .group { text-decoration: underline; text-underline-offset: 2px; }
.sub-line .date { text-decoration: underline; text-underline-offset: 2px; }

/* 表单：12 行 6 列网格，全边框 0.5pt，行允许跨页（不加 break-inside: avoid）
   模板实测：所有单元格 w:sz=24（12pt）；11 个标签格（主持人/会议主题/开始时间/
   结束时间/参加人员/记录人员/记录时间 + 会议内容/已解决问题/待解决问题/备注）
   带 w:shd fill="99ccff" 浅蓝底纹、非加粗；值格与正文格无底纹。 */
table.form { border-collapse: collapse; width: 146.5mm; table-layout: fixed;
             font-family: "Noto Sans CJK SC", "Songti SC", SimSun, serif; }
table.form col.c0 { width: 23.5mm; }
table.form col.c1 { width: 37mm; }
table.form col.c2 { width: 12.5mm; }
table.form col.c3 { width: 19mm; }
table.form col.c4 { width: 18mm; }
table.form col.c5 { width: 36.5mm; }
table.form td { border: 0.5pt solid #000; padding: 0 1.9mm; font-size: 12pt;
                vertical-align: top; word-break: break-word; overflow-wrap: anywhere; }
/* 标签格：浅蓝底纹 #99ccff、非加粗（与模板 w:shd 一致） */
table.form td.label { text-align: left; white-space: nowrap; vertical-align: middle;
                      background: #99ccff; font-weight: normal; }
table.form td.value { vertical-align: middle; }
table.form td.body { vertical-align: top; }

/* 正文块：每块一个 <p>/<li>，行高 1.5，段间收紧 */
.body p, .body li { margin: 0 0 0.6mm; line-height: 1.5; }
.body p:last-child, .body ul:last-child, .body ol:last-child { margin-bottom: 0.6mm; }
.body ul, .body ol { margin: 0 0 0.6mm; padding-left: 0; list-style: none; }
.body li { text-indent: 0; }
.body .mk { display: inline-block; margin-right: 0.4em; }
/* 等宽片段：字体栈跟随正文（避免混排拆 run）；比表格正文 12pt 略小以保留行的等宽观感 */
code { font-family: inherit; font-size: 11pt; }
strong { font-weight: 700; }
"""


def _esc(text: str) -> str:
    return html.escape(text, quote=False)


def render_inline(text: str) -> str:
    """行内 Markdown → HTML（`**粗**` / `` `等宽` ``，其余转义）。"""
    out: list[str] = []
    for seg in parse_inline(text):
        body = _esc(seg.text)
        if seg.bold:
            body = f"<strong>{body}</strong>"
        if seg.mono:
            body = f"<code>{body}</code>"
        out.append(body)
    return "".join(out)


def render_block(block: Block) -> str:
    """一个 Block → `<p>` 或 `<li>`；列表项前缀用 `Block.marker()`。

    层级缩进 `level × 1.2em`，左右都缩进（更像 Word 的多级列表观感）。
    """
    indent = f"margin-left:{block.level * 1.2:.1f}em; margin-right:{block.level * 1.2:.1f}em;"
    marker = block.marker()
    mk = f'<span class="mk">{_esc(marker)}</span>' if marker else ""
    inner = f"{mk}{render_inline(block.text)}"
    if block.kind == "p":
        return f'<p style="{indent}">{inner}</p>'
    return f'<div style="{indent}"><span class="mk-line">{inner}</span></div>'


def render_section(blocks: tuple[Block, ...]) -> str:
    """一个区块的全部 Block → HTML 序列。"""
    return "\n".join(render_block(b) for b in blocks)


def render_table(minutes: Minutes) -> str:
    """渲染 12 行 6 列表单表格。"""
    assert all(sum(s for _, s in row) == 6 for row in TABLE_ROWS), "每行跨列数必须合计 6"
    body_by_row = {r: render_section(minutes.sections.get(k, ()))
                   for r, k in BODY_ROW_SECTIONS}
    rows: list[str] = []
    for idx, row in enumerate(TABLE_ROWS):
        cells: list[str] = []
        for text, span in row:
            span_attr = f' colspan="{span}"' if span > 1 else ""
            if text.startswith("@"):
                key = text[1:]
                cells.append(f'<td class="value"{span_attr}>{_esc(minutes.field(key))}</td>')
            elif text == "":
                cells.append(f'<td class="body"{span_attr}>{body_by_row.get(idx, "")}</td>')
            else:
                cells.append(f'<td class="label"{span_attr}>{_esc(text)}</td>')
        rows.append("<tr>" + "".join(cells) + "</tr>")
    cols = "".join(f'<col class="c{i}" style="width:{COL_MM[i]:g}mm">' for i in range(6))
    return ("<table class=\"form\">\n<colgroup>" + cols + "</colgroup>\n"
            + "\n".join(rows) + "\n</table>")


def render_html(minutes: Minutes) -> str:
    """一份会议记录 → 完整 HTML 文档字符串（幂等，无时间戳）。"""
    title = f"会议记录 {minutes.date} {minutes.group}".strip()
    return (
        "<!doctype html>\n<html lang=\"zh-CN\">\n<head>\n"
        "<meta charset=\"utf-8\">\n"
        f"<title>{_esc(title)}</title>\n"
        f"<style>{CSS}</style>\n</head>\n<body>\n"
        '<div class="sheet">\n'
        '<div class="head-line">'
        "<span>汕头大学计算机系</span>"
        f'<span>编号：{_esc(minutes.code)}</span>'
        "</div>\n"
        '<h1 class="title">会议记录</h1>\n'
        '<div class="sub-line">'
        f'<span class="date">日期：{_esc(minutes.date)}</span>'
        f'<span class="group">{_esc(minutes.group)}</span>'
        "</div>\n"
        f"{render_table(minutes)}\n"
        "</div>\n</body>\n</html>\n"
    )


# ---------------------------------------------------------------- 内容完整性核对

# pdftotext 会丢失/重排某些标点（尤其是等宽 code 片段里的半角数字与 +、以及【】），
# 因此比对时把空白与常见标点一律剔除，只校验汉字/字母/数字等实义字符的命中。
_NOISE_RE = re.compile(r"[\s\u3000「」『』【】()（）\[\]<>《》，,。.;；:：'\"`~!！?？+\-*/\\|=_→←\-—]")


def normalize(text: str) -> str:
    """空白 + 标点归一化（剔除抽取噪声），便于跨渲染器比对实义字符。"""
    return _NOISE_RE.sub("", text)


def _first_chars(text: str, n: int = 20) -> str:
    """取纯文本的前 n 个「实义字符」（跳过标点/空白），与 PDF 侧同一口径。"""
    cleaned = normalize(text)
    return cleaned[:n]


def check_pdf(minutes: Minutes, pdf: Path) -> tuple[int, int, list[str]]:
    """用 pdftotext -layout 抽取文本，核对每个 Block 正文前 20 字符是否命中。

    返回 (命中数, 总数, 未命中描述列表)。
    """
    import subprocess

    res = subprocess.run(
        ["pdftotext", "-layout", str(pdf), "-"],
        capture_output=True, text=True, encoding="utf-8",
    )
    if res.returncode != 0:
        return 0, 0, [f"pdftotext 失败：{res.stderr.strip()[:200]}"]
    haystack = normalize(res.stdout)
    hit = total = 0
    misses: list[str] = []
    for key in SECTION_KEYS:
        for i, block in enumerate(minutes.sections.get(key, ())):
            total += 1
            needle = _first_chars(plain(block.text))
            if needle and needle in haystack:
                hit += 1
            else:
                misses.append(f"{key}[{i}] 未命中：{needle}")
    return hit, total, misses


def main() -> int:
    ap = argparse.ArgumentParser(description="会议记录 → 老师模板同版式 A4 PDF")
    ap.add_argument("--only", action="append", metavar="SLUG",
                    help="只渲染指定 slug（可重复）")
    ap.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR,
                    help=f"PDF 输出目录（默认 {DEFAULT_OUT_DIR.relative_to(ROOT)}）")
    ap.add_argument("--keep-html", type=Path, default=None,
                    help="保留中间 HTML 到该目录（调试用）")
    ap.add_argument("--check", action="store_true",
                    help="渲染后额外做内容完整性机械核对（需 pdftotext）")
    ap.add_argument("--check-only", action="store_true",
                    help="不渲染，只核对已存在的 PDF")
    args = ap.parse_args()

    items = load_all()
    if args.only:
        wanted = set(args.only)
        items = [m for m in items if m.slug in wanted]
        missing = wanted - {m.slug for m in items}
        if missing:
            print(f"❌ 找不到会议记录：{', '.join(sorted(missing))}", file=sys.stderr)
            return 1
    if not items:
        print("❌ minutes/ 下没有可渲染的 .md", file=sys.stderr)
        return 1

    args.out_dir.mkdir(parents=True, exist_ok=True)
    if args.keep_html:
        args.keep_html.mkdir(parents=True, exist_ok=True)

    summary: list[tuple[str, int, int]] = []  # (slug, 页数, 字节数)
    check_failed = False

    if not args.check_only:
        chrome = find_chrome()
        print(f"chrome: {chrome}")
        print(f"输出目录: {args.out_dir}")
        print(f"会议记录 {len(items)} 份\n")
        tmp_holder: tempfile.TemporaryDirectory | None = None
        if args.keep_html:
            html_dir = args.keep_html
        else:
            tmp_holder = tempfile.TemporaryDirectory(prefix="toposort_minutes_")
            html_dir = Path(tmp_holder.name)
        try:
            for m in items:
                html_path = html_dir / f"{m.slug}.html"
                html_path.write_text(render_html(m), encoding="utf-8")
                pdf_path = args.out_dir / f"{m.slug}.pdf"
                html_to_pdf(chrome, html_path, pdf_path)
                pages = pdf_pages(pdf_path)
                size = pdf_path.stat().st_size
                summary.append((m.slug, pages, size))
                print(f"✅ {m.slug} → {pdf_path} ({pages} 页, {size:,} B)")
        finally:
            if tmp_holder is not None:
                tmp_holder.cleanup()

    if args.check or args.check_only:
        print("\n=== 内容完整性核对（pdftotext -layout）===")
        for m in items:
            pdf = args.out_dir / f"{m.slug}.pdf"
            if not pdf.exists():
                print(f"❌ {m.slug}: 缺少 {pdf}")
                check_failed = True
                continue
            hit, total, misses = check_pdf(m, pdf)
            status = "✅" if hit == total else "❌"
            print(f"{status} {m.slug}: 命中块数/总块数 = {hit}/{total}")
            for miss in misses:
                print(f"     - {miss}")
            if hit != total:
                check_failed = True

    if summary:
        print("\n=== 汇总（slug / 页数 / 字节数）===")
        for slug, pages, size in summary:
            print(f"{slug}\t{pages}\t{size}")
        print(f"合计 {len(summary)} 份")

    return 1 if check_failed else 0


def pdf_pages(pdf: Path) -> int:
    """读 PDF 页数（直接用 pdfinfo，缺工具时回退为统计 /Type /Page）。"""
    import shutil
    import subprocess

    if shutil.which("pdfinfo"):
        res = subprocess.run(["pdfinfo", str(pdf)], capture_output=True,
                             text=True, encoding="utf-8")
        for line in res.stdout.splitlines():
            if line.startswith("Pages:"):
                return int(line.split(":", 1)[1].strip())
    return pdf.read_bytes().count(b"/Type /Page") - pdf.read_bytes().count(b"/Type /Pages")


if __name__ == "__main__":
    sys.exit(main())
