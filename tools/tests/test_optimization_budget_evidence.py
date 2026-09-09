"""New fixed-budget replay with rehashed adversarial receipts; no measured processes."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools.tests import test_optimization_revision_evidence as revision_fixture
from tools.optimization_evidence.attempts import counts, metrics
from tools.optimization_evidence.common import canonical
from tools.optimization_revision_runner import budget
from tools.optimization_revision_evidence import validate_suite
from tools.optimization_revision_evidence import budget as result
from tools.optimization_revision_evidence import budget_builds


class Fixture(revision_fixture.Fixture):
    @staticmethod
    def phase(rows, origin, size):
        if rows:
            return revision_fixture.Fixture.phase(rows, origin, size)
        return {"origin_unix_nanos": str(origin), "clock_anchor_uncertainty_nanos": "10",
                "phase_elapsed_nanos": "0", "counts": counts([]), "batches": []}

    @staticmethod
    def config(arm):
        value = revision_fixture.Fixture.config(arm)
        value["workers"]["control"] = 4
        value["cache"].update(preparations=4, compilerWorkers=2)
        return value

    def __init__(self, root):
        with patch.object(revision_fixture, "plan", side_effect=budget.plan):
            super().__init__(root)
        self.suite.update(schema=budget.SCHEMA, clock_ticks_per_second=100)
        for label, built in self.suite["identity"]["builds"].items():
            name = "tools/optimization_revision_runner/budget.py"
            built["inputs"][name] = self.write(f"builds/{label}/source/{name}", b"common budget model")
            if label == "harness":
                built["command"] = budget.HARNESS_COMMAND
        for name in budget_builds.HARNESS_SOURCES:
            self.suite["identity"]["harness_sources"][name] = self.write("harness-source/" + name, name.encode())
        for run in self.suite["runs"]:
            for index, batch in enumerate(run["batches"]):
                witness = self.read(batch["cache_observation"])
                for side in ("before", "after"):
                    row = self.read(witness[side])
                    state = row["data"]["inventory"]["cacheSummary"]
                    cold = index == 0 and side == "before"
                    state.update(entries="0" if cold else "1", maximumConcurrentPreparations="4",
                                 misses="0" if cold else "1", hits=str(index * 16 + (16 if side == "after" else 0)))
                    witness[side] = self.write(witness[side]["path"], row)
                batch["cache_observation"] = self.write(batch["cache_observation"]["path"], witness)
        built = budget_builds.receipt(self.suite)
        built["identity"] = copy.deepcopy(built["identity"])
        built["artifacts"] = list(self.refs.values())
        self.suite["builds"] = self.write("revision-builds.json", built)
        self.save()

    def read(self, ref):
        return json.loads((self.root / ref["path"]).read_bytes())


class BudgetEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.fixture = Fixture(Path(self.temporary.name))
        self.path = self.fixture.root / "suite.json"

    def test_exact_new_smoke_population_and_unavailable_timers(self):
        value = validate_suite(self.path)
        self.assertEqual((value["schema"], value["status"], value["validated_attempts"], value["validated_processes"]),
                         ("latent.optimization.budget-aggregate.v1", "incomplete", "130", "14"))
        self.assertTrue(value["population_complete"])
        self.assertEqual(len(value["comparisons"]), 4)
        self.assertNotIn("prewarm-echo", [row["id"] for row in value["comparisons"]])
        self.assertEqual(value["timer_observation"]["status"], "unavailable")
        self.assertIsNone(value["target"]["arms"]["candidate"]["attained"])

    def test_plan_arithmetic_and_old_profiles_unchanged(self):
        from tools.optimization_revision_runner.model import plan as previous
        from tools.optimization_runner.plans import cases
        for profile, per_arm in (("smoke", 65), ("full", 1761)):
            selected = budget.plan(profile)
            self.assertEqual(sum(row["client_plan"]["warmup_attempts"] + row["client_plan"]["measured_attempts"]
                                 for row in selected["cases"]), per_arm)
        self.assertEqual(14 * (1761 + 23), 24976)
        self.assertEqual(len(previous("full")["cases"]), 9)
        self.assertEqual(len(cases("full")), 16)
        self.assertNotIn("--bins", budget.HARNESS_RECIPE)
        self.assertNotIn("--bin latentd", budget.HARNESS_RECIPE)

    def test_population_change_cannot_relabel_old_profile(self):
        self.fixture.suite["schema"] = "latent.optimization.revision-suite.v1"
        self.fixture.save()
        with self.assertRaises(ValueError):
            validate_suite(self.path)

    def test_missing_prewarm_rejected(self):
        self.fixture.suite["runs"][0]["batches"].pop(0)
        self.fixture.save()
        with self.assertRaises(ValueError):
            validate_suite(self.path)

    def test_rehashed_measured_miss_cannot_claim_warm_work(self):
        batch = self.fixture.suite["runs"][0]["batches"][2]
        witness = self.fixture.read(batch["cache_observation"])
        after = self.fixture.read(witness["after"])
        after["data"]["inventory"]["cacheSummary"]["misses"] = "2"
        witness["after"] = self.fixture.write(witness["after"]["path"], after)
        self.fixture.replace(batch["cache_observation"], witness)
        self.rebind_build_graph()
        with self.assertRaisesRegex(ValueError, "not-resident"):
            validate_suite(self.path)

    def rebind_build_graph(self):
        # This synthetic fixture includes all source/setup files in its build
        # graph; refresh a deliberately rehashed attack's reference inventory.
        row = self.fixture.suite["builds"]
        built = self.fixture.read(row)
        built["artifacts"] = [value for key, value in self.fixture.refs.items() if key != row["path"]]
        self.fixture.replace(row, built)

    def test_rehashed_build_recipe_crossing_rejected(self):
        self.fixture.suite["identity"]["builds"]["harness"]["command"] = revision_fixture.HARNESS_COMMAND
        self.fixture.save()
        with self.assertRaisesRegex(ValueError, "build-command"):
            validate_suite(self.path)

    def test_rehashed_changed_cpu_resolution_rejected(self):
        self.fixture.suite["clock_ticks_per_second"] = 0
        self.fixture.save()
        with self.assertRaisesRegex(ValueError, "cpu-clock"):
            validate_suite(self.path)

    def test_fast_failures_do_not_become_successful_latency_gain(self):
        raw = [json.loads(line) for line in (self.fixture.root / self.fixture.suite["runs"][0]["batches"][2]["attempts"]["path"]).read_bytes().splitlines()]
        success = [row for row in raw if row["phase"] == "measured"]
        candidate = copy.deepcopy(success)
        for index, row in enumerate(candidate):
            if index < 10:
                row.update(outcome="platform-failure", latency_nanos="10", overshoot_nanos="0")
            else:
                row.update(latency_nanos="3000000", overshoot_nanos="1000000")
        old, new = metrics(success), metrics(candidate)
        self.assertLess(int(float(new["all_dispatched_latency_nanos"]["median"])), int(float(old["all_dispatched_latency_nanos"]["median"])))
        self.assertGreater(int(float(new["successful_response_latency_nanos"]["median"])), int(float(old["successful_response_latency_nanos"]["median"])))
        self.assertEqual(new["budget_successes"], "0")

    def test_target_keeps_all_offers_and_rejects_smoke_qualification(self):
        runs = [{"variant": arm, "repetition": repetition, "status": "passed", "batches": [{"id": "budget-2ms", "measured": {
            "counts": {"attempts": "400"}, "budget_successes": "396" if arm == "candidate" else "395"}}]}
            for repetition in range(1, 8) for arm in ("control", "candidate")]
        value = result.target(runs, "full", True)
        self.assertTrue(value["arms"]["candidate"]["attained"])
        self.assertFalse(value["arms"]["control"]["attained"])
        self.assertEqual(value["arms"]["candidate"]["offers"], "2800")
        self.assertIsNone(result.target(runs, "smoke", True)["arms"]["candidate"]["attained"])

    def test_later_arm_failure_keeps_completed_attempts_and_never_qualifies(self):
        self.fixture.suite.update(status="failed", reason="collection-failed")
        self.fixture.suite["runs"][1].update(status="failed", reason="collector-failed")
        self.fixture.save()
        value = validate_suite(self.path)
        self.assertEqual((value["status"], value["validated_attempts"]), ("failed", "130"))
        self.assertEqual(value["validated_processes"], "14")
        self.assertFalse(value["population_complete"])
        self.assertFalse(value["attempt_count_complete"])
        self.assertEqual(value["runs"][1]["validated_attempts"], "65")
        self.assertEqual(len(value["runs"][1]["batches"]), 5)


if __name__ == "__main__":
    unittest.main()
