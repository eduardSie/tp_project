"""Text, JSON-compatible and DOT views of a concrete SIPL parse tree."""

from __future__ import annotations

import json

from sipl.ast import SourceSpan
from sipl.parser import ParseTree, ParseTreeNode


def _location(span: SourceSpan) -> str:
    return (
        f"{span.start_line}:{span.start_column}-"
        f"{span.end_line}:{span.end_column}"
    )


def tree_to_data(tree: ParseTree) -> dict[str, object]:
    """Return a JSON-compatible tree with source text and spans for every node."""
    def convert(node: ParseTreeNode) -> dict[str, object]:
        return {
            "symbol": node.symbol,
            "kind": "terminal" if node.lexeme is not None else "nonterminal",
            "span": node.span.to_dict(),
            "text": tree.source[node.span.start_offset:node.span.end_offset],
            "children": [convert(child) for child in node.children],
        }

    return convert(tree.root)


def format_tree_text(tree: ParseTree) -> str:
    """Render a derivation tree as indented text with source locations."""
    lines: list[str] = []

    def visit(node: ParseTreeNode, depth: int) -> None:
        value = (
            f" {json.dumps(node.lexeme, ensure_ascii=False)}"
            if node.lexeme is not None
            else ""
        )
        lines.append(f"{'  ' * depth}{node.symbol}{value} [{_location(node.span)}]")
        for child in node.children:
            visit(child, depth + 1)

    visit(tree.root, 0)
    return "\n".join(lines)


def format_tree_dot(tree: ParseTree) -> str:
    """Render DOT; each node includes its source location and source tooltip."""
    lines = ["digraph SIPL {", "  node [shape=ellipse];"]
    next_id = 0

    def visit(node: ParseTreeNode) -> int:
        nonlocal next_id
        node_id = next_id
        next_id += 1
        value = f" {node.lexeme!r}" if node.lexeme is not None else ""
        label = f"{node.symbol}{value}\n{_location(node.span)}"
        snippet = tree.source[node.span.start_offset:node.span.end_offset]
        shape = ", shape=box" if node.lexeme is not None else ""
        lines.append(
            f"  n{node_id} [label={json.dumps(label, ensure_ascii=False)}, "
            f"tooltip={json.dumps(snippet, ensure_ascii=False)}{shape}];"
        )
        for child in node.children:
            child_id = visit(child)
            lines.append(f"  n{node_id} -> n{child_id};")
        return node_id

    visit(tree.root)
    lines.append("}")
    return "\n".join(lines)
