from __future__ import annotations

from io import BytesIO
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from sipl.debug_adapter import DapServer, DebugSession
from sipl.diagnostics import ExecutionError


class DebugSessionTests(unittest.TestCase):
    def test_step_advances_statement_and_state(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "program.sipl"
            path.write_text("begin\n X := 2;\n Y := X + 3\nend\n", encoding="utf-8")
            session = DebugSession()
            session.launch(str(path), {}, 100)
            reason, first = session.advance(step=True)
            self.assertEqual(reason, "stopped")
            self.assertEqual(first.span.start_line, 2)
            reason, second = session.advance(step=True)
            self.assertEqual(reason, "stopped")
            self.assertEqual(second.span.start_line, 3)
            self.assertEqual(session.state["X"], 2)
            reason, _ = session.advance(step=True)
            self.assertEqual(reason, "terminated")
            self.assertEqual(session.state["Y"], 5)

    def test_continue_stops_on_source_breakpoint(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "program.sipl"
            path.write_text("begin\n X := 1;\n Y := X + 1\nend\n", encoding="utf-8")
            session = DebugSession()
            session.launch(str(path), {}, 100)
            session.set_breakpoints([3])
            session.advance(step=True)
            reason, event = session.advance(step=False)
            self.assertEqual(reason, "stopped")
            self.assertEqual(event.span.start_line, 3)

    def test_breakpoints_only_verify_statement_lines(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "program.sipl"
            path.write_text("begin\n X := 1\nend\n", encoding="utf-8")
            session = DebugSession()
            session.launch(str(path), {}, 100)
            breakpoints = session.set_breakpoints([1, 2, 4])
            self.assertEqual([item["verified"] for item in breakpoints], [False, True, False])

    def test_loop_breakpoint_stops_on_each_condition_check(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "program.sipl"
            path.write_text(
                "begin\n while X > 0 do\n  X := X - 1\nend\n",
                encoding="utf-8",
            )
            session = DebugSession()
            session.launch(str(path), {"X": 2}, 100)
            session.set_breakpoints([2])
            reason, _ = session.advance(step=False)
            self.assertEqual(reason, "stopped")
            self.assertEqual(session.current_span.start_line, 2)
            self.assertEqual(session.state["X"], 2)
            reason, _ = session.advance(step=False)
            self.assertEqual(reason, "stopped")
            self.assertEqual(session.current_span.start_line, 2)
            self.assertEqual(session.state["X"], 1)

    def test_loop_step_and_breakpoint_stop_before_the_condition(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "program.sipl"
            path.write_text(
                "begin\n while X > 0 do\n  X := X - 1\nend\n",
                encoding="utf-8",
            )
            session = DebugSession()
            session.launch(str(path), {"X": 2}, 100)
            session.advance(step=True)
            self.assertEqual(session.current_span.start_line, 2)
            session.advance(step=True)
            self.assertEqual(session.current_span.start_line, 3)
            session.advance(step=True)
            self.assertEqual(session.current_span.start_line, 2)
            self.assertEqual(session.state["X"], 1)

            session.launch(str(path), {}, 100)
            session.set_breakpoints([2])
            reason, _ = session.advance(step=False)
            self.assertEqual(reason, "stopped")
            self.assertEqual(session.current_span.start_line, 2)
            with self.assertRaises(ExecutionError):
                session.advance(step=False)


class ExtensionManifestTests(unittest.TestCase):
    def test_breakpoints_are_enabled_for_sipl_files(self) -> None:
        manifest_path = Path(__file__).resolve().parents[1] / "vscode-sipl" / "package.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        self.assertIn({"language": "sipl"}, manifest["contributes"]["breakpoints"])
        self.assertTrue(any(item["type"] == "sipl" for item in manifest["contributes"]["debuggers"]))


class DapServerTests(unittest.TestCase):
    @staticmethod
    def unpack_messages(data: bytes) -> list[dict[str, object]]:
        messages = []
        while data:
            header, data = data.split(b"\r\n\r\n", 1)
            length = int(header.split(b":", 1)[1].strip())
            messages.append(json.loads(data[:length]))
            data = data[length:]
        return messages

    def test_debug_protocol_lifecycle(self) -> None:
        output = BytesIO()
        server = DapServer(BytesIO(), output)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "program.sipl"
            path.write_text("begin\n X := X + 1;\n Y := X * 2\nend\n", encoding="utf-8")
            requests = [
                {"seq": 1, "command": "initialize"},
                {
                    "seq": 2,
                    "command": "launch",
                    "arguments": {"program": str(path), "initialState": {"X": 1}},
                },
                {
                    "seq": 3,
                    "command": "setExceptionBreakpoints",
                    "arguments": {"filters": []},
                },
                {
                    "seq": 4,
                    "command": "setBreakpoints",
                    "arguments": {
                        "source": {"path": str(path)},
                        "breakpoints": [{"line": 3}],
                    },
                },
                {"seq": 5, "command": "configurationDone"},
                {"seq": 6, "command": "continue"},
                {"seq": 7, "command": "stackTrace"},
                {"seq": 8, "command": "scopes"},
                {"seq": 9, "command": "variables"},
                {"seq": 10, "command": "evaluate", "arguments": {"expression": "X + 3"}},
                {"seq": 11, "command": "next"},
                {"seq": 12, "command": "disconnect"},
            ]
            for request in requests[:-1]:
                self.assertTrue(server.handle(request))
            self.assertFalse(server.handle(requests[-1]))
        messages = self.unpack_messages(output.getvalue())
        responses = [item for item in messages if item["type"] == "response"]
        self.assertEqual(len(responses), 12)
        self.assertTrue(all(response["success"] for response in responses))
        evaluation = next(item for item in responses if item["command"] == "evaluate")
        self.assertEqual(evaluation["body"]["result"], "5")
        stack = next(item for item in responses if item["command"] == "stackTrace")
        self.assertEqual(stack["body"]["stackFrames"][0]["line"], 3)
        self.assertIn("initialized", [item.get("event") for item in messages])
        self.assertIn("stopped", [item.get("event") for item in messages])

    def test_protocol_errors_and_unsupported_command(self) -> None:
        output = BytesIO()
        server = DapServer(BytesIO(), output)
        self.assertTrue(server.handle({"seq": 1, "command": "unknown"}))
        self.assertTrue(server.handle({"seq": 2, "command": "launch", "arguments": {"program": 7}}))
        self.assertTrue(server.handle({
            "seq": 3,
            "command": "setBreakpoints",
            "arguments": {"source": {"path": "/tmp/file.sipl"}, "breakpoints": [{"line": True}]},
        }))
        self.assertTrue(server.handle({"seq": 3, "command": "launch", "arguments": {
            "program": "/does/not/exist.sipl"
        }}))
        responses = self.unpack_messages(output.getvalue())
        self.assertTrue(all(item["type"] == "response" and not item["success"] for item in responses))

    def test_runtime_failure_sends_one_response_and_terminates_with_error(self) -> None:
        programs = [
            ("begin X := Y end", {}, "not defined"),
            ("begin while 1 = 1 do skip end", {"maxSteps": 2}, "step limit"),
        ]
        for source, options, expected in programs:
            with self.subTest(source=source), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "program.sipl"
                path.write_text(source, encoding="utf-8")
                output = BytesIO()
                server = DapServer(BytesIO(), output)
                server.handle({"seq": 1, "command": "launch", "arguments": {
                    "program": str(path), **options,
                }})
                server.handle({"seq": 2, "command": "configurationDone"})
                server.handle({"seq": 3, "command": "continue"})
                messages = self.unpack_messages(output.getvalue())
                replies = [item for item in messages if item.get("request_seq") == 3]
                self.assertEqual(len(replies), 1)
                self.assertTrue(replies[0]["success"])
                error = next(item for item in messages if item.get("event") == "output")
                self.assertIn(expected, error["body"]["output"])
                self.assertEqual(error["body"]["category"], "stderr")
                exited = next(item for item in messages if item.get("event") == "exited")
                self.assertEqual(exited["body"]["exitCode"], 1)
                self.assertEqual(messages[-1]["event"], "terminated")

    def test_read_message_and_framing_errors(self) -> None:
        payload = json.dumps({"type": "request", "command": "disconnect"}).encode()
        encoded = f"Content-Length: {len(payload)}\r\n\r\n".encode() + payload
        server = DapServer(BytesIO(encoded), BytesIO())
        self.assertEqual(server.read_message()["command"], "disconnect")
        with self.assertRaises(ValueError):
            DapServer(BytesIO(b"X-Bad: header\r\n\r\n"), BytesIO()).read_message()
        with self.assertRaises(ValueError):
            DapServer(BytesIO(b"\r\n"), BytesIO()).read_message()
        with self.assertRaises(EOFError):
            DapServer(BytesIO(b"Content-Length: 8\r\n\r\n{}"), BytesIO()).read_message()

    def test_adapter_stdio_process_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "program.sipl"
            path.write_text("begin X := 1 end\n", encoding="utf-8")
            requests = [
                {"seq": 1, "type": "request", "command": "initialize", "arguments": {}},
                {
                    "seq": 2,
                    "type": "request",
                    "command": "launch",
                    "arguments": {"program": str(path)},
                },
                {
                    "seq": 3,
                    "type": "request",
                    "command": "setBreakpoints",
                    "arguments": {
                        "source": {"path": str(path)},
                        "breakpoints": [{"line": 1}],
                    },
                },
                {
                    "seq": 4,
                    "type": "request",
                    "command": "setExceptionBreakpoints",
                    "arguments": {"filters": []},
                },
                {
                    "seq": 5,
                    "type": "request",
                    "command": "configurationDone",
                    "arguments": {},
                },
                {"seq": 6, "type": "request", "command": "disconnect", "arguments": {}},
            ]
            encoded = bytearray()
            for request in requests:
                body = json.dumps(request).encode()
                encoded.extend(f"Content-Length: {len(body)}\r\n\r\n".encode())
                encoded.extend(body)
            process = subprocess.run(
                [sys.executable, "-m", "sipl.debug_adapter"],
                input=bytes(encoded),
                capture_output=True,
                timeout=10,
                check=False,
            )
        self.assertEqual(process.returncode, 0, process.stderr.decode())
        messages = self.unpack_messages(process.stdout)
        responses = [message for message in messages if message["type"] == "response"]
        self.assertEqual(len(responses), 6)
        self.assertTrue(all(response["success"] for response in responses))
        self.assertIn("stopped", [message.get("event") for message in messages])


if __name__ == "__main__":
    unittest.main()
