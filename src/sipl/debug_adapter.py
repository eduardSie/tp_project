"""Minimal Debug Adapter Protocol server for VS Code."""

from __future__ import annotations

import json
from pathlib import Path
import sys
from typing import BinaryIO, Iterator

from sipl.ast import Assign, Block, If, Sequence, Skip, SourceSpan, Statement, While
from sipl.diagnostics import SipleError
from sipl.interpreter import TraceEvent, execute, run
from sipl.parser import parse


class DebugSession:
    def __init__(self) -> None:
        self.events: Iterator[TraceEvent] | None = None
        self.breakpoints: set[int] = set()
        self.source_path: str | None = None
        self.current_span: SourceSpan | None = None
        self.state: dict[str, int] = {}
        self.finished = False
        self.executable_lines: set[int] = set()
        self.loop_condition_spans: dict[tuple[int, int], SourceSpan] = {}

    def launch(self, path: str, initial_state: dict[str, int], max_steps: int) -> None:
        source_path = Path(path).resolve()
        source = source_path.read_text(encoding="utf-8")
        program = parse(source)
        self.events = iter(execute(program, initial_state, max_steps=max_steps))
        self.source_path = str(source_path)
        self.executable_lines = _statement_lines(program.statement)
        self.loop_condition_spans = _while_condition_spans(program.statement)
        self.current_span = None
        self.state = dict(initial_state)
        self.finished = False

    def set_breakpoints(self, lines: list[int]) -> list[dict[str, object]]:
        self.breakpoints = {line for line in lines if line > 0}
        return [
            {
                "id": index + 1,
                "verified": line in self.executable_lines,
                "line": line,
            }
            for index, line in enumerate(lines)
        ]

    def advance(self, *, step: bool) -> tuple[str, TraceEvent | None]:
        if self.events is None:
            raise RuntimeError("Launch the SIPL program before resuming")
        if self.finished:
            return "terminated", None
        for event in self.events:
            if event.state is not None:
                self.state = dict(event.state)
            if event.event == "BeforeStatement":
                self.current_span = event.span
                executable = event.statement not in {"Sequence", "Block", "While"}
                if executable and (
                    step
                    or (event.span is not None and event.span.start_line in self.breakpoints)
                ):
                    return "stopped", event
            elif event.event == "BeforeCondition" and event.statement == "While":
                loop_span = (
                    self.loop_condition_spans.get((event.span.start_offset, event.span.end_offset))
                    if event.span is not None
                    else None
                )
                if loop_span is not None:
                    self.current_span = loop_span
                    if step or loop_span.start_line in self.breakpoints:
                        return "stopped", event
            elif event.event == "ExecutionFinished":
                self.finished = True
                self.current_span = event.span
                return "terminated", event
        self.finished = True
        return "terminated", None


class DapServer:
    def __init__(self, source: BinaryIO, destination: BinaryIO) -> None:
        self.source = source
        self.destination = destination
        self.session = DebugSession()
        self.sequence = 1

    def read_message(self) -> dict[str, object] | None:
        headers: dict[str, str] = {}
        while True:
            line = self.source.readline()
            if not line:
                return None
            if line in {b"\r\n", b"\n"}:
                break
            key, separator, value = line.decode("ascii").partition(":")
            if not separator:
                raise ValueError("Malformed DAP header")
            headers[key.lower()] = value.strip()
        if "content-length" not in headers:
            raise ValueError("DAP message is missing Content-Length")
        length = int(headers["content-length"])
        payload = self.source.read(length)
        if len(payload) != length:
            raise EOFError("Incomplete DAP message")
        message = json.loads(payload.decode("utf-8"))
        if not isinstance(message, dict):
            raise ValueError("DAP message must be a JSON object")
        return message

    def send(self, message: dict[str, object]) -> None:
        body = json.dumps(message, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        header = f"Content-Length: {len(body)}\r\n\r\n".encode("ascii")
        self.destination.write(header + body)
        self.destination.flush()

    def respond(
        self, request: dict[str, object], *, body: dict[str, object] | None = None,
        success: bool = True, message: str | None = None,
    ) -> None:
        response: dict[str, object] = {
            "seq": self.sequence,
            "type": "response",
            "request_seq": request.get("seq", 0),
            "command": request.get("command", ""),
            "success": success,
        }
        self.sequence += 1
        if body is not None:
            response["body"] = body
        if message is not None:
            response["message"] = message
        self.send(response)

    def event(self, name: str, body: dict[str, object] | None = None) -> None:
        payload: dict[str, object] = {
            "seq": self.sequence,
            "type": "event",
            "event": name,
        }
        self.sequence += 1
        if body is not None:
            payload["body"] = body
        self.send(payload)

    def handle(self, request: dict[str, object]) -> bool:
        command = request.get("command")
        arguments = request.get("arguments") or {}
        if not isinstance(arguments, dict):
            self.respond(request, success=False, message="arguments must be an object")
            return True
        try:
            if command in {"configurationDone", "next", "stepIn", "continue"} and (
                self.session.events is None or self.session.finished
            ):
                raise RuntimeError("No active SIPL debug session")
            if command == "initialize":
                self.respond(
                    request,
                    body={
                        "supportsConfigurationDoneRequest": True,
                        "supportsEvaluateForHovers": True,
                        "supportsStepIn": True,
                        "supportsTerminateRequest": True,
                    },
                )
            elif command == "launch":
                path = arguments.get("program")
                if not isinstance(path, str):
                    raise ValueError("launch requires a 'program' path")
                initial = arguments.get("initialState", {})
                max_steps = arguments.get("maxSteps", 100_000)
                if not isinstance(initial, dict) or any(
                    not isinstance(key, str)
                    or not isinstance(value, int)
                    or isinstance(value, bool)
                    for key, value in initial.items()
                ):
                    raise ValueError("initialState must map variable names to integers")
                if not isinstance(max_steps, int) or isinstance(max_steps, bool) or max_steps < 1:
                    raise ValueError("maxSteps must be a positive integer")
                self.session.launch(path, initial, max_steps)
                self.respond(request)
                self.event("initialized")
            elif command == "setBreakpoints":
                source = arguments.get("source", {})
                if not isinstance(source, dict):
                    raise ValueError("source must be an object")
                path = source.get("path")
                if not isinstance(path, str) or not path:
                    raise ValueError("source.path must be a non-empty string")
                if self.session.source_path and str(Path(path).resolve()) != self.session.source_path:
                    raise ValueError("Breakpoints must target the launched SIPL source")
                requested = arguments.get("breakpoints", [])
                if not isinstance(requested, list):
                    raise ValueError("breakpoints must be an array")
                if any(
                    not isinstance(item, dict)
                    or not isinstance(item.get("line"), int)
                    or isinstance(item.get("line"), bool)
                    or item["line"] < 1
                    for item in requested
                ):
                    raise ValueError("each breakpoint must have a positive integer line")
                lines = [item["line"] for item in requested]
                self.respond(request, body={"breakpoints": self.session.set_breakpoints(lines)})
            elif command == "setExceptionBreakpoints":
                self.respond(request)
            elif command == "configurationDone":
                self.respond(request)
                self.event("thread", {"reason": "started", "threadId": 1})
                self._resume(step=True, stop_reason="entry")
            elif command in {"next", "stepIn"}:
                self.respond(request)
                self.event("continued", {"threadId": 1, "allThreadsContinued": True})
                self._resume(step=True, stop_reason="step")
            elif command == "continue":
                self.respond(request, body={"allThreadsContinued": True})
                self.event("continued", {"threadId": 1, "allThreadsContinued": True})
                self._resume(step=False, stop_reason="breakpoint")
            elif command == "threads":
                self.respond(request, body={"threads": [{"id": 1, "name": "SIPL"}]})
            elif command == "stackTrace":
                span = self.session.current_span
                frames: list[dict[str, object]] = []
                if span is not None:
                    frames.append(
                        {
                            "id": 1,
                            "name": "SIPL program",
                            "line": span.start_line,
                            "column": span.start_column,
                            "source": {
                                "name": Path(self.session.source_path or "program.sipl").name,
                                "path": self.session.source_path,
                            },
                        }
                    )
                self.respond(request, body={"stackFrames": frames, "totalFrames": len(frames)})
            elif command == "scopes":
                self.respond(
                    request,
                    body={
                        "scopes": [
                            {"name": "Variables", "variablesReference": 1, "expensive": False}
                        ]
                    },
                )
            elif command == "variables":
                variables = [
                    {"name": name, "value": str(value), "type": "integer", "variablesReference": 0}
                    for name, value in sorted(self.session.state.items())
                ]
                self.respond(request, body={"variables": variables})
            elif command == "evaluate":
                expression = arguments.get("expression")
                if not isinstance(expression, str):
                    raise ValueError("evaluate requires an expression")
                result = run(
                    f"begin __sipl_debug_result := ({expression}) end",
                    self.session.state,
                ).state["__sipl_debug_result"]
                self.respond(
                    request,
                    body={"result": str(result), "type": "integer", "variablesReference": 0},
                )
            elif command in {"disconnect", "terminate"}:
                self.respond(request)
                self.event("terminated")
                return False
            else:
                self.respond(request, success=False, message=f"Unsupported DAP command: {command}")
        except (OSError, ValueError, SipleError, RuntimeError) as error:
            self.respond(request, success=False, message=str(error))
        return True

    def _resume(self, *, step: bool, stop_reason: str) -> None:
        try:
            reason, _ = self.session.advance(step=step)
        except SipleError as error:
            self.session.finished = True
            output: dict[str, object] = {"category": "stderr", "output": f"{error}\n"}
            if error.span is not None and self.session.source_path is not None:
                output["source"] = {
                    "name": Path(self.session.source_path).name,
                    "path": self.session.source_path,
                }
                output["line"] = error.span.start_line
                output["column"] = error.span.start_column
            self.event("output", output)
            self.event("exited", {"exitCode": 1})
            self.event("terminated")
            return
        self._report_stop(reason, stop_reason)

    def _report_stop(self, reason: str, stop_reason: str) -> None:
        if reason == "stopped":
            self.event(
                "stopped",
                {"reason": stop_reason, "threadId": 1, "allThreadsStopped": True},
            )
        else:
            self.event("exited", {"exitCode": 0})
            self.event("terminated")

    def serve(self) -> None:
        while True:
            request = self.read_message()
            if request is None or not self.handle(request):
                return


def main() -> int:
    try:
        DapServer(sys.stdin.buffer, sys.stdout.buffer).serve()
    except (OSError, EOFError, ValueError, json.JSONDecodeError) as error:
        print(f"sipl-debug-adapter: {error}", file=sys.stderr)
        return 2
    return 0


def _statement_lines(statement: Statement) -> set[int]:
    if isinstance(statement, Assign | If | While | Skip):
        lines = {statement.span.start_line}
        if isinstance(statement, If):
            lines.update(_statement_lines(statement.then_branch))
            lines.update(_statement_lines(statement.else_branch))
        elif isinstance(statement, While):
            lines.update(_statement_lines(statement.body))
        return lines
    if isinstance(statement, Sequence):
        return _statement_lines(statement.first) | _statement_lines(statement.second)
    if isinstance(statement, Block):
        return _statement_lines(statement.statement)
    raise TypeError(f"Unsupported statement node: {type(statement).__name__}")


def _while_condition_spans(statement: Statement) -> dict[tuple[int, int], SourceSpan]:
    if isinstance(statement, While):
        spans = _while_condition_spans(statement.body)
        spans[(statement.condition.span.start_offset, statement.condition.span.end_offset)] = (
            statement.span
        )
        return spans
    if isinstance(statement, If):
        return _while_condition_spans(statement.then_branch) | _while_condition_spans(
            statement.else_branch
        )
    if isinstance(statement, Sequence):
        return _while_condition_spans(statement.first) | _while_condition_spans(statement.second)
    if isinstance(statement, Block):
        return _while_condition_spans(statement.statement)
    if isinstance(statement, Assign | Skip):
        return {}
    raise TypeError(f"Unsupported statement node: {type(statement).__name__}")


if __name__ == "__main__":
    raise SystemExit(main())
