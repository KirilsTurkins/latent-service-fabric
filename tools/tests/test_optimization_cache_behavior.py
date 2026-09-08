"""Rehashed real event graphs reject hidden work, crossed charges and false ownership."""
from copy import deepcopy
import tempfile
import unittest

from tools.tests.cache_behavior_fixtures import Fixture
from tools.optimization_backend_revision.cache import model


class BehaviorReplayTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="cache-behavior-replay-")
        self.addCleanup(self.temp.cleanup)
        self.fixture = Fixture(self.temp.name, "candidate")

    def test_exact_population_and_actual_candidate_graph(self):
        self.assertEqual(model.population("full"), (802, 1617))
        result = self.fixture.parse()
        self.assertEqual(result["samples"], "80")
        self.assertEqual(result["direct_work"]["executions"], "1")
        concurrent = next(row for row in result["phase_metrics"] if row["phase"] == "concurrent")
        self.assertEqual(sum(concurrent["outcomes"].values()), 20)
        self.assertEqual(concurrent["outcomes"]["transport-failure"], 2)
        self.assertTrue(result["runtime_accounting_available"])

    def test_actual_control_ledger_is_unavailable(self):
        with tempfile.TemporaryDirectory() as root:
            result = Fixture(root, "control").parse()
        self.assertFalse(result["runtime_accounting_available"])

    def test_missing_offer_cannot_hide_a_debug_failure(self):
        rows = self.fixture.raw["samples"]
        rows.remove(next(row for row in rows if row.get("outcome") == "transport-failure"))
        with self.assertRaisesRegex(ValueError, "missing-offer|incomplete-population"):
            self.fixture.parse()

    def test_rehashed_resident_probe_contradiction_rejected(self):
        row = self.fixture.checkpoint("held-two-ready")
        row["node"]["inventory"]["cacheSummary"]["sourceBytes"] = str(int(row["accounting"]["resident"]["source_bytes"]) + 1)
        with self.assertRaisesRegex(ValueError, "accounting-sample-disagrees"):
            self.fixture.parse()

    def test_actual_materialized_owner_cannot_be_erased(self):
        row = self.fixture.checkpoint("held-ready-and-active")
        owner = next(item for item in row["node"]["inventory"]["topology"]["entries"] if item["name"] == "prepared-instance-reservations")
        owner["activeCount"] = "0"
        with self.assertRaisesRegex(ValueError, "materialization-owner-not-sampled"):
            self.fixture.parse()

    def test_sequential_checkpoint_cannot_move_before_prior_response(self):
        capture = self.fixture.checkpoint("after-baseline")["observer"]
        # Preserve its valid observer-origin bracket, but rewind the complete
        # capture to the earlier baseline-start observation.
        earlier = self.fixture.checkpoint("after-warmup")["observer"]
        capture.update(deepcopy(earlier))
        with self.assertRaisesRegex(ValueError, "checkpoint-before-previous-work"):
            self.fixture.parse()

    def test_evicted_runtime_cost_cannot_be_replaced_with_another_charge(self):
        value = self.fixture.checkpoint("evicted-held-ready")["accounting"]["runtimes"]
        value["evicted_live"]["metadata_bytes"] = str(int(value["evicted_live"]["metadata_bytes"]) + 1)
        value["live"]["metadata_bytes"] = str(int(value["live"]["metadata_bytes"]) + 1)
        with self.assertRaisesRegex(ValueError, "held-runtime-cost-crossed"):
            self.fixture.parse()

    def test_final_missing_ledger_is_not_zero(self):
        self.fixture.raw["final_runtime_accounting"] = None
        with self.assertRaises(ValueError):
            self.fixture.parse()

    def test_refill_failure_cannot_hide_eviction(self):
        row = next(row for row in self.fixture.raw["samples"] if row["kind"] == "failed-refill-accounting")
        for value in (row["after"]["resident"], row["after"]["runtimes"]["resident"], row["after"]["runtimes"]["live"]):
            value["source_bytes"] = str(int(value["source_bytes"]) - 1)
        with self.assertRaisesRegex(ValueError, "failed-refill-evicted-resident"):
            self.fixture.parse()

    def test_missing_archived_stage_cannot_be_excused_by_ring_overwrite(self):
        row = next(row for row in self.fixture.raw["samples"] if row["kind"] == "preparation-events" and row["events"])
        row["events"].pop()
        with self.assertRaisesRegex(ValueError, "export-missing-duplicate-or-reordered-stage"):
            self.fixture.parse()

    def test_changed_route_generation_is_rejected(self):
        row = next(row for row in self.fixture.raw["samples"] if row.get("outcome") == "success")
        row["response"]["route_generation"] = "8"
        with self.assertRaises(ValueError):
            self.fixture.parse()
