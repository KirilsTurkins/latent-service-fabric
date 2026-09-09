"""Actual replay of a fully rehashed #119 graph, with no guest or process work."""
import copy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools import run_optimization_revision_benchmarks as cli
from tools.optimization_evidence.common import canonical
from tools.optimization_revision_runner import budget, recovery
from tools.optimization_revision_evidence import validate_suite, recovery_builds
from tools.tests.test_optimization_budget_evidence import Fixture as BudgetFixture
from tools.tests.test_phase1_cleanup_shutdown import cleanup


class Fixture(BudgetFixture):
    def __init__(self, root):
        with patch.object(budget, "plan", side_effect=recovery.plan):
            super().__init__(root)
        self.suite["schema"] = recovery.SCHEMA
        for label, built in self.suite["identity"]["builds"].items():
            name = "tools/optimization_revision_runner/recovery.py"
            built["inputs"][name] = self.write(f"builds/{label}/source/{name}", b"common recovery model")
        for name in recovery_builds.HARNESS_SOURCES:
            self.suite["identity"]["harness_sources"][name] = self.write("harness-source/" + name, name.encode())
        candidate = self.suite["runs"][1]
        for name in ("candidate/seed-cleanup.json", candidate["cleanup"]["path"]):
            row = self.refs[name]
            value = self.read(row)
            value["server_shutdown"]["report"]["cleanup"] = cleanup() | {"handoffs": 0, "completed": 0}
            self.replace(row, value)
        self.rebind()

    def rebind(self):
        row = self.suite["builds"]
        value = recovery_builds.receipt(self.suite)
        value["identity"] = copy.deepcopy(value["identity"])
        value["artifacts"] = [item for key, item in self.refs.items() if key != row["path"]]
        self.replace(row, value)
        self.save()


class TransportWarmTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.fixture = Fixture(Path(self.temporary.name))
        self.path = self.fixture.root / "suite.json"

    def test_exact_smoke_and_full_populations_preserve_original_client(self):
        from tools.optimization_runner.plans import cases
        for profile, expected in (("smoke", 17), ("full", 441)):
            value = recovery.plan(profile)
            self.assertEqual(value["cases"][1], cases(profile)[0])
            self.assertEqual(sum(item["client_plan"]["warmup_attempts"] + item["client_plan"]["measured_attempts"]
                                 for item in value["cases"]), expected)
        self.assertEqual(14 * 441, 6174)
        self.assertEqual(len(budget.plan("full")["cases"]), 5)
        value = validate_suite(self.path)
        self.assertEqual((value["schema"], value["status"], value["validated_attempts"], value["validated_processes"]),
                         ("latent.optimization.transport-warm-aggregate.v1", "incomplete", "34", "8"))
        self.assertTrue(value["population_complete"])
        self.assertEqual([item["id"] for item in value["comparisons"]], ["warm-echo"])
        self.assertEqual(len(value["comparisons"][0]["paired_differences_nanos"]), 6)
        self.assertIsNone(value["runs"][0]["transport_cleanup"])
        self.assertTrue(value["runs"][1]["transport_cleanup"]["driverJoined"])
        self.assertEqual(value["timer_observation"]["status"], "unavailable")

    def test_rehashed_candidate_cleanup_removal_cannot_become_historical_absence(self):
        for name in ("candidate/seed-cleanup.json", "candidate/cleanup.json"):
            with self.subTest(name=name):
                row = self.fixture.refs[name]
                original = self.fixture.read(row)
                value = copy.deepcopy(original)
                del value["server_shutdown"]["report"]["cleanup"]
                self.fixture.replace(row, value)
                self.fixture.rebind()
                with self.assertRaisesRegex(ValueError, "cleanup-presence"):
                    validate_suite(self.path)
                self.fixture.replace(row, original)
                self.fixture.rebind()

    def test_false_join_or_zeroed_handoff_counter_cannot_qualify(self):
        row = self.fixture.suite["runs"][1]["cleanup"]
        original = self.fixture.read(row)
        for change in ({"driverJoined": False}, {"handoffs": 1}, {"running": 1, "handoffs": 1}):
            with self.subTest(change=change):
                value = copy.deepcopy(original)
                value["server_shutdown"]["report"]["cleanup"].update(change)
                self.fixture.replace(row, value)
                self.fixture.rebind()
                with self.assertRaises(ValueError):
                    validate_suite(self.path)

    def test_control_cannot_claim_candidate_observer_support(self):
        row = self.fixture.suite["runs"][0]["cleanup"]
        value = self.fixture.read(row)
        value["server_shutdown"]["report"]["cleanup"] = cleanup()
        self.fixture.replace(row, value)
        self.fixture.rebind()
        with self.assertRaisesRegex(ValueError, "cleanup-presence"):
            validate_suite(self.path)

    def test_exact_mode_build_receipt_and_shared_model_cannot_cross(self):
        row = self.fixture.suite["builds"]
        value = self.fixture.read(row)
        value["schema"] = budget.BUILD_SCHEMA
        self.fixture.replace(row, value)
        self.fixture.save()
        with self.assertRaisesRegex(ValueError, "build-schema"):
            validate_suite(self.path)

    def test_missing_warm_offer_or_pair_never_qualifies(self):
        self.fixture.suite["runs"].pop()
        self.fixture.save()
        with self.assertRaisesRegex(ValueError, "missing-pair"):
            validate_suite(self.path)

    def test_failed_arm_retains_complete_attempts(self):
        self.fixture.suite.update(status="failed", reason="collection-failed")
        self.fixture.suite["runs"][1].update(status="failed", reason="collector-failed")
        self.fixture.save()
        value = validate_suite(self.path)
        self.assertEqual((value["status"], value["validated_attempts"]), ("failed", "34"))
        self.assertFalse(value["population_complete"])
        self.assertEqual(value["runs"][1]["validated_attempts"], "17")

    def test_cli_explicit_recovery_prebuilt_dispatch(self):
        with patch.object(cli, "execute", return_value=0) as execute:
            self.assertEqual(cli.main(["--experiment", "recovery", "--profile", "full",
                                       "--builds", "fresh/revision-builds.json"]), 0)
        self.assertEqual(execute.call_args.args[0].experiment, "recovery")


if __name__ == "__main__":
    unittest.main()
