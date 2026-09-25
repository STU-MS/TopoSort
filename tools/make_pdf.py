#!/usr/bin/env python3
"""把交付 Markdown 批量转成 PDF（并顺带产出 docx）。

方案见 evidence/decisions/2026-09-25-doc转PDF方案.md（pandoc + Chrome headless，零新增仓库依赖）。

用法：
    uv run python tools/make_pdf.py            # 转换全部
    uv run python tools/make_pdf.py --skip-docx

依赖（本机外部工具，非仓库依赖）：
    - pandoc           （PATH 中可找到，或设 PANDOC 环境变量）
    - Google Chrome / Chromium / Edge（设 CHROME_PATH 可覆盖）

产物：
    deliverables/pdf/<stem>.pdf     每个源 .md 一份，同名
    deliverables/docx/<stem>.docx   （除非 --skip-docx）
"""
from __future__ import annotations

import argparse
import html
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT_PDF = ROOT / "deliverables" / "pdf"
OUT_DOCX = ROOT / "deliverables" / "docx"

# 源文件：交付文档 + 个人感想 + 会议记录（跳过模板）
SOURCES = (
    sorted((ROOT / "deliverables").glob("*.md"))
    + sorted((ROOT / "deliverables" / "personal").glob("*.md"))
    + sorted(p for p in (ROOT / "minutes").glob("*.md") if not p.name.startswith("_"))
)

CHROME_CANDIDATES = (
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
    "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
)
CHROME_NAMES = (
    "google-chrome",
    "google-chrome-stable",
    "chromium",
    "chromium-browser",
    "microsoft-edge",
    "brave-browser",
)

CSS = """
@page { size: A4; margin: 18mm 16mm; }
* { box-sizing: border-box; }
body {
  font-family: "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei",
               "Noto Sans CJK SC", "WenQuanYi Micro Hei", sans-serif;
  font-size: 12px; line-height: 1.75; color: #111; margin: 0;
}
h1 { font-size: 21px; border-bottom: 2px solid #333; padding-bottom: 6px; }
h2 { font-size: 16px; border-bottom: 1px solid #ccc; padding-bottom: 4px; margin-top: 22px; }
h3 { font-size: 14px; margin-top: 16px; }
h4 { font-size: 13px; }
table { border-collapse: collapse; width: 100%; font-size: 11px; margin: 8px 0; }
th, td { border: 1px solid #999; padding: 4px 6px; vertical-align: top; text-align: left; }
th { background: #f0f0f0; }
pre { background: #f6f8fa; border: 1px solid #ddd; padding: 8px; font-size: 10px;
      white-space: pre-wrap; word-break: break-word; }
code { font-family: Menlo, Consolas, "Courier New", monospace; background: #f0f0f0;
       padding: 0 2px; font-size: 11px; }
pre code { background: none; padding: 0; }
img { max-width: 100%; height: auto; }
blockquote { color: #555; border-left: 3px solid #ccc; margin-left: 0; padding-left: 10px; }
a { color: #0645ad; text-decoration: none; }
"""


def die(msg: str) -> "None":
    print(f"❌ {msg}", file=sys.stderr)
    sys.exit(1)


def find_pandoc() -> str:
    path = os.environ.get("PANDOC") or shutil.which("pandoc")
    if not path:
        die("未找到 pandoc。请安装 pandoc 或设 PANDOC 环境变量。")
    return path


def find_chrome() -> str:
    env = os.environ.get("CHROME_PATH")
    if env and Path(env).exists():
        return env
    for cand in CHROME_CANDIDATES:
        if Path(cand).exists():
            return cand
    for name in CHROME_NAMES:
        found = shutil.which(name)
        if found:
            return found
    die("未找到 Chrome/Chromium。请安装或设 CHROME_PATH 环境变量。")


def md_to_html(pandoc: str, md: Path) -> str:
    body = subprocess.run(
        [pandoc, str(md), "-t", "html", "--metadata", "lang=zh-CN"],
        capture_output=True, text=True, encoding="utf-8",
    )
    if body.returncode != 0:
        die(f"pandoc 转换失败：{md}\n{body.stderr}")
    base = md.parent.resolve().as_uri() + "/"
    title = html.escape(md.stem)
    return (
        "<!doctype html>\n<html lang=\"zh-CN\">\n<head>\n"
        "<meta charset=\"utf-8\">\n"
        f"<title>{title}</title>\n"
        f"<base href=\"{base}\">\n"
        f"<style>{CSS}</style>\n</head>\n<body>\n{body.stdout}\n</body>\n</html>\n"
    )


def html_to_pdf(chrome: str, html_path: Path, pdf_path: Path) -> None:
    cmd = [
        chrome,
        "--headless=new",
        "--disable-gpu",
        "--no-pdf-header-footer",
        "--allow-file-access-from-files",
        "--virtual-time-budget=8000",
    ]
    # GitHub Actions（以及其他 CI）默认设 CI=true。CI 的容器/runner 常以 root 运行，
    # Chrome 的 setuid sandbox 不可用会直接拒绝启动（报 "No usable sandbox!"），
    # 因此 CI 下追加 --no-sandbox。本地运行（无 CI 变量）保持默认沙箱，行为不变。
    if os.environ.get("CI"):
        cmd.append("--no-sandbox")
    cmd += [
        f"--print-to-pdf={pdf_path}",
        html_path.resolve().as_uri(),
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
    if not pdf_path.exists() or pdf_path.stat().st_size == 0:
        die(f"Chrome 未生成 PDF：{pdf_path}\n{res.stderr[-800:]}")


def md_to_docx(pandoc: str, md: Path, docx_path: Path) -> None:
    res = subprocess.run(
        [pandoc, str(md), "-o", str(docx_path)],
        capture_output=True, text=True, encoding="utf-8",
    )
    if res.returncode != 0:
        die(f"pandoc docx 转换失败：{md}\n{res.stderr}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-docx", action="store_true", help="不产出 docx")
    args = ap.parse_args()

    if not SOURCES:
        die("未找到任何源 .md 文件。")

    pandoc = find_pandoc()
    chrome = find_chrome()
    OUT_PDF.mkdir(parents=True, exist_ok=True)
    if not args.skip_docx:
        OUT_DOCX.mkdir(parents=True, exist_ok=True)

    print(f"pandoc: {pandoc}")
    print(f"chrome: {chrome}")
    print(f"源文件 {len(SOURCES)} 个\n")

    ok = 0
    with tempfile.TemporaryDirectory(prefix="toposort_pdf_") as tmp:
        tmpdir = Path(tmp)
        for md in SOURCES:
            rel = md.relative_to(ROOT)
            pdf = OUT_PDF / f"{md.stem}.pdf"
            html_path = tmpdir / f"{md.stem}.html"
            html_path.write_text(md_to_html(pandoc, md), encoding="utf-8")
            html_to_pdf(chrome, html_path, pdf)
            size = pdf.stat().st_size
            line = f"✅ {rel} → deliverables/pdf/{pdf.name} ({size:,} B)"
            if not args.skip_docx:
                docx = OUT_DOCX / f"{md.stem}.docx"
                md_to_docx(pandoc, md, docx)
                line += f"  + docx ({docx.stat().st_size:,} B)"
            print(line)
            ok += 1

    print(f"\n完成：{ok}/{len(SOURCES)} 份转出 PDF。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
