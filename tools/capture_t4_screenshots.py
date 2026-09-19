"""Generate the four reproducible T4 visual-effect screenshots."""

from __future__ import annotations

import os
import re
import sys
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from PySide6.QtCore import QPoint
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from app.events import Consume, CycleFound, Enqueue
from app.scene import CandidatePool, Effects, GraphBoard


NODES = frozenset({"A", "B", "C", "D", "E"})
EDGES = frozenset({("A", "C"), ("A", "E"), ("B", "C"), ("C", "D")})
LAYERS = {"A": 0, "B": 0, "C": 1, "D": 2, "E": 1}


def _next_run_number(directory: Path, date_tag: str) -> int:
    pattern = re.compile(rf"^t4-.*-{date_tag}-(\d+)\.png$")
    numbers: list[int] = []
    for path in directory.glob(f"t4-*-{date_tag}-*.png"):
        match = pattern.match(path.name)
        if match:
            numbers.append(int(match.group(1)))
    return max(numbers, default=0) + 1


def _new_board() -> GraphBoard:
    return GraphBoard(NODES, EDGES, LAYERS)


def _prepare_ready_state(
    board: GraphBoard,
    pool: CandidatePool,
    nodes: tuple[str, ...],
) -> None:
    for node in nodes:
        board.apply_event(Enqueue(node, 0))
    pool.set_ready(nodes)


def _prepare_active_state(
    board: GraphBoard,
    pool: CandidatePool,
    node: str,
) -> None:
    _prepare_ready_state(board, pool, (node,))
    board.apply_event(Consume(node, 0))
    pool.on_consume(node)


def _wait_for_active_frame() -> None:
    QTest.qWait(Effects.PULSE_MS // 2)


def _compose(board_path: Path, pool_path: Path, output: Path) -> None:
    board_image = QImage(str(board_path))
    pool_image = QImage(str(pool_path))
    width = max(board_image.width(), pool_image.width()) + 40
    height = board_image.height() + pool_image.height() + 60
    image = QImage(width, height, QImage.Format.Format_ARGB32)
    image.fill(QColor("#0f1726"))
    painter = QPainter(image)
    painter.drawImage(QPoint(20, 20), pool_image)
    painter.drawImage(QPoint(20, pool_image.height() + 35), board_image)
    painter.end()
    image.save(str(output), "PNG")


def _capture_state(board: GraphBoard, pool: CandidatePool, output: Path) -> None:
    with TemporaryDirectory(prefix="t4-capture-") as temporary:
        temporary_path = Path(temporary)
        board_path = temporary_path / "board.png"
        pool_path = temporary_path / "pool.png"
        board.export_png(board_path)
        pool.export_png(pool_path)
        _compose(board_path, pool_path, output)


def main() -> None:
    app = QApplication.instance() or QApplication([])
    output_dir = PROJECT_ROOT / "evidence" / "screenshots"
    output_dir.mkdir(parents=True, exist_ok=True)
    date_tag = datetime.now().strftime("%Y%m%d")
    run_number = _next_run_number(output_dir, date_tag)

    ready_board = _new_board()
    ready_pool = CandidatePool()
    _prepare_ready_state(ready_board, ready_pool, ("A", "B"))
    _capture_state(
        ready_board,
        ready_pool,
        output_dir / f"t4-ready-{date_tag}-{run_number}.png",
    )

    active_board = _new_board()
    active_pool = CandidatePool()
    _prepare_active_state(active_board, active_pool, "A")
    app.processEvents()
    _wait_for_active_frame()
    _capture_state(
        active_board,
        active_pool,
        output_dir / f"t4-active-pulse-{date_tag}-{run_number}.png",
    )

    QTest.qWait(Effects.GHOST_MS + 25)
    app.processEvents()
    _capture_state(
        active_board,
        active_pool,
        output_dir / f"t4-ghost-edge-dim-{date_tag}-{run_number}.png",
    )

    stuck_board = _new_board()
    stuck_pool = CandidatePool()
    stuck_board.apply_event(CycleFound(frozenset({"A", "B"})))
    _capture_state(
        stuck_board,
        stuck_pool,
        output_dir / f"t4-stuck-{date_tag}-{run_number}.png",
    )

    app.processEvents()
    app.quit()


if __name__ == "__main__":
    main()
