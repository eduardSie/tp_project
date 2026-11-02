"""Command-line interface for parsing, checking and executing SIPL."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from sipl.ast import to_data
from sipl.diagnostics import SipleError
from sipl.interpreter import execute, run
from sipl.parser import parse, parse_with_tree
from sipl.visualization import format_tree_dot, format_tree_text, tree_to_data


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="sipl", description="SIPL language toolkit")
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in ("parse", "check", "run", "trace"):
        subparser = subparsers.add_parser(command)
        subparser.add_argument("file", type=Path)
        subparser.add_argument("--json", action="store_true", help="write JSON output")
        if command in {"run", "trace"}:
            subparser.add_argument(
                "--state",
                default="{}",
                help='initial variable state as JSON, e.g. \'{"X": 3, "Y": 7}\'',
            )
            subparser.add_argument("--max-steps", type=int, default=100_000)
    tree_parser = subparsers.add_parser("tree", help="show the concrete syntax tree")
    tree_parser.add_argument("file", type=Path)
    tree_parser.add_argument("--format", choices=("text", "json", "dot"), default="text")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        source = args.file.read_text(encoding="utf-8")
        if args.command == "tree":
            _, tree = parse_with_tree(source)
            if args.format == "json":
                print(json.dumps(tree_to_data(tree), ensure_ascii=False, indent=2))
            elif args.format == "dot":
                print(format_tree_dot(tree))
            else:
                print(format_tree_text(tree))
            return 0
        program = parse(source)
        if args.command == "parse":
            output = to_data(program)
            print(json.dumps(output, ensure_ascii=False, indent=2) if args.json else "Parse successful")
        elif args.command == "check":
            result = {"valid": True, "diagnostics": []}
            print(json.dumps(result, ensure_ascii=False) if args.json else "Program is valid")
        elif args.command == "run":
            state = json.loads(args.state)
            if not isinstance(state, dict) or any(
                not isinstance(key, str) or not isinstance(value, int) or isinstance(value, bool)
                for key, value in state.items()
            ):
                raise ValueError("--state must be a JSON object mapping names to integers")
            result = run(program, state, max_steps=args.max_steps)
            output = {"state": dict(sorted(result.state.items())), "steps": result.steps}
            print(json.dumps(output, ensure_ascii=False) if args.json else _format_state(result.state))
        else:
            state = json.loads(args.state)
            if not isinstance(state, dict) or any(
                not isinstance(key, str) or not isinstance(value, int) or isinstance(value, bool)
                for key, value in state.items()
            ):
                raise ValueError("--state must be a JSON object mapping names to integers")
            events = list(execute(program, state, max_steps=args.max_steps))
            if args.json:
                print(json.dumps({"trace": [event.to_dict() for event in events]}, ensure_ascii=False))
            else:
                for event in events:
                    print(
                        f"{event.event:20} line "
                        f"{event.span.start_line if event.span else '-'} "
                        f"{json.dumps(event.state, sort_keys=True) if event.state is not None else ''}"
                    )
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError, SipleError) as error:
        payload = error.to_dict() if isinstance(error, SipleError) else {"message": str(error)}
        if getattr(args, "json", False) or (
            args.command == "tree" and args.format == "json"
        ):
            print(json.dumps({"error": payload}, ensure_ascii=False), file=sys.stderr)
        else:
            print(f"sipl: {error}", file=sys.stderr)
        return 2
    return 0


def _format_state(state: dict[str, int]) -> str:
    return json.dumps(dict(sorted(state.items())), ensure_ascii=False)


if __name__ == "__main__":
    raise SystemExit(main())
