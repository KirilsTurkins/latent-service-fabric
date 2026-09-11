"""Finite protocol unit cases; synthetic rows are never qualified release evidence."""
import unittest
from unittest.mock import patch

from tools.optimization_scheduler import aggregate, allocations, model, rows
from tools.optimization_scheduler.parse import checkpoint
from tools.optimization_evidence.common import EvidenceError
from tools.optimization_backend_revision.ownership.allocations import Attribution


class FixedPopulation(unittest.TestCase):
    def test_both_populations_and_distinct_denominators(self):
        for profile, load, total in (("smoke", 936, 1344), ("full", 8720, 9128)):
            selected = list(model.population(profile))
            self.assertEqual(len(selected), 14)
            self.assertEqual(sum(model.counts(row)["logical_offers"] for row in selected), total)
            self.assertEqual(sum(model.counts(row)["logical_offers"] for row in selected if not row["case"].startswith("cancel-")), load)
            self.assertEqual(sum(model.counts(row)["planned_cancel_calls"] for row in selected), 192)
            self.assertEqual(sum(model.counts(row)["planned_release_calls"] for row in selected if row["case"].startswith("cancel-")), 216)
            self.assertEqual([row["variant"] for row in selected], ["control", "candidate", "candidate", "control"] * 3 + ["control", "candidate"])
            self.assertEqual(sum(row["mode"] == "allocation" for row in selected), 2)

    def test_tenant_local_cancel_set_does_not_become_global_ordinal_set(self):
        for tenants in (1, 8):
            chosen = [index for index in range(64) if model.cancelled(index, tenants)]
            self.assertEqual(len(chosen), 32)
            self.assertEqual([sum(index % tenants == tenant for index in chosen) for tenant in range(tenants)], [32 // tenants] * tenants)
        self.assertNotEqual([model.cancelled(index, 1) for index in range(64)], [model.cancelled(index, 8) for index in range(64)])

    def test_closed_plan_and_no_inherited_scratch_or_population_override(self):
        original = model.plan("full")
        for change in ({"observation_hold_millis": True}, {"mode": "allocation"}, {"case": "adaptive"},
                       {"profile": "quick"}, {"warmup_offers": 0}, {"repetition": 2}):
            with self.subTest(change=change), self.assertRaises(EvidenceError):
                model.validate_plan(dict(original, **change))
        for profile in ("smoke", "full"):
            selected = model.suite_plan(profile)
            self.assertEqual(selected["maximum_folded_bytes"], "67108864")
            self.assertEqual(selected["maximum_total_bytes"], "1073741824")
            self.assertNotIn("maximum_temporary_folded_bytes", selected)


def released_rows(selected=None):
    selected = selected or model.plan("smoke")
    result = []
    for index in range(model.counts(selected)["logical_offers"]):
        at = 100_000_000 + index * 11_000_000
        scheduled = at
        if index >= 8 and model.settings(selected)["rate_per_second"]:
            scheduled = 188_000_000 + (index - 8) * 10**9 // model.settings(selected)["rate_per_second"]
        row = dict.fromkeys(rows.TIMES)
        row.update(ordinal=str(index), tenant=str((index if index < 8 else index - 8) % model.tenants(selected)), activation_id=f"scheduler-{index:05}", role="warmup" if index < 8 else "measured",
                   scheduled_nanos=str(scheduled), dispatched_nanos=str(at), admission_started_nanos=str(at + 1), admission_finished_nanos=str(at + 2),
                   admitted_nanos=str(at + 2), deadline_nanos=str(at + 1_000_000_001), deadline_unix_millis="10000",
                   enqueue_called_nanos=str(at + 3), result_nanos=str(at + 4), release_started_nanos=str(at + 10_000_004),
                   released_nanos=str(at + 10_000_005), cancel_accepted=None, cancel_error=None, outcome="released", error=None, cleanup_reclaimed=False)
        result.append(row)
    return result


class OriginalOfferRows(unittest.TestCase):
    def validate(self, value):
        return rows.validate(value, model.plan("smoke"), 188_000_000, 400_000_000)

    def test_actual_boundaries_and_zero_denominator_remain_distinct(self):
        original = self.validate(released_rows())
        self.assertEqual(rows.counts(original)["enqueue_calls"], "24")
        summary = rows.summarize(original)
        self.assertIsNone(summary["cancel_to_original_settlement_nanos"])
        self.assertEqual(summary["observed_hold_nanos"]["median"], "10000000")
        self.assertEqual(rows.summarize([])["offers"], "0")

    def test_tampered_ordinal_tenant_deadline_hold_and_cleanup_rejected(self):
        for name, value in (("ordinal", "1"), ("tenant", "1"), ("deadline_nanos", "1100000003"),
                            ("released_nanos", "100000003"), ("release_started_nanos", "100000005"),
                            ("cleanup_reclaimed", True), ("cancel_accepted", False), ("outcome", "assigned")):
            changed = released_rows()
            changed[0][name] = value
            with self.subTest(name=name), self.assertRaises((EvidenceError, TypeError)):
                self.validate(changed)

    def test_backpressure_never_acquires_an_enqueue_denominator(self):
        selected = model.plan("smoke", case="saturated-one")
        changed = released_rows(selected)
        changed[-1].update({key: None for key in rows.TIMES})
        changed[-1]["outcome"] = "backpressure"
        validated = rows.validate(changed, selected, 188_000_000, 3_000_000_000)
        self.assertEqual(rows.counts(validated)["offers"], "208")
        self.assertEqual(rows.counts(validated)["admission_calls"], "207")
        changed[-1]["enqueue_called_nanos"] = "353000001"
        with self.assertRaises(EvidenceError):
            rows.validate(changed, selected, 188_000_000, 3_000_000_000)

    def test_snapshot_numeric_booleans_and_out_of_scope_counters_rejected(self):
        from tools.optimization_scheduler.parse import QUOTA, SCHEDULER, WORK
        item = {"label": "ready", "started_nanos": "1", "finished_nanos": "2",
                "scheduler": dict.fromkeys(SCHEDULER, "0"), "quota": dict.fromkeys(QUOTA, "0"),
                "work": dict.fromkeys(WORK, "0")}
        item["scheduler"].update(accepting=True, capacity="4", available="4")
        item["work"].update(enabled=False, overflowed=False)
        checkpoint(item, model.plan("smoke"), 3)
        item["scheduler"]["queue_depth"] = False
        with self.assertRaises(EvidenceError):
            checkpoint(item, model.plan("smoke"), 3)
        item["scheduler"]["queue_depth"] = "0"
        item["work"]["entry_unlinks"] = "1"
        with self.assertRaises(EvidenceError):
            checkpoint(item, model.plan("smoke"), 3)


class AllocationOrigins(unittest.TestCase):
    def test_single_selected_group_retains_origin_through_later_frees(self):
        state = Attribution("/probe", (("poll",),))
        for record in (b"v 10400 3", b"X /probe", b"I 1000 100", b"s 6 /probe", b"s 4 poll",
                       b"i 1 1 2", b"t 1 0", b"a a 1", b"c 1", b"+ 0", b"- 0"):
            state.record(record)
        self.assertEqual(state.named_count, 1)
        self.assertEqual(state.statistics[0], state.statistics[2])
        self.assertEqual(state.statistics[2]["peak_live_bytes"], 10)
        self.assertEqual(state.statistics[2]["live_bytes"], 0)

    def test_verified_symbol_without_observed_origin_is_unavailable(self):
        state = Attribution("/probe", (("poll",),))
        class Artifacts:
            def path(self, value):
                return value
        with patch.object(allocations, "symbol_proof", return_value={"raw": "poll", "demangled": "poll"}), \
                patch.object(allocations.common, "replay_attribution", return_value=({"allocation_count": "0"}, state)), \
                patch.object(allocations.common, "folded_attribution", return_value=(0, 0)):
            result = allocations.attribute({"profile_refs": {"interpreted": "raw", "allocations": "folded"}, "command": ["", "", "", "/probe"]},
                                           {}, {}, {}, Artifacts(), {"allocation_count": "0"})
        self.assertEqual(result["status"], "unavailable")
        self.assertEqual(result["reason"], "no-observed-named-allocation-origin")
        self.assertTrue(all(value is None for value in result["statistics"].values()))

    def test_empty_and_failed_population_cannot_qualify(self):
        suite = {"profile": "full", "plan": model.suite_plan("full"), "artifacts": [], "builds": {}, "elapsed_nanos": "1"}
        result = aggregate.aggregate(suite, "sha256:" + "0" * 64, {"requested_refs": {}}, [], False, True)
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["logical_offers"], "0")
        self.assertFalse(result["acceptance_qualified"])
        self.assertFalse(result["completed_paired_run"])


if __name__ == "__main__":
    unittest.main()
