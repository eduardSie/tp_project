from __future__ import annotations

import unittest

from sipl.diagnostics import ExecutionError, StepLimitError
from sipl.interpreter import execute, run


class InterpreterTests(unittest.TestCase):
    def test_assignment_sequence_and_initial_state_copy(self) -> None:
        original = {"X": 4}
        result = run("begin Y := X * 2; X := Y + 1 end", original)
        self.assertEqual(result.state, {"X": 9, "Y": 8})
        self.assertEqual(original, {"X": 4})

    def test_if_then_else(self) -> None:
        self.assertEqual(
            run("begin if X > 0 then Y := 1 else Y := 2 end", {"X": -1}).state["Y"],
            2,
        )

    def test_loop_and_trace_events(self) -> None:
        result = run(
            "begin R := 1; while Y > 0 do begin R := R * X; Y := Y - 1 end end",
            {"X": 3, "Y": 4},
        )
        self.assertEqual(result.state, {"X": 3, "Y": 0, "R": 81})
        self.assertIn("BeforeStatement", {event.event for event in result.trace})
        self.assertIn("AfterStatement", {event.event for event in result.trace})
        self.assertIn("ConditionEvaluated", {event.event for event in result.trace})
        self.assertEqual(result.trace[-1].event, "ExecutionFinished")

    def test_loop_trace_marks_each_condition_before_it_is_evaluated(self) -> None:
        result = run("begin while X > 0 do X := X - 1 end", {"X": 1})
        checks = [
            event for event in result.trace
            if event.event in {"BeforeCondition", "ConditionEvaluated"}
        ]
        self.assertEqual(
            [event.event for event in checks],
            ["BeforeCondition", "ConditionEvaluated", "BeforeCondition", "ConditionEvaluated"],
        )
        self.assertEqual([event.state["X"] for event in checks], [1, 1, 0, 0])
        self.assertEqual([event.condition for event in checks], [None, True, None, False])

    def test_not_and_or_conditions(self) -> None:
        result = run(
            "begin if ¬(X > 1) ∨ Y = 3 then R := 7 else R := 8 end",
            {"X": 1, "Y": 0},
        )
        self.assertEqual(result.state["R"], 7)

    def test_missing_variable_is_an_explicit_error(self) -> None:
        with self.assertRaisesRegex(ExecutionError, "not defined"):
            run("begin X := Y + 1 end")

    def test_step_limit_stops_nonterminating_loop(self) -> None:
        with self.assertRaises(StepLimitError):
            run("begin while X = 0 do skip end", {"X": 0}, max_steps=5)

    def test_api_rejects_invalid_initial_state_and_step_limit(self) -> None:
        with self.assertRaisesRegex(ValueError, "initial_state"):
            run("begin skip end", {"X": True})
        with self.assertRaisesRegex(ValueError, "initial_state"):
            run("begin skip end", ["not", "a", "mapping"])
        with self.assertRaisesRegex(ValueError, "initial_state"):
            run("begin skip end", [])
        with self.assertRaisesRegex(ValueError, "max_steps"):
            run("begin skip end", max_steps=True)

    def test_variable_changed_event_contains_old_and_new_values(self) -> None:
        events = list(execute("begin X := X + 1 end", {"X": 2}))
        change = next(event for event in events if event.event == "VariableChanged")
        self.assertEqual(change.changes, {"X": {"old": 2, "new": 3}})

    def test_skip_and_empty_initial_state(self) -> None:
        result = run("begin skip end")
        self.assertEqual(result.state, {})
        self.assertEqual(result.steps, 1)


if __name__ == "__main__":
    unittest.main()
