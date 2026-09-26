#!/usr/bin/env python3
"""把 report/diagrams/*.mmd（mermaid 图源）渲成 PNG，存进 evidence/screenshots/。

用法（唯一姿势）：

    uv run python tools/gen_diagrams.py              # 渲染全部图源
    uv run python tools/gen_diagrams.py --only 四层   # 只渲名字含「四层」的图

为什么用 Chrome headless + 本地 mermaid.js，而不是在仓库里装 mermaid-cli：
  - 零新增仓库依赖：mermaid.min.js 首次运行从 CDN 下载到 .cache/（已 gitignore），
    校验 SHA256 后才使用，保证任何人任何时间都能重现同一份渲染结果。
  - Chrome headless 三端都有现成安装，不污染 uv 依赖（AGENTS.md 红线：依赖只从 pyproject 走）。

渲染流程（每张图）：
  1. 生成临时 HTML：<pre class="mermaid">图源</pre> + 本地 mermaid.min.js
     + mermaid.initialize({startOnLoad:true, theme:'neutral', flowchart:{useMaxWidth:false}})
  2. Chrome --headless=new --dump-dom 渲染一次，从 DOM 里读 mermaid 生成的 SVG
     的 width/height，据此算出**恰好包住内容**的窗口尺寸（含 padding），
     这样既不会截断文字，也不会留大片空白导致 PNG 过小。
  3. Chrome --headless=new --screenshot=... 按该尺寸截图。
  4. 扫像素算墨迹占画布宽的比例，低于 INK_MIN_WIDTH_RATIO 直接报错（见该常量的注释）。

幂等：mermaid 渲染 + Chrome 截图都是确定性的，重跑覆盖同名文件，字节数一致。
退出码非 0 = 至少一张图渲染失败。
"""
from __future__ import annotations

import argparse
import hashlib
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # tools/ 同级模块
import png_ink  # noqa: E402  纯标准库的 PNG 墨迹扫描，用来守门「图会不会小到看不清」

# ---------------------------------------------------------------------------
# mermaid 版本与期望 SHA256（可复现性凭据；换版本时必须同步改这里）
#   来源：https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.min.js
#   解析出的实际版本：11.17.2（jsdelivr 的 @11 重定向到当前最新的 11.x）
#   SHA256 = 581ed7d74bd9048d0e3a91363927d72ef22942d7722546b27f7cc29e35390eb8
# ---------------------------------------------------------------------------
MERMAID_URL = "https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.min.js"
MERMAID_VERSION = "11.17.2"
MERMAID_SHA256 = "581ed7d74bd9048d0e3a91363927d72ef22942d7722546b27f7cc29e35390eb8"

ROOT = Path(__file__).resolve().parent.parent
DIAGRAM_DIR = ROOT / "report" / "diagrams"
OUT_DIR = ROOT / "evidence" / "screenshots"
CACHE_DIR = ROOT / ".cache"
MERMAID_JS = CACHE_DIR / "mermaid.min.js"

CHROME_CANDIDATES = [
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/usr/bin/google-chrome",
    "/usr/bin/google-chrome-stable",
    "/usr/bin/chromium",
    "/usr/bin/chromium-browser",
    "chrome",
]
MIN_BYTES = 8 * 1024   # 结构图是线稿（大片白底、熵低），20KB 门槛会把正常图误杀
                       # （实测 4 个框的四层架构图只有 2.4KB）。这里用 8KB 做“非空图”下限，
                       # 真正的可读性由墨迹覆盖率 + H/W 上限机械把关。
PADDING = 24          # SVG 四周留白，避免文字贴边被裁
MIN_CANVAS_CSS = 260  # 画布最小 CSS 高/宽：过扁的图（如 4 个框的一行流程图）
                      # 实测量出的高度偏小，截图会把节点压成细条（字全丢），故给下限
MAX_SIDE = 6000       # Chrome 窗口上限保护
VIRTUAL_TIME_BUDGET = 8000

# 墨迹宽度占画布宽度的下限。为什么需要：mermaid 的 stateDiagram 只给 svg
# width="100%"、不给 height，按 CSS 规范「缺省尺寸的替换元素取默认对象尺寸 300×150」，
# Chrome 会把 svg 渲染成 300 CSS px 宽（内容缩到 viewBox 的 29%），而截图窗口是按
# viewBox 开的 → 画布尺寸对、内容只占左上角 27%，插到 16cm 宽时图内字号仅约 4.6pt。
# 这种「画布对、内容小」的缺陷只看尺寸查不出来，必须扫像素；实测正常流程图 93~94%。
INK_MIN_WIDTH_RATIO = 0.70
# 报告里结构图统一按 16cm 宽摆放（report/content.py 的 FIGURES），用折算纸上字号做参考
REF_DIAGRAM_WIDTH_CM = 16.0
PT_PER_CM = 28.3465
# 折算出纸上字号低于它就提醒（不报错：真正常见的密集大图也会落在 7pt 附近）
SOFT_PT_WARN = 7.0

# 图源文件名 → (输出 PNG 名, 字号 px, H/W 上限)
# 字号用于在保持横向的前提下把过扁/过小的图“放大”一点（mermaid 按 font-size 估算节点宽度），
# 使 PNG 既清晰又远离 check_docs.py 的 20KB 门槛。H/W 上限 = 任务 T8 的硬指标（≤1.2）。
DATE_TAG = "20260926"
SPEC: list[tuple[str, str, int, float]] = [
    ("fig2-1-功能结构.mmd", "架构图-功能结构", 16, 1.2),
    ("fig3-1-四层架构.mmd", "架构图-分层", 16, 1.2),
    ("fig3-2-处理流程.mmd", "架构图-处理流程", 16, 1.2),
    ("fig3-3-节点状态机.mmd", "架构图-节点状态机", 22, 1.2),
    ("fig3-4-全序枚举分支.mmd", "架构图-枚举分支", 16, 1.2),
]
DIAGRAMS: list[tuple[str, str]] = [(mmd, stem) for mmd, stem, _, _ in SPEC]
FONT_PX = {mmd: px for mmd, _, px, _ in SPEC}
MAX_HW = {mmd: hw for mmd, _, _, hw in SPEC}


def log(msg: str) -> None:
    print(msg, flush=True)


def find_chrome() -> str:
    for cand in CHROME_CANDIDATES:
        if cand == "chrome":
            found = shutil.which(cand)
            if found:
                return found
        elif Path(cand).exists():
            return cand
    raise SystemExit(
        "❌ 找不到 Google Chrome，请安装后重试（本脚本只用本机 Chrome headless 渲染，不装 mermaid-cli）"
    )


def ensure_mermaid() -> Path:
    """确保 .cache/mermaid.min.js 存在且 SHA256 匹配；不匹配则报错（不静默用坏文件）。"""
    if MERMAID_JS.exists():
        digest = hashlib.sha256(MERMAID_JS.read_bytes()).hexdigest()
        if digest == MERMAID_SHA256:
            log(f"✅ 复用缓存 {MERMAID_JS.relative_to(ROOT)}（mermaid {MERMAID_VERSION}）")
            return MERMAID_JS
        log(f"⚠️  缓存 SHA256 不匹配（{digest[:12]}…），重新下载")

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    log(f"⬇️  下载 mermaid {MERMAID_VERSION}：{MERMAID_URL}")
    subprocess.run(["curl", "-sSL", "-o", str(MERMAID_JS), MERMAID_URL], check=True)
    digest = hashlib.sha256(MERMAID_JS.read_bytes()).hexdigest()
    if digest != MERMAID_SHA256:
        raise SystemExit(
            "❌ mermaid.min.js 校验失败：\n"
            f"   期望 {MERMAID_SHA256}\n   实际 {digest}\n"
            f"   CDN 上的 @11 版本可能已更新；请核对版本号与哈希后更新脚本顶部常量。"
        )
    log("✅ SHA256 校验通过")
    return MERMAID_JS


def build_html(source: str, mermaid_js: Path, font_px: int = 16) -> str:
    return f"""<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="utf-8">
<style>
  html, body {{ margin: 0; padding: 0; background: #ffffff; }}
  #wrap {{ display: inline-block; padding: {PADDING}px; background: #ffffff; }}
  .mermaid {{ font-family: "Helvetica Neue", "PingFang SC", "Hiragino Sans GB",
              "Microsoft YaHei", sans-serif; font-size: {font_px}px; }}
</style>
</head>
<body>
<div id="wrap"><pre class="mermaid">{source}</pre></div>
<script src="file://{mermaid_js}"></script>
<script>
  mermaid.initialize({{ startOnLoad: true, theme: 'neutral',
                        flowchart: {{ useMaxWidth: false, htmlLabels: true }},
                        themeVariables: {{ fontSize: '{font_px}px' }} }});
</script>
<script>
  // mermaid 部分图类型（stateDiagram）生成的 <svg> 只给 width="100%"、不给 height，
  // 于是 Chrome 按 CSS 的「默认对象尺寸 300×150」渲染，内容被缩到 viewBox 的 ~29%，
  // 而截图窗口是按 viewBox 开的 → 画布尺寸对、内容只占一角。渲染完成后把 viewBox 尺寸
  // 回填成显式 width/height，让 svg 盒子 = 内容尺寸（1:1）；已有显式尺寸的图不受影响。
  (function () {{
    function normalizeSvg() {{
      var svg = document.querySelector('svg');
      if (!svg) return false;
      var vb = svg.viewBox && svg.viewBox.baseVal;
      if (!vb || !vb.width || !vb.height) return false;
      var w = svg.getAttribute('width') || '';
      var h = svg.getAttribute('height') || '';
      if (!/^[0-9.]+$/.test(w) || !/^[0-9.]+$/.test(h)) {{
        svg.setAttribute('width', vb.width);
        svg.setAttribute('height', vb.height);
        svg.style.maxWidth = vb.width + 'px';
      }}
      var r = svg.getBoundingClientRect();
      document.documentElement.setAttribute('data-svg-box', JSON.stringify(
        [r.width.toFixed(1), r.height.toFixed(1),
         vb.width.toFixed(1), vb.height.toFixed(1)]));
      return true;
    }}
    var tick = setInterval(function () {{ if (normalizeSvg()) clearInterval(tick); }}, 20);
  }})();
</script>
</body>
</html>
"""


CHROME_STDERR = subprocess.DEVNULL


def _kill(proc: subprocess.Popen) -> None:
    try:
        proc.kill()
    except OSError:
        pass
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        pass


def _spawn(chrome: str, html: Path, *extra: str) -> subprocess.Popen:
    cmd = [
        chrome,
        "--headless=new",
        "--no-sandbox",
        "--hide-scrollbars",
        "--disable-gpu",
        "--force-device-scale-factor=2",   # 2x 分辨率，PNG 更清晰
        f"--virtual-time-budget={VIRTUAL_TIME_BUDGET}",
        f"--user-data-dir={tempfile.mkdtemp(prefix='chrome-gen-diagrams-')}",
        *extra,
        html.as_uri(),
    ]
    return subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=CHROME_STDERR, text=True)


def dump_dom(chrome: str, html: Path, timeout: int = 45) -> str:
    """跑 Chrome --dump-dom 并返回渲染后的 HTML。

    注意：本机 Chrome 153 在 --dump-dom 输出完之后**不会自动退出**（已知行为），
    因此这里不依赖子进程退出，而是在读到 `</html>` 后立即 kill，避免每张图白等超时。
    """
    proc = _spawn(chrome, html, "--dump-dom")
    assert proc.stdout is not None
    chunks: list[str] = []
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        line = proc.stdout.readline()
        if line:
            chunks.append(line)
            if "</html>" in line:
                break
        elif proc.poll() is not None:
            break
    _kill(proc)
    return "".join(chunks)


def screenshot(chrome: str, html: Path, target: Path, w: int, h: int,
               timeout: int = 60) -> None:
    """跑 Chrome --screenshot 并等 PNG 落地（同样不依赖子进程自行退出）。"""
    target.unlink(missing_ok=True)
    proc = _spawn(chrome, html, f"--screenshot={target}", f"--window-size={w},{h}")
    deadline = time.monotonic() + timeout
    last_size = -1
    stable = 0
    try:
        while time.monotonic() < deadline:
            time.sleep(0.4)
            if target.exists():
                size = target.stat().st_size
                if size > 0 and size == last_size:
                    stable += 1
                    if stable >= 2:  # 连续两次不变 = 写完了
                        break
                else:
                    stable = 0
                last_size = size
            elif proc.poll() is not None:
                break
    finally:
        _kill(proc)


SVG_SIZE = re.compile(r'<svg[^>]*?\bwidth="([\d.]+)"[^>]*?\bheight="([\d.]+)"')
SVG_SIZE_REV = re.compile(r'<svg[^>]*?\bheight="([\d.]+)"[^>]*?\bwidth="([\d.]+)"')
# stateDiagram 等图类型不输出写死的 width/height，只给 width="100%" + viewBox（外加
# style="max-width: Wpx"）。此时以 viewBox 尺寸为准。
SVG_VIEWBOX = re.compile(r'<svg[^>]*?\bviewBox="0 0 ([\d.]+) ([\d.]+)"')


def measure(chrome: str, html: Path) -> tuple[int, int]:
    """渲染一次并读出 mermaid 生成 SVG 的实际尺寸，返回截图的 CSS 像素窗口尺寸。

    `--window-size` 用的是 CSS px；配合 `--force-device-scale-factor=2`，
    Chrome 会按 2x 输出 PNG，所以这里只加 CSS px 的 padding。
    """
    dom = dump_dom(chrome, html)
    m = SVG_SIZE.search(dom) or SVG_SIZE_REV.search(dom)
    if m:
        if "height" in m.group(0)[: m.group(0).find("width")]:
            h, w = m.group(1), m.group(2)
        else:
            w, h = m.group(1), m.group(2)
    else:
        vb = SVG_VIEWBOX.search(dom)
        if not vb:
            snippet = dom[:400].replace("\n", " ")
            raise RuntimeError(f"未在渲染后的 DOM 中找到 <svg> 尺寸信息；开头片段：{snippet}")
        w, h = vb.group(1), vb.group(2)
    return (
        min(MAX_SIDE, max(MIN_CANVAS_CSS, int(float(w)) + 2 * PADDING)),
        min(MAX_SIDE, max(MIN_CANVAS_CSS, int(float(h)) + 2 * PADDING)),
    )


def render_one(chrome: str, mmd: Path, stem: str, mermaid_js: Path,
               font_px: int = 16, max_hw: float = 1.2) -> Path:
    source = mmd.read_text(encoding="utf-8").strip()
    html_text = build_html(source, mermaid_js, font_px)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    target = OUT_DIR / f"{stem}-{DATE_TAG}-1.png"

    with tempfile.TemporaryDirectory(prefix="gen-diagrams-") as tmp:
        html = Path(tmp) / "diagram.html"
        html.write_text(html_text, encoding="utf-8")
        w, h = measure(chrome, html)
        log(f"   画布尺寸 {w}x{h} CSS px（2x DPR → {w * 2}x{h * 2} PNG）")
        screenshot(chrome, html, target, w, h)

    if not target.exists():
        raise RuntimeError(f"Chrome 未生成截图：{target}")
    size = target.stat().st_size
    if size < MIN_BYTES:
        raise RuntimeError(f"截图过小(<{MIN_BYTES // 1024}KB)：{target} ({size}B)，可能文字被截断或渲染失败")
    hw = h / w if w else float("inf")
    if hw > max_hw:
        raise RuntimeError(
            f"纵横比不达标：H/W={hw:.3f} > {max_hw}（{w}x{h}），"
            f"14cm 宽时高 {14 * hw:.1f}cm；请把图源改成更横向的布局"
        )

    cover_w, cover_h, ink = png_ink.ink_coverage(target)
    ink_w, ink_h = ink[2] - ink[0] + 1, ink[3] - ink[1] + 1
    pt_on_page = font_px * 2 * (REF_DIAGRAM_WIDTH_CM * PT_PER_CM) / (w * 2)
    line = (f"✅ {target.relative_to(ROOT)}  {w}x{h}px  H/W={hw:.3f}  {size}B"
            f"  墨迹占宽 {cover_w:.0%} 高 {cover_h:.0%}"
            f"  摆 {REF_DIAGRAM_WIDTH_CM:g}cm 宽时图上字号≈{pt_on_page:.1f}pt")
    if cover_w < INK_MIN_WIDTH_RATIO:
        raise RuntimeError(
            f"墨迹只占画布宽 {cover_w:.0%}（下限 {INK_MIN_WIDTH_RATIO:.0%}）：{target}\n"
            f"   画布 {w}x{h} CSS，墨迹 {ink_w}x{ink_h}px（留白 左{ink[0]} 右{w - 1 - ink[2]}）\n"
            "   画布对但内容缩在一角，插进文档后图内文字会被整体缩小到看不清。\n"
            "   多半是 mermaid 生成的 svg 没有显式 width/height，被按「默认对象尺寸"
            "300×150」缩小渲染了；先确认 build_html 里的 svg 归一化脚本是否生效。"
        )
    log(line)
    if pt_on_page < SOFT_PT_WARN:
        log(f"   ⚠️  图上字号 ≈{pt_on_page:.1f}pt 偏小（<{SOFT_PT_WARN:g}pt），"
            "建议把图源改稀一点或缩小摆放宽度")
    return target


def main() -> int:
    parser = argparse.ArgumentParser(description="mermaid 图源 → PNG（Chrome headless）")
    parser.add_argument("--only", help="只渲染名字含该子串的图（匹配 .mmd 文件名或输出名）")
    parser.add_argument("--list", action="store_true", help="列出全部图源后退出")
    args = parser.parse_args()

    if args.list:
        for mmd, stem in DIAGRAMS:
            log(f"{mmd}  →  {stem}-{DATE_TAG}-1.png")
        return 0

    chrome = find_chrome()
    log(f"Chrome: {chrome}")

    selected = [
        (mmd, stem)
        for mmd, stem in DIAGRAMS
        if not args.only or args.only in mmd or args.only in stem
    ]
    if not selected:
        log(f"❌ 没有图源匹配 --only {args.only!r}")
        return 1
    missing = [mmd for mmd, _ in selected if not (DIAGRAM_DIR / mmd).exists()]
    if missing:
        log(f"❌ 缺少图源：{missing}")
        return 1

    mermaid_js = ensure_mermaid()

    failures: list[str] = []
    for mmd_name, stem in selected:
        mmd = DIAGRAM_DIR / mmd_name
        log(f"▶ {mmd_name}")
        try:
            render_one(chrome, mmd, stem, mermaid_js,
                       FONT_PX[mmd_name], MAX_HW[mmd_name])
        except Exception as exc:  # noqa: BLE001 - 逐张报告，最后统一非 0 退出
            log(f"❌ {mmd_name} 渲染失败：{exc}")
            failures.append(mmd_name)

    log("---")
    if failures:
        log(f"❌ {len(failures)} 张图渲染失败：{', '.join(failures)}")
        return 1
    log(f"✅ {len(selected)} 张图全部渲染成功 → {OUT_DIR.relative_to(ROOT)}/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
