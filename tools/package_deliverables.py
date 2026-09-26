#!/usr/bin/env python3
"""组装最终交付包 group01.zip（提交 mySTU）。

材料来源统一为 `submission/`（由 tools/build_submission.py 刷新）。
`deliverables/` 只作为素材/过程文档，不再直接进包（避免重复）。

包内结构：
    group01/
    ├── 00-项目报告.pdf / .docx
    ├── readme.txt
    ├── 会议记录/
    ├── 个人任务及感想/
    ├── 演示视频/
    ├── 源程序/           git 跟踪文件快照（排除 submission/ 与 deliverables 的 pdf/docx）
    └── 提交说明.txt

用法：
    uv run python tools/build_submission.py    # 先刷新 submission/
    uv run python tools/package_deliverables.py

产物：仓库根目录 group01.zip（已 gitignore）
"""
from __future__ import annotations

import subprocess
import sys
import zipfile
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SUBMISSION = ROOT / "submission"
ZIP_PATH = ROOT / "group01.zip"

# 源程序快照里排除的目录前缀（避免与单独的 PDF/docx 目录重复）
SOURCE_EXCLUDE_PREFIXES = (
    "submission/",  # 提交材料目录，单独打包
    "deliverables/pdf/",  # 与 会议记录/ 个人任务及感想 重复
    "deliverables/docx/",
)


def git_tracked_files() -> list[Path]:
    # 用 -z（NUL 分隔）避免 git 对非 ASCII 路径做八进制转义/加引号
    out = subprocess.run(
        ["git", "-C", str(ROOT), "ls-files", "-z"],
        capture_output=True,
    )
    if out.returncode != 0:
        sys.exit("❌ 无法执行 git ls-files。")
    files = []
    for line in out.stdout.decode("utf-8").split("\0"):
        if not line:
            continue
        if any(line.startswith(pref) for pref in SOURCE_EXCLUDE_PREFIXES):
            continue
        p = ROOT / line
        if p.exists():
            files.append(p)
    return files


def dir_files(d: Path) -> list[Path]:
    if not d.is_dir():
        return []
    return sorted(p for p in d.iterdir() if p.is_file())


def find_videos() -> list[Path]:
    """演示视频：优先 submission/演示视频/，兼容旧的 deliverables/*.mp4。"""
    vids = [p for p in dir_files(SUBMISSION / "演示视频") if p.suffix.lower() == ".mp4"]
    vids += sorted((ROOT / "deliverables").glob("*.mp4"))
    return vids


def main() -> int:
    if not SUBMISSION.is_dir():
        sys.exit("❌ submission/ 不存在，请先运行 uv run python tools/build_submission.py")

    readme = SUBMISSION / "readme.txt"
    report_pdf = SUBMISSION / "00-项目报告.pdf"
    report_docx = SUBMISSION / "00-项目报告.docx"
    minutes = dir_files(SUBMISSION / "会议记录")
    personal = dir_files(SUBMISSION / "个人任务及感想")
    videos = find_videos()
    source = git_tracked_files()

    # 防回归：非 ASCII 路径曾因 git 引号转义被静默漏掉，此处显式断言关键目录已纳入
    rel = [p.relative_to(ROOT).as_posix() for p in source]
    for need in ("deliverables/", "minutes/", "app/"):
        if not any(r.startswith(need) for r in rel):
            sys.exit(f"❌ 源程序快照缺少 {need}，打包中止（请检查 git_tracked_files）。")

    # 存在性校验：缺项写进「未闭环项」，不崩溃
    missing: list[str] = []
    if not report_pdf.exists():
        missing.append("00-项目报告.pdf（组长从 readme 模板导出后放入 submission/）")
    if not report_docx.exists():
        missing.append("00-项目报告.docx（T4 报告构建产出后放入 submission/）")
    if not readme.exists():
        missing.append("readme.txt（运行 tools/build_submission.py 从根目录同步）")
    if not minutes:
        missing.append("会议记录/ 为空（应为 5 组 docx+pdf）")
    if not personal:
        missing.append("个人任务及感想/ 为空（应为 5 组 docx+pdf）")
    if not videos:
        missing.append("演示视频（submission/演示视频/*.mp4 或 deliverables/*.mp4）尚未就位")

    # 组装清单文本
    stamp = date.today().isoformat()
    manifest = [
        "TopoSort 拓扑排序应用软件 — 第一组 提交材料",
        f"打包日期：{stamp}",
        "",
        "目录结构：",
        "  00-项目报告.pdf              项目报告 PDF（老师模板导出）",
        "  00-项目报告.docx             项目报告 docx（可直接批注）",
        "  readme.txt                   运行环境/配置/如何运行",
        "  会议记录/                    5 次会议记录（docx + pdf）",
        "  个人任务及感想/               5 人个人任务及感想（docx + pdf）",
        "  演示视频/                    演示视频（≤50M）",
        "  源程序/                      整个项目源码快照（git 跟踪文件，含 app/、tools/、evidence/、readme.txt）",
        "  提交说明.txt                 本文件",
        "",
        f"会议记录：{len(minutes)} 份  |  个人任务及感想：{len(personal)} 份  |  视频：{len(videos)} 个",
    ]
    if missing:
        manifest += ["", "⚠️ 未闭环项（打包时缺失，请补齐后重跑）："] + [f"  - {m}" for m in missing]

    # 写 zip
    if ZIP_PATH.exists():
        ZIP_PATH.unlink()
    with zipfile.ZipFile(ZIP_PATH, "w", zipfile.ZIP_DEFLATED) as z:
        if report_pdf.exists():
            z.write(report_pdf, "group01/00-项目报告.pdf")
        if report_docx.exists():
            z.write(report_docx, "group01/00-项目报告.docx")
        if readme.exists():
            z.write(readme, "group01/readme.txt")
        for p in minutes:
            z.write(p, f"group01/会议记录/{p.name}")
        for p in personal:
            z.write(p, f"group01/个人任务及感想/{p.name}")
        for p in videos:
            z.write(p, f"group01/演示视频/{p.name}")
        # 源程序快照
        for p in source:
            z.write(p, f"group01/源程序/{p.relative_to(ROOT).as_posix()}")
        # 提交说明
        z.writestr("group01/提交说明.txt", "\n".join(manifest) + "\n")

    size = ZIP_PATH.stat().st_size
    print("\n".join(manifest))
    print("\n" + "=" * 48)
    print(f"✅ 已生成 {ZIP_PATH.name}  体积 {size:,} B ({size / 1024 / 1024:.1f} MB)")
    print(
        f"   源程序文件 {len(source)} 个 · 会议记录 {len(minutes)} 份 · "
        f"个人任务及感想 {len(personal)} 份 · 视频 {len(videos)} 个"
    )
    if missing:
        print("⚠️ 仍有未闭环项：\n   - " + "\n   - ".join(missing))
    return 0


if __name__ == "__main__":
    sys.exit(main())
