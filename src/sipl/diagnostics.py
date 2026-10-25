"""User-facing lexical, syntax and execution errors."""

from __future__ import annotations

from dataclasses import dataclass

from sipl.ast import SourceSpan


@dataclass(slots=True)
class SipleError(Exception):
    message: str
    span: SourceSpan | None = None
    code: str = "SIPL_ERROR"

    def __str__(self) -> str:
        if self.span is None:
            return self.message
        return (
            f"{self.message} "
            f"(line {self.span.start_line}, column {self.span.start_column})"
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "code": self.code,
            "message": self.message,
            "span": self.span.to_dict() if self.span else None,
        }


class LexError(SipleError):
    def __init__(self, message: str, span: SourceSpan):
        super().__init__(message, span, "LEX_ERROR")


class ParseError(SipleError):
    def __init__(self, message: str, span: SourceSpan):
        super().__init__(message, span, "PARSE_ERROR")


class ExecutionError(SipleError):
    def __init__(self, message: str, span: SourceSpan | None = None):
        super().__init__(message, span, "EXECUTION_ERROR")


class StepLimitError(ExecutionError):
    def __init__(self, limit: int, span: SourceSpan):
        super().__init__(f"Execution exceeded the step limit ({limit})", span)
        self.code = "STEP_LIMIT_EXCEEDED"

