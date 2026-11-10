from __future__ import annotations

import json
from contextlib import redirect_stderr, redirect_stdout
import io
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from sipl.cli import main


class CliTests(unittest.TestCase):
    def invoke(self, command: str, source: str, *arguments: str) -> subprocess.CompletedProcess[str]:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "test.sipl"
            path.write_text(source, encoding="utf-8")
            return subprocess.run(
                [sys.executable, "-m", "sipl.cli", command, str(path), *arguments],
                check=False,
                capture_output=True,
                text=True,
            )

    def test_parse_json(self) -> None:
        completed = self.invoke("parse", "begin skip end", "--json")
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(json.loads(completed.stdout)["type"], "Program")

    def test_check_and_run_json(self) -> None:
        check = self.invoke("check", "begin X := 3 end", "--json")
        run = self.invoke("run", "begin X := 3 end", "--json")
        self.assertEqual(check.returncode, 0, check.stderr)
        self.assertTrue(json.loads(check.stdout)["valid"])
        self.assertEqual(json.loads(run.stdout)["state"], {"X": 3})

    def test_parse_error_exit_code_and_json_diagnostic(self) -> None:
        completed = self.invoke("check", "begin X := end", "--json")
        self.assertEqual(completed.returncode, 2)
        self.assertEqual(json.loads(completed.stderr)["error"]["code"], "PARSE_ERROR")

    def test_trace_returns_json_events(self) -> None:
        completed = self.invoke("trace", "begin X := 1 end", "--json")
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertTrue(json.loads(completed.stdout)["trace"])

    def test_tree_formats_and_source_diagnostics(self) -> None:
        source = "begin\n  X := (1 + 2)\nend\n"
        text = self.invoke("tree", source)
        data = self.invoke("tree", source, "--format", "json")
        dot = self.invoke("tree", source, "--format", "dot")
        for completed in (text, data, dot):
            self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn('IDENT "X" [2:3-2:4]', text.stdout)
        self.assertEqual(json.loads(data.stdout)["text"], source)
        self.assertIn("digraph SIPL {", dot.stdout)

        invalid = self.invoke("tree", "begin X := end", "--format", "json")
        self.assertEqual(invalid.returncode, 2)
        self.assertEqual(json.loads(invalid.stderr)["error"]["code"], "PARSE_ERROR")

    def test_all_commands_through_library_entry_point(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "test.sipl"
            path.write_text("begin X := X + 1 end", encoding="utf-8")
            for args in (
                ["parse", str(path), "--json"],
                ["check", str(path), "--json"],
                ["run", str(path), "--state", '{"X": 2}', "--json"],
                ["trace", str(path), "--state", '{"X": 2}', "--json"],
                ["tree", str(path), "--format", "json"],
            ):
                with self.subTest(args=args):
                    output = io.StringIO()
                    with redirect_stdout(output):
                        self.assertEqual(main(args), 0)
                    self.assertTrue(json.loads(output.getvalue()))

    def test_json_state_errors_and_missing_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "test.sipl"
            path.write_text("begin skip end", encoding="utf-8")
            for args in (
                ["run", str(path), "--state", "[]", "--json"],
                ["trace", str(path), "--state", '{"X": true}', "--json"],
                ["run", str(path), "--max-steps", "0", "--json"],
                ["check", str(path) + ".missing", "--json"],
            ):
                with self.subTest(args=args):
                    output = io.StringIO()
                    with redirect_stderr(output):
                        self.assertEqual(main(args), 2)
                    self.assertTrue(json.loads(output.getvalue())["error"])

    def test_human_output_and_non_json_errors(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "test.sipl"
            path.write_text("begin X := 4 end", encoding="utf-8")
            output = io.StringIO()
            with redirect_stdout(output):
                self.assertEqual(main(["run", str(path)]), 0)
            self.assertIn('"X": 4', output.getvalue())
            path.write_text("begin X := end", encoding="utf-8")
            errors = io.StringIO()
            with redirect_stderr(errors):
                self.assertEqual(main(["check", str(path)]), 2)
            self.assertIn("line 1", errors.getvalue())

    def test_tree_json_error_through_library_entry_point(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "test.sipl"
            path.write_text("begin X := end", encoding="utf-8")
            errors = io.StringIO()
            with redirect_stderr(errors):
                self.assertEqual(main(["tree", str(path), "--format", "json"]), 2)
            self.assertEqual(json.loads(errors.getvalue())["error"]["code"], "PARSE_ERROR")


if __name__ == "__main__":
    unittest.main()
