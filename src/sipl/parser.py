"""Lexer and recursive-descent parser for the course SIPL grammar."""

from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass
from functools import wraps
import re
from typing import Callable, Protocol, TypeVar

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
from sipl.diagnostics import LexError, ParseError


@dataclass(frozen=True, slots=True)
class Token:
    kind: str
    value: str
    span: SourceSpan


@dataclass(frozen=True, slots=True)
class ParseTreeNode:
    symbol: str
    span: SourceSpan
    children: tuple[ParseTreeNode, ...] = ()
    lexeme: str | None = None


@dataclass(frozen=True, slots=True)
class ParseTree:
    source: str
    root: ParseTreeNode


class _Spanned(Protocol):
    @property
    def span(self) -> SourceSpan: ...


_Node = TypeVar("_Node", bound=_Spanned)


def _production(
    symbol: str,
) -> Callable[[Callable[[Parser], _Node]], Callable[[Parser], _Node]]:
    def decorate(method: Callable[[Parser], _Node]) -> Callable[[Parser], _Node]:
        @wraps(method)
        def wrapped(parser: Parser) -> _Node:
            stack = parser._tree_stack
            if stack is None:
                return method(parser)
            children: list[ParseTreeNode] = []
            stack.append(children)
            try:
                result = method(parser)
            finally:
                stack.pop()
            span = (
                parser.join(children[0].span, children[-1].span)
                if children
                else result.span
            )
            node = ParseTreeNode(symbol, span, tuple(children))
            if stack:
                stack[-1].append(node)
            else:
                parser._tree = node
            return result

        return wrapped

    return decorate


_TOKEN_RE = re.compile(
    r"(?P<SPACE>\s+)"
    r"|(?P<NUMBER>[0-9]+)"
    r"|(?P<IDENT>[A-Za-z_][A-Za-z_0-9]*)"
    r"|(?P<ASSIGN>:=)"
    r"|(?P<OR>[|∨])"
    r"|(?P<NOT>¬)"
    r"|(?P<OP>[()+\-*=><;])"
)
_KEYWORDS = {"begin", "end", "if", "then", "else", "while", "do", "skip"}


def _span(source: str, start: int, end: int, line_starts: list[int]) -> SourceSpan:
    start_line_index = bisect_right(line_starts, start) - 1
    end_line_index = bisect_right(line_starts, end) - 1
    return SourceSpan(
        start,
        end,
        start_line_index + 1,
        start - line_starts[start_line_index] + 1,
        end_line_index + 1,
        end - line_starts[end_line_index] + 1,
    )


def tokenize(source: str) -> list[Token]:
    tokens: list[Token] = []
    position = 0
    line_starts = [0]
    line_starts.extend(index + 1 for index, char in enumerate(source) if char == "\n")
    while position < len(source):
        match = _TOKEN_RE.match(source, position)
        if match is None:
            raise LexError(
                f"Unexpected character {source[position]!r}",
                _span(source, position, position + 1, line_starts),
            )
        kind = match.lastgroup
        value = match.group()
        start, end = match.span()
        position = end
        if kind == "SPACE":
            continue
        if kind == "IDENT" and value in _KEYWORDS:
            kind = value.upper()
        elif kind == "IDENT":
            kind = "IDENT"
        elif kind == "OP":
            kind = value
        tokens.append(Token(kind or "", value, _span(source, start, end, line_starts)))
    eof = _span(source, len(source), len(source), line_starts)
    tokens.append(Token("EOF", "", eof))
    return tokens


class Parser:
    def __init__(self, source: str, *, capture_tree: bool = False):
        self.tokens = tokenize(source)
        self.index = 0
        self._tree_stack: list[list[ParseTreeNode]] | None = [] if capture_tree else None
        self._tree: ParseTreeNode | None = None

    @property
    def current(self) -> Token:
        return self.tokens[self.index]

    def take(self, kind: str) -> Token:
        token = self.current
        if token.kind != kind:
            expected = "end of input" if kind == "EOF" else repr(kind)
            found = "end of input" if token.kind == "EOF" else repr(token.value)
            raise ParseError(f"Expected {expected}, found {found}", token.span)
        self.index += 1
        if self._tree_stack is not None:
            self._tree_stack[-1].append(
                ParseTreeNode(token.kind, token.span, lexeme=token.value)
            )
        return token

    @_production("program")
    def parse_program(self) -> Program:
        start = self.take("BEGIN")
        statement = self.parse_statement()
        end = self.take("END")
        self.take("EOF")
        return Program(statement, self.join(start.span, end.span))

    @_production("statement")
    def parse_statement(self) -> Statement:
        statement = self.parse_single_statement()
        while self.current.kind == ";":
            self.take(";")
            next_statement = self.parse_single_statement()
            statement = Sequence(
                statement, next_statement, self.join(statement.span, next_statement.span)
            )
        return statement

    @_production("simple_statement")
    def parse_single_statement(self) -> Statement:
        token = self.current
        if token.kind == "IDENT":
            name = self.take("IDENT")
            self.take("ASSIGN")
            expression = self.parse_arithmetic()
            return Assign(name.value, expression, self.join(name.span, expression.span))
        if token.kind == "SKIP":
            return Skip(self.take("SKIP").span)
        if token.kind == "BEGIN":
            start = self.take("BEGIN")
            statement = self.parse_statement()
            end = self.take("END")
            return Block(statement, self.join(start.span, end.span))
        if token.kind == "IF":
            start = self.take("IF")
            condition = self.parse_condition()
            self.take("THEN")
            then_branch = self.parse_single_statement()
            self.take("ELSE")
            else_branch = self.parse_single_statement()
            return If(
                condition,
                then_branch,
                else_branch,
                self.join(start.span, else_branch.span),
            )
        if token.kind == "WHILE":
            start = self.take("WHILE")
            condition = self.parse_condition()
            self.take("DO")
            body = self.parse_single_statement()
            return While(condition, body, self.join(start.span, body.span))
        raise ParseError(f"Expected a statement, found {token.value!r}", token.span)

    @_production("arithmetic")
    def parse_arithmetic(self) -> Arithmetic:
        return self.parse_additive()

    @_production("additive")
    def parse_additive(self) -> Arithmetic:
        expression = self.parse_multiplicative()
        while self.current.kind in {"+", "-"}:
            operator = self.take(self.current.kind)
            right = self.parse_multiplicative()
            expression = BinaryArithmetic(
                operator.value, expression, right, self.join(expression.span, right.span)
            )
        return expression

    @_production("multiplicative")
    def parse_multiplicative(self) -> Arithmetic:
        expression = self.parse_arithmetic_atom()
        while self.current.kind == "*":
            operator = self.take("*")
            right = self.parse_arithmetic_atom()
            expression = BinaryArithmetic(
                operator.value, expression, right, self.join(expression.span, right.span)
            )
        return expression

    @_production("atom")
    def parse_arithmetic_atom(self) -> Arithmetic:
        token = self.current
        if token.kind == "-":
            operator = self.take("-")
            operand = self.parse_arithmetic_atom()
            return UnaryArithmetic("-", operand, self.join(operator.span, operand.span))
        if token.kind == "NUMBER":
            number = self.take("NUMBER")
            return Number(int(number.value), number.span)
        if token.kind == "IDENT":
            variable = self.take("IDENT")
            return Variable(variable.value, variable.span)
        if token.kind == "(":
            start = self.take("(")
            expression = self.parse_arithmetic()
            end = self.take(")")
            return self.respan(expression, self.join(start.span, end.span))
        raise ParseError("Expected an arithmetic expression", token.span)

    @_production("condition")
    def parse_condition(self) -> Condition:
        return self.parse_disjunction()

    @_production("disjunction")
    def parse_disjunction(self) -> Condition:
        condition = self.parse_boolean_atom()
        while self.current.kind == "OR":
            self.take("OR")
            right = self.parse_boolean_atom()
            condition = OrCondition(
                condition, right, self.join(condition.span, right.span)
            )
        return condition

    @_production("boolean_atom")
    def parse_boolean_atom(self) -> Condition:
        token = self.current
        if token.kind == "NOT":
            start = self.take("NOT")
            operand = self.parse_boolean_atom()
            return NotCondition(operand, self.join(start.span, operand.span))
        if token.kind == "(":
            saved_index = self.index
            child_count = (
                len(self._tree_stack[-1]) if self._tree_stack is not None else 0
            )
            start = self.take("(")
            try:
                condition = self.parse_condition()
                end = self.take(")")
                return self.respan(condition, self.join(start.span, end.span))
            except ParseError:
                self.index = saved_index
                if self._tree_stack is not None:
                    del self._tree_stack[-1][child_count:]
        left = self.parse_arithmetic()
        operator = self.current
        if operator.kind not in {"=", ">"}:
            raise ParseError("Expected '=' or '>' in a condition", operator.span)
        self.take(operator.kind)
        right = self.parse_arithmetic()
        return Comparison(operator.value, left, right, self.join(left.span, right.span))

    def join(self, first: SourceSpan, last: SourceSpan) -> SourceSpan:
        return SourceSpan(
            first.start_offset,
            last.end_offset,
            first.start_line,
            first.start_column,
            last.end_line,
            last.end_column,
        )

    @staticmethod
    def respan(node: Arithmetic | Condition, span: SourceSpan):
        from dataclasses import replace

        return replace(node, span=span)


def parse(source: str) -> Program:
    """Parse one complete SIPL program into the toolkit's typed AST."""
    return Parser(source).parse_program()


def parse_with_tree(source: str) -> tuple[Program, ParseTree]:
    """Parse once and return both the AST and the concrete derivation tree."""
    parser = Parser(source, capture_tree=True)
    program = parser.parse_program()
    if parser._tree is None:
        raise RuntimeError("Parser completed without producing a derivation tree")
    return program, ParseTree(source, parser._tree)
