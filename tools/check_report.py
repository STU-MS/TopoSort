#!/usr/bin/env python3
"""《项目报告》成品机械验收（T6 / issue #43）。

只做**能机械判定**的检查，不做主观文风评判。检查项：

  1. `submission/00-项目报告.docx` 存在且能被 officecli 解析；
  2. 八章齐全、层级与老师模板一致（`标题 1` × 8、`标题 2` × 3），且章节顺序正确；
  3. 图题/表题编号按章连续、不重号、不跳号，且**正文里引用到了**（「图 X-Y」「表 X-Y」）；
  4. 无残留：`http` 链接、`完整内容见`、老师模板示例标题「校园行走最优路径查询系统」；
  5. 目录是真的 `TOC` 域；缓存页码单调不减且不全相同（防「域没更新、11 条全 5」）；
     settings 里置了 `updateFields`（Word 打开时重算页码）；
  6. 图片数量与图题数量一致；
  7. 每张图的墨迹宽度 ≥ 画布宽度 70%——画布对但内容缩在一角的图，插进文档后
     图内文字会被整体缩到看不清（实测踩过：mermaid stateDiagram 被按 CSS
     「默认对象尺寸 300×150」渲染，内容只占画布 27%）；
  8. `submission/00-项目报告.pdf` 缺失时给**告警**（由组长导出），不算失败。PDF 允许改名，
     认「00-项目报告.pdf」或 submission/ 下任何含「项目报告」的 PDF。

用法：
    uv run python tools/check_report.py            # 检查默认成品
    uv run python tools/check_report.py --docx /path/to/x.docx

退出码 0 = 全部通过（PDF 缺失只告警）；1 = 有不合格项。
"""
from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # tools/ 同级模块
import png_ink  # noqa: E402

# 墨迹宽度占画布宽度的下限，与 tools/gen_diagrams.py 的 INK_MIN_WIDTH_RATIO 同义：
# 低于它的图在纸面上会被整体缩小到看不清，属于交付缺陷而非风格问题。
INK_MIN_WIDTH_RATIO = 0.70

# 目录条目样式的名字：Word 存成 toc 1/toc 2（id=TOC1…），ONLYOFFICE 存成 目录 1/目录 2
# （id 是数字，如 919）。两种都要认，见下方正则。

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DOCX = ROOT / "submission" / "00-项目报告.docx"
DEFAULT_PDF = ROOT / "submission" / "00-项目报告.pdf"


def resolve_report_pdf(explicit: Path | None = None) -> Path:
    """报告 PDF 允许改名（组长起的「…-项目报告-Group01.pdf」也认）。

    顺序：显式 --pdf > 00-项目报告.pdf > submission/ 下第一个含「项目报告」的 PDF；
    都没找到时返回预期路径，由调用方给出「未就位」告警。
    """
    if explicit is not None and explicit.exists():
        return explicit
    if DEFAULT_PDF.exists():
        return DEFAULT_PDF
    for cand in sorted((ROOT / "submission").glob("*项目报告*.pdf")):
        return cand
    return explicit if explicit is not None else DEFAULT_PDF

CHAPTERS = (
    "软硬件环境",
    "需求分析",
    "详细设计",
    "运行结果截图",
    "测试（测试用例设计、运行结果）",
    "系统特色以及可扩展点",
    "感想",
    "附件（会议记录）",
)
SUBSECTIONS = ("类设计", "核心流程描述", "核心算法设计")

FORBIDDEN = {
    "http": "长 URL（正文不应出现链接）",
    "完整内容见": "把正文外包给别的文件的跳转句",
    "校园行走最优路径查询系统": "老师模板里的示例标题残留",
    "TODO": "待办标记残留",
}

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


def officecli() -> str:
    found = shutil.which("officecli") or str(Path.home() / ".local" / "bin" / "officecli")
    if not Path(found).exists():
        raise SystemExit("❌ 找不到 officecli")
    return found


def main() -> int:
    ap = argparse.ArgumentParser(description="《项目报告》成品机械验收")
    ap.add_argument("--docx", type=Path, default=DEFAULT_DOCX)
    ap.add_argument("--pdf", type=Path, default=DEFAULT_PDF)
    args = ap.parse_args()

    docx: Path = args.docx if args.docx.is_absolute() else ROOT / args.docx
    if not docx.exists():
        fail(f"成品不存在：{docx}（先跑 uv run python tools/build_report.py）")
        return 1
    ok(f"成品存在：{docx.relative_to(ROOT)}（{docx.stat().st_size:,} B）")

    oc = officecli()

    def run(*a: str) -> str:
        res = subprocess.run([oc, *a], capture_output=True, text=True, encoding="utf-8")
        if res.returncode != 0:
            fail(f"officecli {' '.join(a[:2])} 失败：{(res.stderr or res.stdout).strip()[:200]}")
        return res.stdout or ""

    # ---- 1. 可解析 + 章节结构 -------------------------------------------------
    outline = run("view", str(docx), "outline")
    text = run("view", str(docx), "text")

    for name in CHAPTERS:
        if not re.search(rf'\]\s+"{re.escape(name)}"\s+\(标题 1\)', outline):
            fail(f"缺少一级标题（标题 1）：{name}")
    for name in SUBSECTIONS:
        if not re.search(rf'\]\s+"{re.escape(name)}"\s+\(标题 2\)', outline):
            fail(f"缺少二级标题（标题 2）：{name}")
    if not FAILURES:
        ok(f"章节结构齐全：标题 1 × {len(CHAPTERS)}、标题 2 × {len(SUBSECTIONS)}")

    # 章节顺序（按 outline 出现位置）
    positions = [outline.find(f'"{n}" (标题 1)') for n in CHAPTERS]
    if all(p >= 0 for p in positions) and positions != sorted(positions):
        fail(f"章节顺序与老师模板不一致：{positions}")

    # ---- 2. 图表编号 ---------------------------------------------------------
    fig_nums = re.findall(r"图\s*(\d+)-(\d+)\s", text)
    tab_nums = re.findall(r"表\s*(\d+)-(\d+)\s", text)

    def check_numbering(kind: str, nums: list[tuple[str, str]]) -> None:
        seen: dict[int, set[int]] = {}
        for chapter, index in nums:
            seen.setdefault(int(chapter), set()).add(int(index))
        if not seen:
            fail(f"没有找到任何{kind}题注/引用")
            return
        problems = []
        for chapter in sorted(seen):
            idx = sorted(seen[chapter])
            if idx != list(range(1, len(idx) + 1)):
                problems.append(f"第{chapter}章 {kind}编号不连续：{idx}")
        if problems:
            fail("；".join(problems))
        else:
            summary = "、".join(f"第{c}章 {len(seen[c])} 个" for c in sorted(seen))
            ok(f"{kind}编号按章连续：{summary}")

    check_numbering("图", fig_nums)
    check_numbering("表", tab_nums)

    # 正文引用：每个题注编号在正文里至少出现两次（题注本身 + 正文引用）
    for kind, nums in (("图", fig_nums), ("表", tab_nums)):
        missing = [
            f"{kind}{c}-{i}"
            for (c, i) in sorted(set(nums))
            if len(re.findall(rf"{kind}\s*{c}-{i}(?!\d)", text)) < 2
        ]
        if missing:
            fail(f"{kind}题注未在正文中被引用：{missing[:6]}{' …' if len(missing) > 6 else ''}")

    # ---- 3. 图片数量与图题一致 ----------------------------------------------
    file_line = next((l for l in outline.splitlines() if l.startswith("File:")), "")
    m = re.search(r"(\d+)\s+images", file_line)
    n_images = int(m.group(1)) if m else None
    n_figs = len(set(fig_nums))
    if n_images is not None and n_images != n_figs:
        fail(f"图片数（{n_images}）与图题数（{n_figs}）不一致")
    elif n_images is not None:
        ok(f"图片数（{n_images}）与图题数一致（{n_figs}）")

    # ---- 4. 残留检查 ---------------------------------------------------------
    for needle, why in FORBIDDEN.items():
        hit = text.count(needle)
        if hit:
            fail(f"发现 {hit} 处「{needle}」（{why}）")
    if not any(needle in text for needle in FORBIDDEN):
        ok("无长 URL、无「完整内容见」、无模板示例标题残留")

    # ---- 5. 目录域与 updateFields -------------------------------------------
    with zipfile.ZipFile(docx) as z:
        document = z.read("word/document.xml").decode("utf-8")
        settings = z.read("word/settings.xml").decode("utf-8")
        styles = z.read("word/styles.xml").decode("utf-8")
        media = sorted(n for n in z.namelist() if n.startswith("word/media/"))
        media_blobs = [(n, z.read(n)) for n in media]
    if 'TOC \\o' not in document:
        fail("目录不是真的 TOC 域（未找到 TOC \\o 指令）")
    else:
        # 目录条目样式必须通过 styles.xml 把 styleId 映回名字再判：Word（toc 1…）与
        # ONLYOFFICE（目录 1…）保存时用的 id 完全不同，直接数 "TOC1" 会误报 0 条。
        style_name = dict(re.findall(r'w:styleId="([^"]+)"[^>]*>\s*<w:name w:val="([^"]*)"', styles))
        toc_styles = {sid for sid, nm in style_name.items()
                      if re.fullmatch(r"(toc|目录)\s*[1-9]", nm.strip().lower())}
        entries = sum(
            1 for p in re.findall(r"<w:p[ >].*?</w:p>", document, re.S)
            if (m := re.search(r'w:pStyle w:val="([^"]+)"', p)) and m.group(1) in toc_styles
            and "".join(re.findall(r"<w:t[^>]*>([^<]*)</w:t>", p)).strip()
        )
        if entries:
            ok(f"目录是真 TOC 域，含 {entries} 个目录条目")
        else:
            warn("目录是 TOC 域但没有可识别的目录条目段落：靠 updateFields 让 Word 重建，"
                 "导出 PDF 前请确认目录完整")
    if "updateFields" not in settings:
        warn("settings.xml 未置 updateFields：Word 打开时可能不重算目录页码（可在 Word 里 Ctrl+A → F9）")
    else:
        ok("已置 updateFields：Word 打开时自动重算目录页码与页码域")

    # 目录缓存页码：ONLYOFFICE 导出 PDF 会更新 PAGE/NUMPAGES 域，却**不更新 TOC 域**，
    # 于是 PDF 目录里 11 条页码会全是模板残留值（实测全为 5）。这里机械拦一道。
    pagenums = []
    for m in re.finditer(r" PAGEREF (_Toc\w+)[^<]*</w:instrText></w:r>(.*?)"
                         r'<w:fldChar w:fldCharType="end"', document, re.S):
        nums = re.findall(r"<w:t[^>]*>(\d+)</w:t>", m.group(2))
        if nums:
            pagenums.append(int(nums[0]))
    if pagenums:
        if len(set(pagenums)) == 1:
            fail(f"目录缓存页码全是 {pagenums[0]}（TOC 域从未更新）：导出 PDF 前必须在 Word 里"
                 "更新域（目录上右键 → 更新域 → 更新整个目录），否则 PDF 目录页码全错")
        elif pagenums != sorted(pagenums):
            warn(f"目录缓存页码不是单调不减：{pagenums}")
        else:
            ok(f"目录缓存页码已就位且单调不减：{pagenums}")

    # ---- 7. 图能不能看清（墨迹占画布宽度的比例）------------------------------
    unreadable: list[str] = []
    n_checked = 0
    for name, blob in media_blobs:
        if not blob[:8] == b"\x89PNG\r\n\x1a\n":
            continue
        n_checked += 1
        cover_w, cover_h, ink = png_ink.ink_coverage(blob)
        w, h, _nch, _px = png_ink.decode(blob)
        flag = ""
        if cover_w < INK_MIN_WIDTH_RATIO:
            unreadable.append(
                f"{name}（{w}x{h}，墨迹只占宽 {cover_w:.0%}，"
                f"留白 左{ink[0]} 右{w - 1 - ink[2]}）"
            )
            flag = "  ← 内容缩在一角，纸面上会小到看不清"
        print(f"   {name}  {w}x{h}  墨迹占宽 {cover_w:.0%} 高 {cover_h:.0%}{flag}")
    if unreadable:
        fail(f"{len(unreadable)} 张图在纸面上会被缩到看不清：{'；'.join(unreadable)}\n"
             "   修法：重跑 uv run python tools/gen_diagrams.py，或把该图源改稀/改横向")
    else:
        ok(f"{n_checked} 张 PNG 的墨迹宽度都 ≥ {INK_MIN_WIDTH_RATIO:.0%}，纸面上不会糊成一片")

    # ---- 8. 报告 PDF ---------------------------------------------------------
    pdf_arg = None if args.pdf == DEFAULT_PDF else (args.pdf if args.pdf.is_absolute() else ROOT / args.pdf)
    pdf = resolve_report_pdf(pdf_arg)
    if pdf.exists():
        ok(f"报告 PDF 就位：{pdf.relative_to(ROOT)}（{pdf.stat().st_size:,} B）")
    else:
        warn(f"报告 PDF 未就位（{pdf.relative_to(ROOT)}）：需由组长导出后放入 submission/")

    print("\n" + "=" * 60)
    if FAILURES:
        print(f"❌ 验收不通过：{len(FAILURES)} 项不合格，{len(WARNINGS)} 项告警")
        return 1
    print(f"✅ 验收通过（{len(WARNINGS)} 项告警）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
