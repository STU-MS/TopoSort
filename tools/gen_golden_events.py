"""golden 事件流生成器：为 evidence/test-data/ 下带 golden 的 *.in 重新生成 *.events.json。

用法：uv run python tools/gen_golden_events.py [--all]
说明：.in 仅支持严格 `<a,b>` 行（宽松容错解析归 app/models/parser.py，
此处刻意不重复实现算法/解析）：宽容写法的文件（全角括号/裸写/残缺行）直接
跳过并说明，不再中断整个生成过程。
默认只为**已有** `.events.json` 的用例重生（保持 golden 集合稳定；
`--all` 则给所有严格格式文件都生成）。生成结果即 golden——确定性契约
保证任意平台任意时刻重跑，输出逐字节一致。
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.events import TopoPlayer, event_to_dict  # noqa: E402
from app.models import Graph  # noqa: E402

TESTDATA = ROOT / "evidence" / "test-data"

# 真实课程图不生成 golden：009 有 156 万条序、010 是 10^41 量级，事件流会跑到天荒地老
# （且 .events.json 会大到无意义）。它们的结构断言见 app/tests/test_models.py 的
# TestRealCourseGraphs。
NO_GOLDEN = {"009-任务书图一", "010-学业指南计算机培养方案"}


def graph_from_in(path: Path) -> Graph | None:
    """严格 `<a,b>` 行 → Graph；遇宽容写法（宽容格式/残缺行）返回 None 让调用方跳过。"""

    nodes, edges = set(), set()
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.strip("<>").split(",")
        if len(parts) != 2:
            return None
        a, b = parts[0].strip(), parts[1].strip()
        nodes.add(a)
        nodes.add(b)
        edges.add((a, b))
    return Graph(frozenset(nodes), frozenset(edges))


def main() -> None:
    rebuild_all = "--all" in sys.argv[1:]
    for in_file in sorted(TESTDATA.glob("*.in")):
        out = in_file.with_suffix(".events.json")
        if in_file.stem in NO_GOLDEN:
            print(f"{in_file.name}: 跳过（真实课程图，结果数过大，不生成 golden）")
            continue
        if not rebuild_all and not out.exists():
            print(f"{in_file.name}: 跳过（本用例没有 golden；要生成请加 --all）")
            continue
        graph = graph_from_in(in_file)
        if graph is None:
            print(f"{in_file.name}: 跳过（含宽容写法，本脚本只吃严格 <a,b> 行）")
            continue
        events = list(TopoPlayer(graph).iter_events())
        body = ",\n ".join(json.dumps(event_to_dict(e), ensure_ascii=False) for e in events)
        out.write_text("[" + body + "]\n", encoding="utf-8", newline="")
        print(f"{out.name}: {len(events)} events")


if __name__ == "__main__":
    main()
