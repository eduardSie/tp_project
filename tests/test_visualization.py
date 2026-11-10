from __future__ import annotations

import unittest
from collections.abc import Iterator

from sipl import parse, parse_with_tree
from sipl.diagnostics import SipleError
from sipl.parser import ParseTreeNode, tokenize
from sipl.visualization import format_tree_dot, format_tree_text, tree_to_data


def walk(node: ParseTreeNode) -> Iterator[ParseTreeNode]:
    yield node
    for child in node.children:
        yield from walk(child)


class ParseTreeTests(unittest.TestCase):
    def test_derivation_matches_ast_tokens_and_source_spans(self) -> None:
        sources = [
            "begin skip end",
            "  begin\n  X := -(1 + 2) * 3;\n  while X > 0 do X := X - 1\nend\n",
            "begin if (X + 1) > 2 then skip else Y := 3 end",
            "begin if ((X + 1) > 2) ∨ (Y = 0) then skip else skip end",
            "begin if ¬(X > 1) | (Y = 0) then begin X := 1; Y := 2 end else skip end",
        ]
        for source in sources:
            with self.subTest(source=source):
                program, tree = parse_with_tree(source)
                self.assertEqual(program, parse(source))
                self.assertEqual(tree.root.symbol, "program")
                nodes = list(walk(tree.root))
                leaves = [node for node in nodes if node.lexeme is not None]
                self.assertEqual(
                    [(node.symbol, node.lexeme, node.span) for node in leaves],
                    [(token.kind, token.value, token.span) for token in tokenize(source)],
                )
                for node in nodes:
                    fragment = source[node.span.start_offset:node.span.end_offset]
                    if node.lexeme is not None:
                        self.assertEqual(node.lexeme, fragment)
                        self.assertEqual(node.children, ())
                    else:
                        self.assertTrue(node.children)
                        self.assertEqual(node.span.start_offset, node.children[0].span.start_offset)
                        self.assertEqual(node.span.end_offset, node.children[-1].span.end_offset)
                        for left, right in zip(node.children, node.children[1:]):
                            self.assertLessEqual(left.span.end_offset, right.span.start_offset)

    def test_tree_contains_concrete_grammar_and_punctuation(self) -> None:
        _, tree = parse_with_tree("begin X := (1 + 2) end")
        symbols = [node.symbol for node in walk(tree.root)]
        for symbol in ("program", "statement", "simple_statement", "arithmetic", "atom"):
            self.assertIn(symbol, symbols)
        for symbol in ("BEGIN", "IDENT", "ASSIGN", "(", "+", ")", "END", "EOF"):
            self.assertIn(symbol, symbols)
        self.assertNotIn("Assign", symbols)

    def test_invalid_programs_report_the_same_diagnostic(self) -> None:
        for source in ("begin X := end", "begin @ end", "begin if (X > ) then skip else skip end"):
            with self.subTest(source=source):
                with self.assertRaises(SipleError) as ordinary:
                    parse(source)
                with self.assertRaises(SipleError) as visualized:
                    parse_with_tree(source)
                self.assertEqual(ordinary.exception.to_dict(), visualized.exception.to_dict())

    def test_text_json_and_dot_link_nodes_to_source(self) -> None:
        source = "begin\n  X := 1 + 2\nend\n"
        _, tree = parse_with_tree(source)
        text = format_tree_text(tree)
        self.assertIn('BEGIN "begin" [1:1-1:6]', text)
        self.assertIn('IDENT "X" [2:3-2:4]', text)
        data = tree_to_data(tree)
        self.assertEqual(data["symbol"], "program")
        self.assertEqual(data["kind"], "nonterminal")
        self.assertEqual(data["text"], source)
        begin = data["children"][0]
        self.assertEqual(begin["kind"], "terminal")
        self.assertEqual(begin["text"], "begin")
        self.assertEqual(begin["span"]["startLine"], 1)
        dot = format_tree_dot(tree)
        self.assertTrue(dot.startswith("digraph SIPL {\n"))
        self.assertIn('tooltip="begin\\n  X := 1 + 2\\nend\\n"', dot)
        self.assertIn("1:1-1:6", dot)
        self.assertEqual(dot.count("[label="), len(list(walk(tree.root))))
        self.assertEqual(dot.count(" -> "), len(list(walk(tree.root))) - 1)


if __name__ == "__main__":
    unittest.main()
