"""golden 事件流生成器：为 evidence/test-data/ 下每个 *.in 生成 *.events.json。

用法：uv run python tools/gen_golden_events.py
说明：.in 仅支持严格 `<a,b>` 行（宽松容错解析归 app/models/parser.py，
此处刻意不重复实现算法/解析）。生成结果即 golden——确定性契约保证
任意平台任意时刻重跑，输出逐字节一致。
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.events import TopoPlayer, event_to_dict  # noqa: E402
from app.models import Graph  # noqa: E402

TESTDATA = ROOT / "evidence" / "test-data"


def graph_from_in(path: Path) -> Graph:
    nodes, edges = set(), set()
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        left, right = line.strip("<>").split(",")
        a, b = left.strip(), right.strip()
        nodes.add(a)
        nodes.add(b)
        edges.add((a, b))
    return Graph(frozenset(nodes), frozenset(edges))


def main() -> None:
    for in_file in sorted(TESTDATA.glob("*.in")):
        events = list(TopoPlayer(graph_from_in(in_file)).iter_events())
        out = in_file.with_suffix(".events.json")
        body = ",\n ".join(json.dumps(event_to_dict(e), ensure_ascii=False) for e in events)
        out.write_text("[" + body + "]\n", encoding="utf-8", newline="")
        print(f"{out.name}: {len(events)} events")


if __name__ == "__main__":
    main()
