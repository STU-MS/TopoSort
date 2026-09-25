#!/usr/bin/env python3
"""统一整理交付报告：

  ① 清除 emoji（✅❌🔄★⚠ 等）→ 纯文字（按上下文语义替换）；
  ② 给所有引用文件附 GitHub 可访问链接（“同名链接”：外观不变，只是可点击）。

设计要点：
- 图片：`![alt](相对路径)` → `[![alt](相对路径)](GitHub绝对地址)`
  —— 图片 src 保持相对，保证离线转 PDF 也能出图；点击才走 GitHub。
- 普通链接：目标改为 GitHub 绝对地址，链接文字不变。
- 行内 code 路径：`` `evidence/.../x.in` `` → `` [`……`](GitHub绝对地址) ``，等宽外观不变。
- 无法唯一确定的引用（同名多义、占位片段）保持原样，不误改。

用法：
    uv run python tools/linkify_docs.py --dry-run   # 只统计与预览，不写盘
    uv run python tools/linkify_docs.py --write     # 实际写盘
"""
from __future__ import annotations

import argparse
import re
import sys
import urllib.parse
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REPO = "STU-MS/TopoSort"
BRANCH = "master"
BASE = f"https://github.com/{REPO}/blob/{BRANCH}/"

TARGETS = (
    sorted((ROOT / "deliverables").glob("*.md"))
    + sorted((ROOT / "deliverables" / "personal").glob("*.md"))
)

# 仅清 emoji；以下符号视为排版字符保留：→ ↓ ① ┌ ─ │ ├ └ 等
EMOJI_RE = re.compile(r"[✅❌🔄★⚠]\uFE0F?\s?")
# 表头为“结果/是否接受/动态演化能力…”时，单元格里的裸图标换成对应词
BARE_CELL = {
    "deliverables/00-项目报告.md": {"✅": "通过"},
    "deliverables/05-测试报告.md": {"✅": "通过"},
    "deliverables/06-用户手册.md": {"✅": "接受", "❌": "不接受"},
    "deliverables/01-可行性研究报告.md": {"✅": "支持", "❌": "不支持"},
}

IMG_RE = re.compile(r"!\[([^\]]*)\]\(([^)]+)\)")
LINK_RE = re.compile(r"(?<!!)\[([^\]]*)\]\(([^)]*)\)")
CODE_RE = re.compile(r"`([^`\n]+)`(?!\])")
FENCE_RE = re.compile(r"^```")


def build_index() -> tuple[dict[str, list[str]], list[str]]:
    skip = {".git", ".venv", "__pycache__", "dist", "build", "pdf", "docx"}
    by_name: dict[str, list[str]] = {}
    all_rel: list[str] = []
    for p in ROOT.rglob("*"):
        if not p.is_file():
            continue
        if any(part in skip for part in p.parts):
            continue
        rel = p.relative_to(ROOT).as_posix()
        all_rel.append(rel)
        by_name.setdefault(p.name, []).append(rel)
    return by_name, all_rel


BY_NAME, ALL_REL = build_index()


def resolve(target: str, md: Path) -> str | None:
    """把文档里的引用解析成“仓库相对路径”；解析不出返回 None。"""
    t = target.strip().strip("`")
    if not t or t.startswith(("http://", "https://", "mailto:", "#")):
        return None
    t = t.split("#")[0].strip()
    for cand in (ROOT / t, md.parent / t):
        if cand.is_file():
            return cand.resolve().relative_to(ROOT).as_posix()
    # basename / 后缀 唯一匹配
    hits = BY_NAME.get(Path(t).name, [])
    if len(set(hits)) == 1:
        return hits[0]
    suf = [r for r in ALL_REL if r.endswith("/" + t)]
    if len(set(suf)) == 1:
        return suf[0]
    return None


def abs_url(rel: str) -> str:
    return BASE + urllib.parse.quote(rel, safe="/")


def clean_emoji(text: str, rel: str) -> str:
    for glyph, word in BARE_CELL.get(rel, {}).items():
        text = text.replace(f"| {glyph} |", f"| {word} |")
    return EMOJI_RE.sub("", text)


def linkify(text: str, md: Path) -> str:
    # 注意顺序：先处理普通链接，再处理图片。否则图片被包成 [![alt](src)](abs) 后，
    # 外层 [ ] 会被链接正则当成“label=![alt”再吃掉，导致 src 也被绝对化（破坏离线出图）。

    # 1) 普通链接：文字不变，目标改绝对地址（含修复空目标 []() ）
    def link(m: re.Match) -> str:
        label, tgt = m.group(1), m.group(2)
        if tgt.startswith(("http://", "https://", "mailto:", "#")):
            return m.group(0)
        rel = resolve(tgt or label, md)
        return f"[{label}]({abs_url(rel)})" if rel else m.group(0)

    text = LINK_RE.sub(link, text)

    # 2) 图片：外层套 GitHub 链接（src 保持相对，保证离线转 PDF 能出图）
    def img(m: re.Match) -> str:
        alt, src = m.group(1), m.group(2)
        if src.startswith(("http://", "https://")):
            return m.group(0)
        rel = resolve(src, md)
        return f"[![{alt}]({src})]({abs_url(rel)})" if rel else m.group(0)

    text = IMG_RE.sub(img, text)

    # 3) 行内 code 路径：等宽不变，可点击（跳过代码围栏块）
    out: list[str] = []
    in_fence = False
    for line in text.splitlines(keepends=True):
        if FENCE_RE.match(line):
            in_fence = not in_fence
            out.append(line)
            continue
        if not in_fence:
            def code(m: re.Match) -> str:
                raw = m.group(1)
                rel = resolve(raw, md)
                if not rel or " " in raw:
                    return m.group(0)
                return f"[`{raw}`]({abs_url(rel)})"

            line = CODE_RE.sub(code, line)
        out.append(line)
    return "".join(out)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true", help="写盘")
    ap.add_argument("--dry-run", action="store_true", help="只预览不写盘（默认）")
    args = ap.parse_args()
    write = args.write and not args.dry_run

    total_emoji = total_img = total_link = total_code = 0
    for md in TARGETS:
        rel = md.relative_to(ROOT).as_posix()
        src = md.read_text(encoding="utf-8")
        n_emoji = len(EMOJI_RE.findall(src))
        step1 = clean_emoji(src, rel)
        step2 = linkify(step1, md)
        n_img = len(IMG_RE.findall(step1))
        # 统计链接化数量
        total_emoji += n_emoji
        total_img += n_img
        total_link += sum(
            1 for _ in LINK_RE.finditer(step1)
            if resolve(_.group(2) or _.group(1), md)
        )
        total_code += sum(
            1 for _ in CODE_RE.finditer(step1)
            if resolve(_.group(1), md) and " " not in _.group(1)
        )
        if step2 != src:
            if write:
                md.write_text(step2, encoding="utf-8")
            print(f"{'写入' if write else '预览'} {rel}: emoji {n_emoji} 处，图片 {n_img} 处")

    # 残留检查
    leftover = 0
    for md in TARGETS:
        if EMOJI_RE.search(md.read_text(encoding="utf-8")):
            leftover += 1
    print("\n=== 汇总 ===")
    print(f"emoji 清除：{total_emoji} 处")
    print(f"图片转可点击：约 {total_img} 处")
    print(f"普通链接绝对化：约 {total_link} 处")
    print(f"行内路径链接化：约 {total_code} 处")
    print(f"emoji 残留文件：{leftover} 个（应为 0）")
    if not write:
        print("\n（dry-run：未写盘；确认无误后加 --write）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
