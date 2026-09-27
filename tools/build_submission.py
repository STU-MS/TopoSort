#!/usr/bin/env python3
"""搭建 / 刷新唯一提交材料目录 submission/。

设计原则：
  * `deliverables/` 保持原始样子（素材/过程文档），本脚本**只读不写**。
  * `submission/` 是唯一正式提交材料目录，可幂等重跑（重复运行结果一致）。
  * 报告 docx（T4 产出）与报告 PDF（组长导出）**不归本脚本管**，不会被创建或覆盖。

固定结构：
    submission/
    ├── readme.txt                    ← 从仓库根 readme.txt 同步
    ├── 00-项目报告.docx               ← 报告构建侧产出，本脚本不动
    ├── 高级算法实践-项目报告-Group01.pdf ← 组长导出，本脚本不动（允许含「项目报告」的改名）
    ├── 会议记录/                      ← deliverables/docx|pdf/2026-*.{docx,pdf}
    ├── 个人任务及感想/                 ← deliverables/docx|pdf/0?-*-个人任务及感想.{docx,pdf}
    ├── 可执行程序/                    ← CI 由 release.yml 注入三端产物，本脚本不动（.gitkeep 占位）
    ├── 测试用例/                      ← 12 个可导入 txt + 说明.txt，入 git，本脚本不动
    └── 演示视频/                      ← mp4 走 git LFS，本脚本仅保 .gitkeep 占位

用法：
    uv run python tools/build_submission.py
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DELIVERABLES = ROOT / "deliverables"
DOCX_DIR = DELIVERABLES / "docx"
PDF_DIR = DELIVERABLES / "pdf"
SUBMISSION = ROOT / "submission"

MINUTES_DIR = SUBMISSION / "会议记录"
PERSONAL_DIR = SUBMISSION / "个人任务及感想"
VIDEO_DIR = SUBMISSION / "演示视频"

# 独立管理（由 T4 / 组长产出），本脚本绝不创建或覆盖
PROTECTED = ("00-项目报告.docx", "00-项目报告.pdf")


def protected_path(name: str) -> Path | None:
    """报告 docx/pdf 允许改名（组长起的「高级算法实践-项目报告-Group01.pdf」也认）。"""
    p = SUBMISSION / name
    if p.exists():
        return p
    if name.endswith(".pdf"):
        for cand in sorted(SUBMISSION.glob("*项目报告*.pdf")):
            return cand
    return None


def is_minutes(name: str) -> bool:
    return name.startswith("2026-") and name.endswith((".docx", ".pdf"))


def is_personal(name: str) -> bool:
    return name.endswith("-个人任务及感想.docx") or name.endswith("-个人任务及感想.pdf")


def copy_group(src_dir: Path, dst_dir: Path, predicate) -> list[str]:
    """把 src_dir 下满足 predicate 的文件复制到 dst_dir，返回复制出的文件名。"""
    dst_dir.mkdir(parents=True, exist_ok=True)
    copied: list[str] = []
    if not src_dir.is_dir():
        return copied
    for src in sorted(src_dir.iterdir()):
        if not src.is_file() or not predicate(src.name):
            continue
        shutil.copy2(src, dst_dir / src.name)
        copied.append(src.name)
    return copied


def sync_readme() -> bool:
    src = ROOT / "readme.txt"
    if not src.exists():
        print("⚠️  根目录 readme.txt 缺失，跳过同步")
        return False
    shutil.copy2(src, SUBMISSION / "readme.txt")
    return True


def main() -> int:
    # 安全阀：submission/ 必须位于仓库内
    if SUBMISSION.parent != ROOT:
        sys.exit("❌ submission 路径异常，拒绝执行。")

    (SUBMISSION / ".gitkeep").parent.mkdir(parents=True, exist_ok=True)
    SUBMISSION.mkdir(exist_ok=True)

    readme_ok = sync_readme()

    minutes_docx = copy_group(DOCX_DIR, MINUTES_DIR, is_minutes)
    minutes_pdf = copy_group(PDF_DIR, MINUTES_DIR, is_minutes)
    personal_docx = copy_group(DOCX_DIR, PERSONAL_DIR, is_personal)
    personal_pdf = copy_group(PDF_DIR, PERSONAL_DIR, is_personal)

    # 演示视频目录：占位但不入库（.gitignore 已忽略其内容）
    VIDEO_DIR.mkdir(parents=True, exist_ok=True)
    (VIDEO_DIR / ".gitkeep").touch()

    print("✅ submission/ 已刷新")
    print(f"   readme.txt                : {'已同步' if readme_ok else '缺失'}")
    print(f"   会议记录/                 : docx {len(minutes_docx)} + pdf {len(minutes_pdf)}")
    print(f"   个人任务及感想/            : docx {len(personal_docx)} + pdf {len(personal_pdf)}")
    print(f"   演示视频/                 : 占位目录（视频不入 git）")

    # 报告由其他环节产出，这里只提示，不创建
    for name in PROTECTED:
        found = protected_path(name)
        mark = f"已存在：{found.name}" if found else "待产出（本脚本不动）"
        print(f"   {name:<24}: {mark}")

    # docx / pdf 应成对出现，缺对时告警（不视为错误）
    docx_names = {n[:-5] for n in minutes_docx + personal_docx}
    pdf_names = {n[:-4] for n in minutes_pdf + personal_pdf}
    only_docx = sorted(docx_names - pdf_names)
    only_pdf = sorted(pdf_names - docx_names)
    if only_docx:
        print("⚠️  仅有 docx 无 PDF：" + "、".join(only_docx))
    if only_pdf:
        print("⚠️  仅有 PDF 无 docx：" + "、".join(only_pdf))
    return 0


if __name__ == "__main__":
    sys.exit(main())
