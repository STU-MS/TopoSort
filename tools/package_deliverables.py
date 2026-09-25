#!/usr/bin/env python3
"""组装最终交付包 group01.zip（提交 mySTU）。

按老师任务书「提交材料」组装，内含 8 类材料。源程序快照用 `git ls-files` 获取，
天然排除 .venv/dist/build/.git/__pycache__ 与本脚本产物（均已在 .gitignore）。

用法：
    uv run python tools/package_deliverables.py            # 先确保 PDF 存在再打包
    uv run python tools/package_deliverables.py --rebuild  # 强制重跑 make_pdf.py

产物：仓库根目录 group01.zip
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import zipfile
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PDF_DIR = ROOT / "deliverables" / "pdf"
DOCX_DIR = ROOT / "deliverables" / "docx"
ZIP_PATH = ROOT / "group01.zip"

EXPECTED_PDF = 17  # 00-06(7) + personal(5) + minutes(5)


def run_make_pdf() -> None:
    print("→ 生成 PDF / docx（tools/make_pdf.py）…")
    res = subprocess.run([sys.executable, str(ROOT / "tools" / "make_pdf.py")])
    if res.returncode != 0:
        sys.exit("❌ make_pdf.py 失败，终止打包。")


def git_tracked_files() -> list[Path]:
    out = subprocess.run(
        ["git", "-C", str(ROOT), "ls-files"],
        capture_output=True, text=True, encoding="utf-8",
    )
    if out.returncode != 0:
        sys.exit("❌ 无法执行 git ls-files。")
    files = []
    for line in out.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        p = ROOT / line
        # 源程序快照排除已单独成目录的 PDF/docx（避免重复）
        if line.startswith("deliverables/pdf/") or line.startswith("deliverables/docx/"):
            continue
        if p.exists():
            files.append(p)
    return files


def find_videos() -> list[Path]:
    return sorted(p for p in (ROOT / "deliverables").glob("*.mp4"))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rebuild", action="store_true", help="强制重跑 make_pdf.py")
    args = ap.parse_args()

    pdfs = sorted(PDF_DIR.glob("*.pdf"))
    if args.rebuild or len(pdfs) < EXPECTED_PDF:
        run_make_pdf()
        pdfs = sorted(PDF_DIR.glob("*.pdf"))

    docxs = sorted(DOCX_DIR.glob("*.docx"))
    videos = find_videos()
    source = git_tracked_files()
    readme = ROOT / "readme.txt"

    # 缺口检查
    missing: list[str] = []
    if len(pdfs) < EXPECTED_PDF:
        missing.append(f"PDF 数量不足：{len(pdfs)}/{EXPECTED_PDF}")
    if not videos:
        missing.append("演示视频（deliverables/*.mp4）尚未就位（T17 / issue #32）")
    if not readme.exists():
        missing.append("readme.txt 缺失")

    # 组装清单文本
    stamp = date.today().isoformat()
    manifest = [
        "TopoSort 拓扑排序应用软件 — 第一组 提交材料",
        f"打包日期：{stamp}",
        "",
        "目录结构：",
        "  00-项目报告.pdf              项目报告（含运行界面截图）",
        "  readme.txt                   运行环境/配置/如何运行",
        "  文档PDF/                     所有交付文档的 PDF（00-06 + 个人感想 + 会议记录）",
        "  文档Word/                    对应 docx（Word 格式，便于批注）",
        "  会议记录PDF/                 会议记录 PDF（另在 文档PDF/ 也有）",
        "  源程序/                      整个项目源码快照（git 跟踪文件，含 md 源、evidence、readme.txt）",
        "  演示视频/                    演示视频（≤50M）",
        "  提交说明.txt                 本文件",
        "",
        f"PDF 份数：{len(pdfs)}  |  docx 份数：{len(docxs)}  |  视频：{len(videos)} 个",
    ]
    if missing:
        manifest += ["", "⚠️ 未闭环项（打包时缺失，请补齐后重跑）："] + [f"  - {m}" for m in missing]

    # 写 zip
    if ZIP_PATH.exists():
        ZIP_PATH.unlink()
    with zipfile.ZipFile(ZIP_PATH, "w", zipfile.ZIP_DEFLATED) as z:
        # 顶层项目报告与 readme
        report_pdf = PDF_DIR / "00-项目报告.pdf"
        if report_pdf.exists():
            z.write(report_pdf, "group01/00-项目报告.pdf")
        if readme.exists():
            z.write(readme, "group01/readme.txt")
        # 文档 PDF / docx
        for p in pdfs:
            z.write(p, f"group01/文档PDF/{p.name}")
            if p.name.startswith("2026-"):
                z.write(p, f"group01/会议记录PDF/{p.name}")
        for p in docxs:
            z.write(p, f"group01/文档Word/{p.name}")
        # 源程序快照
        for p in source:
            z.write(p, f"group01/源程序/{p.relative_to(ROOT).as_posix()}")
        # 演示视频
        for p in videos:
            z.write(p, f"group01/演示视频/{p.name}")
        # 提交说明
        z.writestr("group01/提交说明.txt", "\n".join(manifest) + "\n")

    size = ZIP_PATH.stat().st_size
    print("\n".join(manifest))
    print("\n" + "=" * 48)
    print(f"✅ 已生成 {ZIP_PATH.name}  体积 {size:,} B ({size / 1024 / 1024:.1f} MB)")
    print(f"   源程序文件 {len(source)} 个 · PDF {len(pdfs)} 份 · docx {len(docxs)} 份 · 视频 {len(videos)} 个")
    if missing:
        print("⚠️ 仍有未闭环项：\n   - " + "\n   - ".join(missing))
    return 0


if __name__ == "__main__":
    sys.exit(main())
