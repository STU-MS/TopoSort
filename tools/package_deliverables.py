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
    uv run python tools/package_deliverables.py              # 自动先刷新 submission/
    uv run python tools/package_deliverables.py --no-refresh # 直接拿现状打包

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


def find_binaries() -> list[Path]:
    """三端可执行产物：submission/可执行程序/ 下全部文件（不含子目录、忽略占位 .gitkeep）。

    由 release.yml 的 package job 在 CI 里注入构建矩阵产物；本机直接打包时
    该目录为空 → 打警告并继续（组员本地自测包不含二进制属正常）。
    """
    return [p for p in dir_files(SUBMISSION / "可执行程序") if p.name != ".gitkeep"]


def refresh_submission() -> None:
    """先跑 tools/build_submission.py 刷新 submission/ 里的派生材料。

    为什么由本脚本自动调：CI 的步骤只有 make_pdf.py → package_deliverables.py，
    没有单独跑 build_submission.py；在这里自动调可保证本机与 CI 行为一致
    （否则 CI 里会议记录/个人感想会直接用仓库里已有副本，与本机刷新的结果不一致）。
    加 --no-refresh 可跳过。
    """
    if "--no-refresh" in sys.argv[1:]:
        print("→ 跳过 submission/ 刷新（--no-refresh）")
        return
    script = ROOT / "tools" / "build_submission.py"
    if not script.exists():
        print("⚠️  未找到 tools/build_submission.py，跳过 submission/ 刷新")
        return
    print("→ 刷新 submission/（tools/build_submission.py）…")
    res = subprocess.run([sys.executable, str(script)])
    if res.returncode != 0:
        sys.exit("❌ build_submission.py 失败，终止打包。")


def find_report_pdf() -> Path | None:
    """报告 PDF 允许改名（组长可能起「…-项目报告-Group01.pdf」这类更认得出的名字）。

    优先标准名 00-项目报告.pdf，否则取 submission/ 下第一个含「项目报告」的 PDF。
    """
    canon = SUBMISSION / "00-项目报告.pdf"
    if canon.exists():
        return canon
    for cand in sorted(SUBMISSION.glob("*项目报告*.pdf")):
        return cand
    return None


def main() -> int:
    refresh_submission()
    if not SUBMISSION.is_dir():
        sys.exit("❌ submission/ 不存在，请先运行 uv run python tools/build_submission.py")

    readme = SUBMISSION / "readme.txt"
    report_pdf = find_report_pdf()
    minutes = dir_files(SUBMISSION / "会议记录")
    personal = dir_files(SUBMISSION / "个人任务及感想")
    # 交付规则：有 pdf 就不收 docx（组长定稿，见 evidence/decisions/2026-09-27-提交包内容定案.md）
    minutes_pdf = [p for p in minutes if p.suffix.lower() == ".pdf"]
    personal_pdf = [p for p in personal if p.suffix.lower() == ".pdf"]
    videos = find_videos()
    cases = dir_files(SUBMISSION / "测试用例")
    binaries = find_binaries()
    source = git_tracked_files()

    # 防回归：非 ASCII 路径曾因 git 引号转义被静默漏掉，此处显式断言关键目录已纳入
    rel = [p.relative_to(ROOT).as_posix() for p in source]
    for need in ("deliverables/", "minutes/", "app/"):
        if not any(r.startswith(need) for r in rel):
            sys.exit(f"❌ 源程序快照缺少 {need}，打包中止（请检查 git_tracked_files）。")

    # 存在性校验：缺项写进「未闭环项」，不崩溃
    missing: list[str] = []
    if report_pdf is None:
        missing.append("项目报告 PDF（submission/00-项目报告.pdf 或任一含「项目报告」的 PDF）")
    if not readme.exists():
        missing.append("readme.txt（运行 tools/build_submission.py 从根目录同步）")
    if not minutes_pdf:
        missing.append("会议记录/ 为空（应为 5 组 pdf）")
    if not personal_pdf:
        missing.append("个人任务及感想/ 为空（应为 5 组 pdf）")
    if not videos:
        missing.append("演示视频（submission/演示视频/*.mp4）尚未就位")
    if not cases:
        missing.append("测试用例/ 为空（应为 12 个可导入 txt + 说明.txt）")
    if not binaries:
        missing.append("可执行程序/ 为空 —— CI 打包时由 release.yml 注入三端产物；本机自测打包无此项属正常")

    # 组装控制台清单（不再写进包：组长定的包内不含提交说明.txt）
    manifest = [
        "TopoSort 拓扑排序应用软件 — 第一组 提交材料",
        f"打包日期：{date.today().isoformat()}",
        "",
        "包内结构：",
        "  00-项目报告.pdf              项目报告 PDF（老师模板导出）",
        "  readme.txt                   运行环境/配置/如何运行",
        "  可执行程序/                  三端单文件产物（CI 打包时注入）",
        "  会议记录/                    5 次会议记录（仅 pdf）",
        "  个人任务及感想/               5 人个人任务及感想（仅 pdf）",
        "  测试用例/                    12 个可导入数据 + 说明.txt",
        "  演示视频/                    演示视频（≤50M）",
        "  源程序/                      整个项目源码快照（git 跟踪文件，含 app/、tools/、evidence/、readme.txt）",
        "",
        f"会议记录：{len(minutes_pdf)} 份  |  个人任务及感想：{len(personal_pdf)} 份  |  测试用例：{len(cases)} 个  |  "
        f"二进制：{len(binaries)} 个  |  视频：{len(videos)} 个",
    ]
    if missing:
        manifest += ["", "⚠️ 未闭环项（打包时缺失，请补齐后重跑）："] + [f"  - {m}" for m in missing]

    # 写 zip
    if ZIP_PATH.exists():
        ZIP_PATH.unlink()
    with zipfile.ZipFile(ZIP_PATH, "w", zipfile.ZIP_DEFLATED) as z:
        if report_pdf is not None:
            z.write(report_pdf, "group01/00-项目报告.pdf")
        if readme.exists():
            z.write(readme, "group01/readme.txt")
        for p in binaries:
            z.write(p, f"group01/可执行程序/{p.name}")
        for p in minutes_pdf:
            z.write(p, f"group01/会议记录/{p.name}")
        for p in personal_pdf:
            z.write(p, f"group01/个人任务及感想/{p.name}")
        for p in cases:
            z.write(p, f"group01/测试用例/{p.name}")
        for p in videos:
            z.write(p, f"group01/演示视频/{p.name}")
        # 源程序快照
        for p in source:
            z.write(p, f"group01/源程序/{p.relative_to(ROOT).as_posix()}")

    size = ZIP_PATH.stat().st_size
    print("\n".join(manifest))
    print("\n" + "=" * 48)
    print(f"✅ 已生成 {ZIP_PATH.name}  体积 {size:,} B ({size / 1024 / 1024:.1f} MB)")
    print(
        f"   源程序文件 {len(source)} 个 · 会议记录 {len(minutes_pdf)} 份 · "
        f"个人任务及感想 {len(personal_pdf)} 份 · 测试用例 {len(cases)} 个 · "
        f"二进制 {len(binaries)} 个 · 视频 {len(videos)} 个"
    )
    if missing:
        print("⚠️ 仍有未闭环项：\n   - " + "\n   - ".join(missing))
    return 0


if __name__ == "__main__":
    sys.exit(main())
