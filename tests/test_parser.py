from __future__ import annotations

import unittest

from sipl.ast import Program, to_data
from sipl.diagnostics import LexError, ParseError
from sipl.parser import parse


VALID_PROGRAMS = [
    "begin skip end",
    "begin X := 0 end",
    "begin X := 1 + 2 end",
    "begin X := 1 - 2 * 3 end",
    "begin X := (1 + 2) * 3 end",
    "begin X := -1 end",
    "begin X := 1; Y := X end",
    "begin if X = 0 then skip else Y := 1 end",
    "begin if ¬(X > 0) then skip else X := X - 1 end",
    "begin while X > 0 do X := X - 1 end",
    "begin begin X := 1; Y := 2 end end",
    "begin if (X + 1) > 0 then skip else skip end",
    "begin if (X > 0) ∨ (Y = 0) then skip else skip end",
    "begin X := 1; if X > 0 then Y := 1 else Y := 2 end",
    "begin skip; skip; skip end",
]

INVALID_PROGRAMS = [
    "",
    "skip",
    "begin end",
    "begin X = 1 end",
    "begin X := end",
    "begin X := 1 + end",
    "begin while X > 0 X := 1 end",
    "begin if X > 0 then skip end",
    "begin if X > 0 skip else skip end",
    "begin X := 1;; Y := 2 end",
    "begin X := (1 + 2 end",
    "begin X := 1 @ 2 end",
    "begin X := ١ end",
    "begin begin skip end",
    "begin X := 1 Y := 2 end",
    "begin if (X + 1) then skip else skip end",
]


class ParserTests(unittest.TestCase):
    def test_at_least_ten_valid_programs(self) -> None:
        for source in VALID_PROGRAMS:
            with self.subTest(source=source):
                self.assertIsInstance(parse(source), Program)

    def test_at_least_ten_invalid_programs_have_source_diagnostics(self) -> None:
        for source in INVALID_PROGRAMS:
            with self.subTest(source=source):
                with self.assertRaises((LexError, ParseError)) as caught:
                    parse(source)
                self.assertIsNotNone(caught.exception.span)

    def test_ast_is_typed_and_has_spans(self) -> None:
        ast = parse("begin\n  X := 1 + 2\nend")
        data = to_data(ast)
        self.assertEqual(data["type"], "Program")
        self.assertEqual(data["statement"]["type"], "Assign")
        self.assertEqual(data["statement"]["span"]["startLine"], 2)

    def test_boolean_grouping_and_arithmetic_grouping(self) -> None:
        parse("begin if ((X + 1) > 2) ∨ (Y = 0) then skip else skip end")


if __name__ == "__main__":
    unittest.main()
