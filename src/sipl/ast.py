"""Typed SIPL abstract syntax tree and source locations."""

from __future__ import annotations

from dataclasses import dataclass, fields
from typing import TypeAlias


@dataclass(frozen=True, slots=True)
class SourceSpan:
    start_offset: int
    end_offset: int
    start_line: int
    start_column: int
    end_line: int
    end_column: int

    def to_dict(self) -> dict[str, int]:
        return {
            "startOffset": self.start_offset,
            "endOffset": self.end_offset,
            "startLine": self.start_line,
            "startColumn": self.start_column,
            "endLine": self.end_line,
            "endColumn": self.end_column,
        }


@dataclass(frozen=True, slots=True)
class Number:
    value: int
    span: SourceSpan


@dataclass(frozen=True, slots=True)
class Variable:
    name: str
    span: SourceSpan


@dataclass(frozen=True, slots=True)
class UnaryArithmetic:
    operator: str
    operand: Arithmetic
    span: SourceSpan


@dataclass(frozen=True, slots=True)
class BinaryArithmetic:
    operator: str
    left: Arithmetic
    right: Arithmetic
    span: SourceSpan


Arithmetic: TypeAlias = Number | Variable | UnaryArithmetic | BinaryArithmetic


@dataclass(frozen=True, slots=True)
class Comparison:
    operator: str
    left: Arithmetic
    right: Arithmetic
    span: SourceSpan


@dataclass(frozen=True, slots=True)
class NotCondition:
    operand: Condition
    span: SourceSpan


@dataclass(frozen=True, slots=True)
class OrCondition:
    left: Condition
    right: Condition
    span: SourceSpan


Condition: TypeAlias = Comparison | NotCondition | OrCondition


@dataclass(frozen=True, slots=True)
class Assign:
    name: str
    expression: Arithmetic
    span: SourceSpan


@dataclass(frozen=True, slots=True)
class Sequence:
    first: Statement
    second: Statement
    span: SourceSpan


@dataclass(frozen=True, slots=True)
class If:
    condition: Condition
    then_branch: Statement
    else_branch: Statement
    span: SourceSpan


@dataclass(frozen=True, slots=True)
class While:
    condition: Condition
    body: Statement
    span: SourceSpan


@dataclass(frozen=True, slots=True)
class Block:
    statement: Statement
    span: SourceSpan


@dataclass(frozen=True, slots=True)
class Skip:
    span: SourceSpan


Statement: TypeAlias = Assign | Sequence | If | While | Block | Skip


@dataclass(frozen=True, slots=True)
class Program:
    statement: Statement
    span: SourceSpan


def to_data(value: object) -> object:
    """Convert typed AST nodes into stable JSON-compatible data."""
    if isinstance(value, SourceSpan):
        return value.to_dict()
    if hasattr(value, "__dataclass_fields__"):
        result: dict[str, object] = {"type": type(value).__name__}
        for field in fields(value):
            result[field.name] = to_data(getattr(value, field.name))
        return result
    if isinstance(value, tuple):
        return [to_data(item) for item in value]
    return value

