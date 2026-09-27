#!/usr/bin/env python3
"""界面截图工具：把 MainWindow 的各状态渲染成 PNG，存进 evidence/screenshots/。

用法（唯一姿势）：

    uv run python tools/shoot.py

为什么用脚本而不是手截：
  - 命名规则 `功能名-YYYYMMDD-N.png` 与「PNG > 20KB」是 CI 机械检查项
    （tools/check_docs.py），脚本自动合规；手截容易截小了、命名错了、忘挪目录。
  - QWidget.grab() 是 Qt 自己把窗口重绘成位图，不调系统截图接口，
    Windows / macOS / Linux 行为一致，而且不受别的窗口遮挡。

阶段自适应（重要）：
  T2 / T3 / T4 尚未合并时，依赖它们的界面状态**根本截不出来**（parse() 会抛
  NotImplementedError）。本脚本遇到这种情况打印「跳过」并说明原因，**绝不伪造**。
  等对应模块合并后重跑本脚本，缺的图自动补齐，无需改代码。
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))  # 直接执行本脚本时，让 import app.* 能找到仓库根

# Windows 控制台默认 GBK，打印中文文件名会抛 UnicodeEncodeError；统一改 UTF-8
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from app.ui import MainWindow  # noqa: E402

OUT = ROOT / "evidence" / "screenshots"
DATA = ROOT / "report" / "data"          # 演示数据（图1 / 学业指南）——报告与截图共用同一份
TODAY = date.today().strftime("%Y%m%d")
WINDOW_SIZE = (1280, 800)          # 别调太小：整窗白底可能压到 20KB 以下
MIN_BYTES = 20 * 1024              # check_docs.py 的截图门槛

CANON = "<A,C>\n<A,E>\n<B,C>\n<C,D>\n"   # 标准基准图，恰 7 条合法序（2026-09-19 修正，原 6 条漏 A E B C D）
BAD_PARSE = "<A,B>\n<A>\n"               # 第 2 行残缺 → 解析错误（含行号）
CYCLE = "<A,B>\n<B,A>\n"                 # 互依赖 → 环

_log: list[str] = []


def next_path(name: str) -> Path:
    """`功能名-YYYYMMDD-N.png`，N 从 1 起，已有文件则顺延，不覆盖旧图。"""
    n = 1
    while True:
        path = OUT / f"{name}-{TODAY}-{n}.png"
        if not path.exists():
            return path
        n += 1


def snap(win: MainWindow, name: str) -> None:
    """把当前窗口状态存成一张图。"""
    app = QApplication.instance()
    app.processEvents()  # 让布局/样式先算完，否则可能截到半成品
    path = next_path(name)
    win.grab().save(str(path))
    size = path.stat().st_size
    warn = "" if size >= MIN_BYTES else "   <-- 低于 20KB，被文档引用会被 check_docs 打回"
    _log.append(f"  [图] {path.name:<40} {size:>8} B{warn}")


def skip(name: str, why: str) -> None:
    _log.append(f"  [跳过] {name:<40} {why}")


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)

    app = QApplication.instance() or QApplication(sys.argv)
    win = MainWindow()
    win.resize(*WINDOW_SIZE)
    win.show()
    app.processEvents()

    # ---- ① 壳本身的状态：不依赖 T2/T3/T4，任何时候都能截 ----
    snap(win, "主窗口-初始")

    win.set_input(CANON)
    snap(win, "主窗口-输入完成")

    # ---- ② 点「开始」之后：结果流 or 降级提示，二者必居其一 ----
    win.click_start()
    app.processEvents()
    if win.results():
        snap(win, "主窗口-结果流")
    elif win.error_text():
        # 此刻的文案通常是「某模块尚未完成」——这是真实降级态，不是造假
        snap(win, "主窗口-降级提示")

    # ---- ③ 两类错误呈现（T5 验收要求：文案含行号 / 含"环"）----
    for name, text, must in (
        ("主窗口-解析错误提示", BAD_PARSE, "行"),
        ("主窗口-环检测提示", CYCLE, "环"),
    ):
        win.set_input(text)
        win.click_start()
        app.processEvents()
        err = win.error_text() or ""
        if must in err:
            snap(win, name)
        else:
            why = "算法模块（T2 models）未就绪" if not err else f"文案不符：{err[:40]}"
            skip(name, why)

    # ---- ④ 动画：多分支泳道并推 + 画布节点状态（T3/T4 就绪后自动出现）----
    win.set_input(CANON)
    win.click_start()
    QTest.qWait(1200)  # 默认 400ms/拍，等约 3 拍
    if win.lanes.lane_ids():
        snap(win, "主窗口-泳道并推")
    else:
        skip("主窗口-泳道并推", "事件引擎（T3 events）未就绪，泳道无数据")

    # ---- ⑤ 真实课程图：任务书图1（15 门课）+ 学业指南计算机培养方案（44 门课）----
    # 两张图的结果数都远超上限（1,566,180 / 10^41 量级），用来截“已达上限 + 总数估算”的真实界面。
    for name, data_file in (
        ("主窗口-图1课程图", DATA / "figure1-courses.txt"),
        ("主窗口-学业指南课程图", DATA / "study-guide-cs.txt"),
    ):
        if not data_file.exists():
            skip(name, f"缺数据文件 {data_file.relative_to(ROOT)}")
            continue
        win.set_input(data_file.read_text(encoding="utf-8"))
        win.click_start()
        QTest.qWait(1200)
        if win.results():
            snap(win, name)
        else:
            skip(name, "结果流为空（算法模块未就绪？）")

    win.set_input("")  # 收尾：停掉计时器，别让脚本挂着不退

    print(f"截图目录：{OUT}")
    print("\n".join(_log))
    print(f"\n共 {sum(1 for line in _log if '[图]' in line)} 张，"
          f"{sum(1 for line in _log if '[跳过]' in line)} 项因依赖未就绪跳过。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
