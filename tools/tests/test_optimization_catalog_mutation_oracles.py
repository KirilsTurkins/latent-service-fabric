"""Independent receipt, deletion and observer association regressions."""
from copy import deepcopy
import json
from pathlib import Path
import unittest

from tools.optimization_backend_revision.catalog_mutations import fixtures, oracle, policy
from tools.optimization_evidence.common import EvidenceError

ROOT = Path(__file__).resolve().parents[2]


def fixture():
    root = ROOT / "examples/echo-contract"
    return fixtures.normalize(fixtures.COMPONENT_HEADER,
        json.loads((root / "capsule.json").read_text()),
        json.loads((root / "contracts.json").read_text()),
        json.loads((root / "deployment.json").read_text()))


def snapshot(sequence, operation="apply-versioned", generation="2"):
    # Structural observer values only: not a build/measurement fixture.
    counts = {key: "0" for key in policy.WORK_COUNTS}
    return {"started": str(sequence), "finished": str(sequence), "active": "0",
        "maximum_active": "1" if sequence else "0", "overflowed": False, "poisoned": False,
        "last": None if sequence == 0 else {"sequence": str(sequence), "operation": operation,
            "outcome": "returned-ok", "compiled_generation": generation, "overflowed": False,
            "counts": counts}}


class CatalogMutationOracleTests(unittest.TestCase):
    def test_weight_preserves_revision_but_changes_manifest_and_recreate_changes_stamp(self):
        value = oracle.Oracle(fixture(), 4, "distinct")
        before = value.resolved("unchanged-apply", "named")["result"]
        after = value.resolved("weight-update", "named")["result"]
        self.assertEqual(before["revision"], after["revision"])
        self.assertEqual(before["release"], after["release"])
        self.assertNotEqual(before["attributes_digest"], after["attributes_digest"])
        self.assertIsNone(value.get("delete")["result"])
        self.assertEqual(value.mutation("delete")["result"]["deleted"]["object_generation"], "3")
        seed, final = value.get("seed")["result"], value.get("reapply")["result"]
        self.assertEqual(seed["manifest_digest"], final["manifest_digest"])
        self.assertEqual((seed["object_generation"], final["object_generation"]), ("1", "5"))

    def test_deleted_named_route_fails_while_shared_default_resolves_another_release(self):
        for shape in ("distinct", "shared"):
            value = oracle.Oracle(fixture(), 4, shape)
            self.assertEqual(value.resolved("delete", "named")["error"]["code"], "RouteUnavailable")
            default = value.resolved("delete", "default")
            if shape == "distinct":
                self.assertIn("error", default)
            else:
                self.assertIn(default["result"]["release"], [value.fixture.release(index) for index in (1, 2, 3)])
            self.assertEqual(value.resolved("seed", "named")["result"]["generation"], "1")

    def test_returned_absence_is_counted_as_success_and_ordinal_gaps_reject(self):
        counts = oracle.Operations()
        counts.add("gets", True, ordinal="1")
        counts.add("resolves", False, ordinal="2")
        self.assertEqual(counts.snapshot()["gets"], {"attempted": "1", "returned_ok": "1", "returned_error": "0"})
        with self.assertRaises(EvidenceError):
            counts.add("resolves", ordinal="4")
        with self.assertRaises(EvidenceError):
            counts.add("gets", count=True)


class CatalogMutationWorkTests(unittest.TestCase):
    def test_completed_receipt_requires_one_actual_operation_and_expected_generation(self):
        before, after = snapshot(1, "apply-many", "1"), snapshot(2)
        policy.work_operation(before, after, "apply-versioned", 2)
        for change in ({"operation": "delete-versioned"}, {"compiled_generation": "3"},
                       {"outcome": "owner-dropped"}, {"sequence": "1"}):
            modified = deepcopy(after)
            modified["last"].update(change)
            with self.subTest(change=change), self.assertRaises(EvidenceError):
                policy.work_operation(before, modified, "apply-versioned", 2)
        with self.assertRaises(EvidenceError):
            policy.work_operation(before, snapshot(3), "apply-versioned", 2)

    def test_overlap_poison_boolean_counters_and_unknown_fields_reject(self):
        for change in ({"active": "1"}, {"maximum_active": "2"}, {"finished": "1"},
                       {"started": True}, {"poisoned": True}, {"overflowed": True}, {"extra": "0"}):
            with self.subTest(change=change), self.assertRaises(EvidenceError):
                policy.work_snapshot({**snapshot(2), **change})
        modified = snapshot(2)
        modified["last"]["counts"]["compiler_calls"] = False
        with self.assertRaises(EvidenceError):
            policy.work_snapshot(modified)

    def test_unavailable_partial_stage_is_retained_but_cannot_qualify_success(self):
        observed = snapshot(2)
        observed["last"]["counts"]["stage_written_bytes"] = None
        self.assertIsNone(policy.work_counts(observed["last"]["counts"])["stage_written_bytes"])
        with self.assertRaises(EvidenceError):
            policy.work_operation(snapshot(1), observed, "apply-versioned", 2)


if __name__ == "__main__":
    unittest.main()
