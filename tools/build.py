#!/usr/bin/env python3
"""T7 打包入口（Issue #8）：三端一致的 PyInstaller 单文件封装。

用法（一律走 uv，见 AGENTS.md 第三节）：:

    uv run python tools/build.py                 # 本机单文件产物（默认开体积优化）
    uv run python tools/build.py --smoke         # 构建后追加「空目录启动冒烟」
    uv run python tools/build.py --no-optimize   # 关掉 excludes（做体积对照用）
    uv run python tools/build.py --console       # 保留控制台（排查启动崩溃用）

三端差异全部在本脚本内部消化，外部调用方式完全一致：

    Windows  产物 dist/TopoSort.exe   传 --windowed（不弹控制台窗口）
    macOS    产物 dist/TopoSort.app   onedir + --windowed（产出真 .app），
                                      再用 ditto 打成可分发 zip（--no-zip 可关）
    Linux    产物 dist/TopoSort       不传 --windowed（*NIX 上该参数会被忽略，传了也无害）

平台相关的默认值（本脚本有意保守化，因为 CI 之外的平台本地验不了）：

    --strip   默认**仅 Linux 开启**。Windows 官方不推荐；macOS 上与 ad-hoc 代码签名
              存在冲突风险（PyInstaller 先 strip 再签名，剥过的二进制可能过不了签名校验），
              故一律不在非 Linux 平台默认开启。
    --zip     默认**仅 macOS 开启**（.app 是目录，需打包才能作为 Release 资产分发）。
    --mode    默认 macOS 用 onedir、其余用 onefile。PyInstaller 6.22 对 macOS 的
              `--onefile --windowed` 已发 DEPRECATION（osx.py:33 WINDOWED_ONEFILE_DEPRCATION：
              “a .app bundle can not be a single file” 且与 macOS 安全模型冲突，v7.0 起直接报错），
              故 macOS 必须走 onedir。

设计约束（AGENTS.md 红线）：
    * 不引入新依赖：只用标准库 + dev 组已有的 pyinstaller。
    * 跨平台：路径一律 pathlib，不硬编码分隔符；不调用平台专属 API。
    * 工具链已定案为 PyInstaller（evidence/decisions/2026-09-15-技术栈定案.md），
      本脚本不提供换打包器的开关。
"""

from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
ENTRY = REPO_ROOT / "app" / "main.py"
DEFAULT_NAME = "TopoSort"

# --------------------------------------------------------------------------
# 体积优化清单
#
# 依据：app/ 实际只 import 了 PySide6.QtCore / QtGui / QtWidgets 三个模块
# （`grep -rh "^from PySide6" app/` 可复核）。PyInstaller 6 的 PySide6 hook 是
# 「按被 import 的模块」收集 Qt 库与插件的（PyInstaller/utils/hooks/qt/__init__.py
# 的 add_qt6_dependencies），因此未 import 的 Qt 模块本就不会被收进来；这里显式
# 排除是为了兜住 hiddenimports / 依赖字典可能牵进来的旁支，并让意图可复核。
#
# 收益以实测为准，见 evidence/decisions/2026-09-21-打包发布方案.md。
#
# 【实测结论 2026-09-21 · Linux x86_64】这份 excludes 清单的体积收益为 0：
#   开排除 72,258,160 字节 vs 关排除 72,257,448 字节（差 +712 B，属构建噪声）。
# 原因：PyInstaller 6 的 PySide6 hook 按「被 import 的模块」收集 Qt 库，未 import 的
# Qt 模块本来就不会进包；而真正的大头（libicudata 30.6MB、libpython 20.8MB、
# libQt6Quick+Qml 15.5MB、libgtk-3 系 15MB）是**插件经二进制依赖分析**拖进来的，
# --exclude-module 管不到。保留本清单的用途：意图可复核 + 兜住日后 hook 行为变化，
# 不是当作体积杠杆。真正的杠杆见 --strip 与决策文档。
# --------------------------------------------------------------------------
QT_EXCLUDES = [
    # 3D 场景图
    "PySide6.Qt3DAnimation",
    "PySide6.Qt3DCore",
    "PySide6.Qt3DExtras",
    "PySide6.Qt3DInput",
    "PySide6.Qt3DLogic",
    "PySide6.Qt3DRender",
    # QML / Quick 全家桶
    "PySide6.QtQml",
    "PySide6.QtQuick",
    "PySide6.QtQuick3D",
    "PySide6.QtQuickControls2",
    "PySide6.QtQuickTest",
    "PySide6.QtQuickWidgets",
    # 浏览器内核
    "PySide6.QtWebEngineCore",
    "PySide6.QtWebEngineQuick",
    "PySide6.QtWebEngineWidgets",
    "PySide6.QtWebView",
    "PySide6.QtWebChannel",
    "PySide6.QtWebSockets",
    # 多媒体
    "PySide6.QtMultimedia",
    "PySide6.QtMultimediaWidgets",
    "PySide6.QtSpatialAudio",
    "PySide6.QtTextToSpeech",
    # 图表与数据可视化
    "PySide6.QtCharts",
    "PySide6.QtDataVisualization",
    "PySide6.QtGraphs",
    "PySide6.QtGraphsWidgets",
    "PySide6.QtCanvasPainter",
    # 数据库 / 测试 / 设计器 / 帮助 / PDF
    "PySide6.QtSql",
    "PySide6.QtTest",
    "PySide6.QtDesigner",
    "PySide6.QtUiTools",
    "PySide6.QtHelp",
    "PySide6.QtPdf",
    "PySide6.QtPdfWidgets",
    # 设备与附加网络能力
    "PySide6.QtBluetooth",
    "PySide6.QtNfc",
    "PySide6.QtPositioning",
    "PySide6.QtLocation",
    "PySide6.QtSerialPort",
    "PySide6.QtSerialBus",
    "PySide6.QtSensors",
    "PySide6.QtRemoteObjects",
    "PySide6.QtScxml",
    "PySide6.QtStateMachine",
    "PySide6.QtHttpServer",
    "PySide6.QtNetworkAuth",
    # 打印 / SVG / XML：本应用只用 QImage 存 PNG，不需要这些格式后端
    "PySide6.QtPrintSupport",
    "PySide6.QtSvg",
    "PySide6.QtSvgWidgets",
    "PySide6.QtXml",
    # 未被 QGraphicsView 使用的 GL 控件包装
    "PySide6.QtOpenGLWidgets",
]

PY_EXCLUDES = [
    # 测试框架（dev 依赖，运行时不需要）
    "pytest",
    "_pytest",
    "pytestqt",
    # 构建/安装工具链
    "setuptools",
    "pkg_resources",
    "pip",
    "wheel",
    # 与本项目无关的科学计算/交互式栈（若环境里装了，别被 hook 牵进来）
    "numpy",
    "matplotlib",
    "IPython",
    "PIL",
    # 标准库里的 GUI/测试旁支
    "tkinter",
    "test",
]

# 运行时冒烟：出现这些字样即判失败（冻结应用最典型的几种崩法）
SMOKE_FAIL_MARKERS = [
    "Traceback (most recent call last)",
    "ModuleNotFoundError",
    "ImportError",
    "cannot open shared object file",
    "Fatal Python error",
    "could not load the Qt platform plugin",
    "qt.qpa.plugin",
]


def force_utf8_stdio() -> None:
    """把 stdout/stderr 切到 UTF-8。

    为什么需要：Windows 控制台默认不是 UTF-8（cp936 / cp1252），脚本一 print 中文就抛
    UnicodeEncodeError: 'charmap' codec can't encode —— CI 上表现为「打包步骤 10 秒就退出」，
    PyInstaller 根本没跑起来。这是本脚本在 Windows 上翻过的真坑。
    errors="replace" 保证任何环境下都不会因为「打印一句话」而崩。
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):  # 已被重定向/包装过的流，忽略
            pass


def human_mb(num_bytes: int) -> str:
    return f"{num_bytes / 1024 / 1024:.1f} MB"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def artifact_paths(dist: Path, name: str) -> list[Path]:
    """本平台上预期的产物路径（按优先级）。"""
    if sys.platform == "win32":
        return [dist / f"{name}.exe"]
    if sys.platform == "darwin":
        # --windowed 在 macOS 上触发 .app；onedir 与 onefile 两种模式在 macOS 上都会额外
        # 产出 .app（makespec.py:863-873），但只有 onedir 是官方推荐且未被弃用的组合。
        return [dist / f"{name}.app", dist / name]
    return [dist / name]


def find_artifact(dist: Path, name: str) -> Path | None:
    for candidate in artifact_paths(dist, name):
        if candidate.exists():
            return candidate
    return None


def launchable_binary(artifact: Path) -> Path:
    """把产物映射到「可直接执行的二进制」。

    macOS 的 .app 是目录，真正的可执行文件在 Contents/MacOS/ 下。
    """
    if artifact.is_dir() and artifact.suffix == ".app":
        inner = artifact / "Contents" / "MacOS" / artifact.stem
        return inner
    return artifact


def embedded_names(binary: Path, needles: list[bytes]) -> list[str]:
    """在产物字节流里找内嵌文件名（PyInstaller 归档的目录表是明文的）。

    这是对「Qt 平台插件是否真的被打进包」的静态佐证，与运行时冒烟互补。
    """
    found: list[str] = []
    remaining = {n: n.decode("utf-8", "replace") for n in needles}
    with binary.open("rb") as fh:
        overlap = b""
        while chunk := fh.read(4 * 1024 * 1024):
            window = overlap + chunk
            for needle in list(remaining):
                if needle in window:
                    found.append(remaining.pop(needle))
            overlap = window[-256:]
    return found


def resolve_mode(args: argparse.Namespace) -> str:
    """解析打包模式。

    macOS 必须用 onedir：PyInstaller 对 macOS 的 `--onefile --windowed` 已发 DEPRECATION
    （osx.py:33），理由是一个 .app 本来就不可能是单文件，且与 macOS 安全模型冲突，
    v7.0 起会直接报错。Linux/Windows 仍用 onefile（技术栈定案要求“单文件双击即跑”）。
    """
    if args.mode:
        return args.mode
    return "onedir" if sys.platform == "darwin" else "onefile"


def build(args: argparse.Namespace) -> tuple[Path, float]:
    dist = args.distpath
    work = args.workpath

    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        f"--{resolve_mode(args)}",
        # UPX 在 Windows 上会压坏 Qt6 插件（PyInstaller 4.3 起自动排除 Qt 插件），
        # 且在 *NIX 上本就不生效；直接关掉，换取「三端构建结果可复现」。
        "--noupx",
        "--name",
        args.name,
        "--distpath",
        str(dist),
        "--workpath",
        str(work),
        "--specpath",
        str(work),
        # 让 `app` 包从仓库根解析（与 pytest 的 pythonpath=["."] 同一口径）
        "--paths",
        str(REPO_ROOT),
    ]

    if args.optimize:
        for module in QT_EXCLUDES + PY_EXCLUDES:
            cmd += ["--exclude-module", module]

    # --strip：裁掉收集到的共享库的符号表。实测 libpython3.11.so.1.0 未 strip（20.8MB），
    # 是 Linux 上唯一有效且受支持的体积杠杆。
    # 只在 Linux 默认开启：Windows 官方文档标注不推荐；macOS 上 PyInstaller 会对收集到的
    # 二进制做 ad-hoc 签名，strip 与签名的先后顺序存在冲突风险，而本机无法验证 macOS，
    # 故不冒险。
    if args.strip:
        cmd.append("--strip")

    # Windows/macOS 出窗口应用；Linux 上 --windowed 被忽略，不传以免误导
    if sys.platform in ("win32", "darwin") and not args.console:
        cmd.append("--windowed")

    cmd.append(str(ENTRY))

    print("=" * 72)
    print(f"打包平台：{sys.platform} / Python {sys.version.split()[0]}")
    print(f"体积优化：{'开' if args.optimize else '关'} "
          f"（Qt 排除 {len(QT_EXCLUDES)} 项，Python 排除 {len(PY_EXCLUDES)} 项；"
          f"实测收益≈0，见脚本注释）")
    print(f"符号表   ：{'裁剪（--strip）' if args.strip else '保留'}")
    print(f"macOS打包：{'打 .app 分发包' if args.zip else '不打'}")
    print(f"模式     ：{resolve_mode(args)}")
    print("=" * 72)
    print("$ " + " ".join(cmd[:12]) + f" … ({len(cmd) - 12} 个参数略)")
    print()

    started = time.perf_counter()
    completed = subprocess.run(cmd, cwd=REPO_ROOT)
    elapsed = time.perf_counter() - started

    if completed.returncode != 0:
        raise SystemExit(f"❌ PyInstaller 构建失败（退出码 {completed.returncode}）")

    artifact = find_artifact(dist, args.name)
    if artifact is None:
        expected = "、".join(str(p) for p in artifact_paths(dist, args.name))
        raise SystemExit(f"❌ 构建返回 0 但找不到产物，预期之一：{expected}")
    return artifact, elapsed


def smoke(binary: Path, seconds: int, artifact: Path) -> bool:
    """空目录启动冒烟：不依赖系统 Python、不依赖仓库文件。

    判据（两条都满足才算过）：
      1) 进程在剥离 Python 相关变量的干净环境下启动后，至少存活 N 秒不退出
         （GUI 程序进事件循环本就不该自己退出；提前非 0 退出 = 启动即崩）；
      2) 这段时间内 stderr 没有出现 SMOKE_FAIL_MARKERS 里的任何字样。
    刻意不改 app/ 代码去加自检开关——交付物里不该埋自动退出的后门。
    """
    print()
    print("=" * 72)
    print(f"空目录启动冒烟：{binary.name}（offscreen，存活判据 {seconds}s）")
    print("=" * 72)

    # 白名单环境：不含 PYTHONPATH / PYTHONHOME / VIRTUAL_ENV / LD_LIBRARY_PATH，
    # 等价于 `env -i`，用来证明「空目录、无 Python 环境可运行」。
    env = {
        "PATH": os.environ.get("PATH", ""),
        "QT_QPA_PLATFORM": "offscreen",
        "LANG": "C.UTF-8",
    }
    if sys.platform == "win32":
        # Windows 上缺 SYSTEMROOT 会导致进程无法启动，属系统必需项而非 Python 环境
        for key in ("SYSTEMROOT", "WINDIR", "TEMP", "TMP", "PATHEXT"):
            if key in os.environ:
                env[key] = os.environ[key]

    with tempfile.TemporaryDirectory(prefix="toposort-smoke-") as tmp:
        tmpdir = Path(tmp)
        # 把产物拷进空目录：证明运行不依赖仓库里的任何文件。
        # 注意 macOS 的 .app 是**目录**，必须整棵树拷过去——onedir 的可执行文件靠
        # @loader_path 找 Contents/Frameworks，只拷裸二进制会因找不到库而误报失败。
        local_artifact = tmpdir / artifact.name
        if artifact.is_dir():
            shutil.copytree(artifact, local_artifact, symlinks=True)
            local = local_artifact / binary.relative_to(artifact)
        else:
            shutil.copy2(artifact, local_artifact)
            local_artifact.chmod(0o755)
            local = local_artifact
        env["HOME"] = str(tmpdir)

        popen_kwargs: dict = {
            "cwd": str(tmpdir),
            "env": env,
            "stdout": subprocess.PIPE,
            "stderr": subprocess.PIPE,
            "text": True,
            # 显式指定解码，不依赖系统 locale（Windows 上默认是 cp936/cp1252）
            "encoding": "utf-8",
            "errors": "replace",
        }
        if sys.platform == "win32":
            popen_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            popen_kwargs["start_new_session"] = True

        proc = subprocess.Popen([str(local)], **popen_kwargs)
        survived = False
        try:
            out, err = proc.communicate(timeout=seconds)
            early_exit = True
        except subprocess.TimeoutExpired:
            early_exit = False
            survived = True
            _terminate_tree(proc)
            try:
                out, err = proc.communicate(timeout=15)
            except subprocess.TimeoutExpired:
                proc.kill()
                out, err = proc.communicate()

    print(f"空目录：{tmpdir}")
    if survived:
        print(f"存活 {seconds}s：是（{seconds}s 后由冒烟脚本主动终止，未自行退出）")
    else:
        print(f"存活 {seconds}s：否（进程自行退出，退出码 {proc.returncode}）")
    if out.strip():
        print("--- stdout ---")
        print(out.strip()[:2000])
    if err.strip():
        print("--- stderr ---")
        print(err.strip()[:2000])

    problems: list[str] = []
    if not survived:
        problems.append(f"进程在 {seconds}s 内自行退出（退出码 {proc.returncode}），未进入稳定运行")
    for marker in SMOKE_FAIL_MARKERS:
        if marker in err:
            problems.append(f"stderr 命中失败标记：{marker}")

    if problems:
        print()
        for item in problems:
            print(f"❌ {item}")
        return False

    print()
    print("✅ 冒烟通过：干净环境下启动、进入事件循环、stderr 无异常")
    return True


def write_checksum(deliverable: Path) -> Path:
    """写 `<交付物>.sha256`（`sha256sum -c` 兼容格式）。

    为什么必须随产物一起发布、而不是写死在文档里：PyInstaller onefile 产物**不是字节
    可复现的**（本机两次同参数构建实测 71,363,616 与 71,363,600 字节，哈希不同；
    `SOURCE_DATE_EPOCH` 在 PyInstaller 里只对 Windows 的 PE 时间戳生效）。
    所以校验值只能“这次构建的产物配这次的哈希”。
    """
    out = Path(str(deliverable) + ".sha256")
    out.write_text(
        f"{sha256_file(deliverable)}  {deliverable.name}\n",
        encoding="utf-8",
        newline="",
    )
    return out


def make_app_zip(artifact: Path) -> Path:
    """把 macOS .app 打成可分发 zip。

    必须用系统 ditto：.app 内含符号链接与可执行权限，Python 标准库 zipfile
    默认不保留符号链接，解压后包会坏。ditto 是 macOS 自带工具，不引入新依赖。
    """
    out = artifact.parent / f"{artifact.stem}-macos.zip"
    if out.exists():
        out.unlink()
    subprocess.run(
        [
            "ditto",
            "-c",
            "-k",
            "--sequesterRsrc",
            "--keepParent",
            str(artifact),
            str(out),
        ],
        check=True,
    )
    return out


def _terminate_tree(proc: subprocess.Popen) -> None:
    """结束进程树（onefile 模式 PyInstaller 会 fork 出子进程）。"""
    if sys.platform == "win32":
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
            capture_output=True,
            check=False,
        )
        return
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        proc.terminate()


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="TopoSort 三端单文件打包（PyInstaller 封装，Issue #8）",
    )
    parser.add_argument("--name", default=DEFAULT_NAME, help="产物名（默认 TopoSort）")
    parser.add_argument(
        "--distpath",
        type=Path,
        default=REPO_ROOT / "dist",
        help="产物目录（默认 dist/）",
    )
    parser.add_argument(
        "--workpath",
        type=Path,
        default=REPO_ROOT / "build",
        help="中间目录（默认 build/）",
    )
    parser.add_argument(
        "--no-optimize",
        dest="optimize",
        action="store_false",
        help="关闭体积优化 excludes（用于对照实测）",
    )
    parser.add_argument(
        "--console",
        action="store_true",
        help="保留控制台窗口（Windows/macOS 排查启动崩溃时用）",
    )
    parser.add_argument(
        "--no-strip",
        dest="strip",
        action="store_false",
        help="不裁剪共享库符号表（默认仅 Linux 开启）",
    )
    parser.add_argument(
        "--no-zip",
        dest="zip",
        action="store_false",
        help="macOS 上不额外打 .app 分发包（默认打）",
    )
    parser.add_argument(
        "--mode",
        choices=["onefile", "onedir"],
        default=None,
        help="打包模式（默认：macOS 为 onedir，其余为 onefile）",
    )
    parser.add_argument(
        "--smoke",
        action="store_true",
        help="构建后做空目录启动冒烟（剥离 Python 环境变量，offscreen）",
    )
    parser.add_argument(
        "--smoke-seconds",
        type=int,
        default=10,
        help="冒烟存活判据秒数（默认 10）",
    )
    parser.set_defaults(
        optimize=True,
        strip=sys.platform.startswith("linux"),
        zip=sys.platform == "darwin",
        mode=None,
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    force_utf8_stdio()
    args = parse_args(argv)
    artifact, elapsed = build(args)

    binary = launchable_binary(artifact)
    size = sum(f.stat().st_size for f in artifact.rglob("*") if f.is_file()) \
        if artifact.is_dir() else artifact.stat().st_size

    print()
    print("=" * 72)
    print("构建结果")
    print("=" * 72)
    print(f"平台       : {sys.platform}")
    print(f"产物       : {artifact}")
    print(f"体积       : {human_mb(size)}（{size} 字节）")
    print(f"构建耗时   : {elapsed:.1f}s")
    if binary != artifact:
        print(f"可执行文件 : {binary}（{human_mb(binary.stat().st_size)}）")
    print(f"SHA256     : {sha256_file(binary)}")

    if sys.platform.startswith("linux"):
        needles = [b"libqxcb.so", b"libqoffscreen.so", b"libqwayland-generic.so"]
    elif sys.platform == "darwin":
        needles = [b"libqcocoa.dylib"]
    else:
        needles = [b"qwindows.dll"]
    found = embedded_names(binary, needles)
    print(f"内嵌平台插件: {'、'.join(found) if found else '（未在字节流中命中，见下方说明）'}")
    if not found:
        print("  ⚠ 目录表可能是压缩存放；以 --smoke 的运行时结果为准")

    # 交付物：macOS 的 .app 是目录，先打成 zip 才能当 Release 资产；其余平台产物本身即单文件
    deliverable = artifact
    if args.zip:
        if artifact.is_dir() and artifact.suffix == ".app":
            deliverable = make_app_zip(artifact)
            print(f"分发包     : {deliverable}（{human_mb(deliverable.stat().st_size)}）")
        else:
            print("（--zip 跳过：本平台产物不是 .app 目录，无需再打包）")

    checksum = write_checksum(deliverable)
    print(f"交付物     : {deliverable}")
    print(f"交付物SHA256: {sha256_file(deliverable)}")
    print(f"校验文件   : {checksum}（sha256sum -c 兼容）")

    print()
    print("建议追加到 evidence/benchmarks.csv 的一行（append-only，勿改旧行）：")
    print("  注意：本表固定 7 列（日期,用例名,节点数,边数,结果数,耗时ms,模式）。打包类记录没有"
          "节点/边/结果数，故这三列留空；体积与开关等附加信息统一放进「模式」列，用 `;` 分隔，"
          "以免新增逗号列破坏既有表头 schema。")
    print(
        f"{time.strftime('%Y-%m-%d')},{args.name}-{sys.platform}-onefile"
        f",,,,{int(elapsed * 1000)}"
        f",package;size_mb={size / 1024 / 1024:.1f}"
        f";optimize={'on' if args.optimize else 'off'}"
        f";strip={'on' if args.strip else 'off'}"
    )

    if args.smoke:
        if not smoke(binary, args.smoke_seconds, artifact):
            return 2

    print()
    print("✅ 打包完成")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
