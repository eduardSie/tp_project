"""SIPL language toolkit."""

from sipl.interpreter import ExecutionResult, execute, run
from sipl.parser import parse, parse_with_tree

__all__ = ["ExecutionResult", "execute", "parse", "parse_with_tree", "run"]
