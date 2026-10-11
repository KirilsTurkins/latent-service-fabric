"""Keep typed actual resource observations distinct from absent or deadline data."""
import unittest

from tools.java_http_composition.resource_diagnostics import terminal_observation


class JavaResourceDiagnosticTests(unittest.TestCase):
    def test_queue_deadline_unknown_and_nonterminal_observations_cannot_claim_resource_failure(self):
        for stages, reason in (((1, 2), 9), ((5,), 11)):
            self.assertEqual(terminal_observation({"diagnostic": None}, stages=stages, reason=reason), "unavailable")
            for stage in range(0, 8):
                for actual_reason in (9, 11, 13, 14, 999):
                    for terminal in (False, True, None):
                        node = {"diagnostic": {"stage": stage, "reason": actual_reason}, "diagnosticIsTerminal": terminal}
                        expected = "observed" if stage in stages and actual_reason == reason and terminal is True else "unexpected"
                        self.assertEqual(terminal_observation(node, stages=stages, reason=reason), expected)
            for diagnostic in ({"stage": str(stages[0]), "reason": reason},
                               {"stage": stages[0], "reason": str(reason)},
                               {"stage": True, "reason": reason}, {"stage": stages[0], "reason": True}):
                self.assertEqual(terminal_observation({"diagnostic": diagnostic, "diagnosticIsTerminal": True},
                                 stages=stages, reason=reason), "unexpected")


if __name__ == "__main__":
    unittest.main()
