"""Cross-check benchmark budgets against the real node fixture's wire ceiling."""

from fractions import Fraction
import json
import math
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from optimization_runner.fixtures import node_config
from optimization_runner.plans import plan


def observed_absolute_allowance(unix_nanos: int, budget_millis: int) -> int:
    """Wire deadline rounds up; earliest server wall sample rounds down.

    This rational-time model is independent of the Rust collector's integer
    arithmetic. The server validates the caller's absolute deadline before
    intersecting it with the narrower grpc-timeout.
    """
    now_millis = Fraction(unix_nanos, 1_000_000)
    return math.ceil(now_millis + budget_millis) - math.floor(now_millis)


class OptimizationPlanDeadlineTests(unittest.TestCase):
    def node_maximum(self) -> int:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            configuration = json.loads(node_config(root, root / "data").read_text(encoding="utf-8"))
        return configuration["execution"]["maximumWallTimeMillis"]

    def test_all_selected_budgets_leave_absolute_deadline_quantization_headroom(self):
        maximum = self.node_maximum()
        for profile in ("smoke", "full"):
            for case in plan(profile)["cases"]:
                budget = case["client_plan"]["budget_millis"]
                for fraction in (0, 1, 999_999):
                    with self.subTest(profile=profile, case=case["id"], fraction=fraction):
                        observed = observed_absolute_allowance(1_800_000_000_000_000_000 + fraction, budget)
                        self.assertLessEqual(observed, maximum)

    def test_using_the_exact_ceiling_is_alignment_dependent(self):
        maximum = self.node_maximum()
        aligned = 1_800_000_000_000_000_000
        self.assertEqual(observed_absolute_allowance(aligned, maximum), maximum)
        # The retired 5000ms cache plan fails this boundary despite its nominal
        # budget being within the configured 5000ms server limit.
        self.assertEqual(observed_absolute_allowance(aligned + 1, maximum), maximum + 1)
        self.assertEqual(observed_absolute_allowance(aligned + 999_999, maximum - 1), maximum)


if __name__ == "__main__":
    unittest.main()
