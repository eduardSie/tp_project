"""SIPL evaluator with deterministic events and bounded execution."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterator, Mapping

from sipl.ast import (
    Arithmetic,
    Assign,
    BinaryArithmetic,
    Block,
    Comparison,
    Condition,
    If,
    NotCondition,
    Number,
    OrCondition,
    Program,
    Sequence,
    Skip,
    SourceSpan,
    Statement,
    UnaryArithmetic,
    Variable,
    While,
)
from sipl.diagnostics import ExecutionError, StepLimitError
from sipl.parser import parse

State = dict[str, int]


@dataclass(frozen=True, slots=True)
class TraceEvent:
    event: str
    span: SourceSpan | None
    statement: str | None = None
    condition: bool | None = None
    changes: dict[str, dict[str, int | None]] | None = None
    state: dict[str, int] | None = None
    steps: int | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "event": self.event,
            "span": self.span.to_dict() if self.span else None,
            "statement": self.statement,
            "condition": self.condition,
            "changes": self.changes,
            "state": dict(self.state) if self.state is not None else None,
            "steps": self.steps,
        }


@dataclass(frozen=True, slots=True)
class ExecutionResult:
    state: State
    trace: tuple[TraceEvent, ...]
    steps: int

    def to_dict(self) -> dict[str, object]:
        return {
            "state": dict(sorted(self.state.items())),
            "steps": self.steps,
            "trace": [event.to_dict() for event in self.trace],
        }


class _Execution:
    def __init__(self, state: Mapping[str, int], max_steps: int):
        if not isinstance(max_steps, int) or isinstance(max_steps, bool) or max_steps < 1:
            raise ValueError("max_steps must be a positive integer")
        if not isinstance(state, Mapping):
            raise ValueError("initial_state must map variable names to integers")
        if any(
            not isinstance(name, str)
            or not isinstance(value, int)
            or isinstance(value, bool)
            for name, value in state.items()
        ):
            raise ValueError("initial_state must map variable names to integers")
        self.state = dict(state)
        self.max_steps = max_steps
        self.steps = 0

    def eval_arithmetic(self, expression: Arithmetic) -> int:
        if isinstance(expression, Number):
            return expression.value
        if isinstance(expression, Variable):
            try:
                return self.state[expression.name]
            except KeyError as error:
                raise ExecutionError(
                    f"Variable {expression.name!r} is not defined", expression.span
                ) from error
        if isinstance(expression, UnaryArithmetic):
            return -self.eval_arithmetic(expression.operand)
        if isinstance(expression, BinaryArithmetic):
            left = self.eval_arithmetic(expression.left)
            right = self.eval_arithmetic(expression.right)
            if expression.operator == "+":
                return left + right
            if expression.operator == "-":
                return left - right
            return left * right
        raise TypeError(f"Unsupported arithmetic node: {type(expression).__name__}")

    def eval_condition(self, condition: Condition) -> bool:
        if isinstance(condition, Comparison):
            left = self.eval_arithmetic(condition.left)
            right = self.eval_arithmetic(condition.right)
            return left == right if condition.operator == "=" else left > right
        if isinstance(condition, NotCondition):
            return not self.eval_condition(condition.operand)
        if isinstance(condition, OrCondition):
            return self.eval_condition(condition.left) or self.eval_condition(condition.right)
        raise TypeError(f"Unsupported condition node: {type(condition).__name__}")

    def execute_statement(self, statement: Statement) -> Iterator[TraceEvent]:
        self.steps += 1
        if self.steps > self.max_steps:
            raise StepLimitError(self.max_steps, statement.span)
        kind = type(statement).__name__
        yield TraceEvent("BeforeStatement", statement.span, kind, state=dict(self.state))
        if isinstance(statement, Assign):
            old_value = self.state.get(statement.name)
            self.state[statement.name] = self.eval_arithmetic(statement.expression)
            yield TraceEvent(
                "VariableChanged",
                statement.span,
                kind,
                changes={
                    statement.name: {
                        "old": old_value,
                        "new": self.state[statement.name],
                    }
                },
                state=dict(self.state),
                steps=self.steps,
            )
        elif isinstance(statement, Sequence):
            yield from self.execute_statement(statement.first)
            yield from self.execute_statement(statement.second)
        elif isinstance(statement, If):
            outcome = self.eval_condition(statement.condition)
            yield TraceEvent(
                "ConditionEvaluated",
                statement.condition.span,
                kind,
                condition=outcome,
                state=dict(self.state),
                steps=self.steps,
            )
            branch = statement.then_branch if outcome else statement.else_branch
            yield from self.execute_statement(branch)
        elif isinstance(statement, While):
            while True:
                yield TraceEvent(
                    "BeforeCondition",
                    statement.condition.span,
                    kind,
                    state=dict(self.state),
                    steps=self.steps,
                )
                outcome = self.eval_condition(statement.condition)
                yield TraceEvent(
                    "ConditionEvaluated",
                    statement.condition.span,
                    kind,
                    condition=outcome,
                    state=dict(self.state),
                    steps=self.steps,
                )
                if not outcome:
                    break
                yield from self.execute_statement(statement.body)
        elif isinstance(statement, Block):
            yield from self.execute_statement(statement.statement)
        elif not isinstance(statement, Skip):
            raise TypeError(f"Unsupported statement node: {type(statement).__name__}")
        yield TraceEvent(
            "AfterStatement", statement.span, kind, state=dict(self.state), steps=self.steps
        )


def execute(
    program: Program | str,
    initial_state: Mapping[str, int] | None = None,
    *,
    max_steps: int = 100_000,
) -> Iterator[TraceEvent]:
    """Yield execution events while mutating a private copy of the initial state."""
    parsed = parse(program) if isinstance(program, str) else program
    execution = _Execution(initial_state if initial_state is not None else {}, max_steps)
    yield from execution.execute_statement(parsed.statement)
    yield TraceEvent(
        "ExecutionFinished",
        parsed.span,
        state=dict(execution.state),
        steps=execution.steps,
    )


def run(
    program: Program | str,
    initial_state: Mapping[str, int] | None = None,
    *,
    max_steps: int = 100_000,
) -> ExecutionResult:
    events = tuple(execute(program, initial_state, max_steps=max_steps))
    final_state = events[-1].state
    if final_state is None:
        raise RuntimeError("Execution completed without a final state")
    return ExecutionResult(dict(final_state), events, events[-1].steps or 0)
