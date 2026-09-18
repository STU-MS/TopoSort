"""`<a,b>` 文本解析。实现 T2（issue #3）。"""

from app.models.graph import Graph


class ParseError(ValueError):
    """解析失败。lineno 从 1 开始；line 为原始行文本。"""

    def __init__(self, lineno: int, line: str, reason: str):
        super().__init__(f"第 {lineno} 行解析失败：{reason}（原文：{line!r}）")
        self.lineno = lineno
        self.line = line
        self.reason = reason


def parse(text: str) -> Graph:
    """将逐行关系文本解析为不可变有向图。"""

    nodes: set[str] = set()
    edges: set[tuple[str, str]] = set()

    for lineno, original in enumerate(text.splitlines(), start=1):
        line = original.strip()
        if not line:
            continue

        normalized = line.translate(str.maketrans({"（": "(", "）": ")", "，": ","}))
        content = _unwrap(normalized, lineno, original)
        parts = content.split(",")
        if len(parts) != 2:
            raise ParseError(lineno, original, "每行必须包含且仅包含一个逗号")

        source, target = (part.strip() for part in parts)
        if not source or not target:
            raise ParseError(lineno, original, "关系两端的节点名不能为空")
        if source == target:
            raise ParseError(lineno, original, "不允许自环")

        nodes.update((source, target))
        edges.add((source, target))

    return Graph(frozenset(nodes), frozenset(edges))


def _unwrap(line: str, lineno: int, original: str) -> str:
    pairs = {"<": ">", "(": ")"}
    if line[0] in pairs:
        if line[-1] != pairs[line[0]]:
            raise ParseError(lineno, original, "关系括号不匹配")
        content = line[1:-1].strip()
        if any(char in content for char in "<>()"):
            raise ParseError(lineno, original, "关系括号不匹配")
        return content
    if line[-1] in pairs.values() or any(char in line for char in "<>()"):
        raise ParseError(lineno, original, "关系括号不匹配")
    return line
