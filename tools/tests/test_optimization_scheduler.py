"""Finite protocol unit cases; synthetic rows are never qualified release evidence."""
import copy
import os
import unittest
from unittest.mock import patch

from tools.optimization_scheduler import aggregate, allocations, model, rows
from tools.optimization_scheduler.parse import checkpoint, parse
from tools.optimization_evidence.common import EvidenceError, canonical, sha256
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


def raw_checkpoint(label, at, *, granted=0, cancelled=0, depth=0, live=0, leases=0,
                   tenant_count=0, enabled=False, unlinks=0, accepting=True):
    """Small hand-authored protocol state, not a recorded scheduler observation."""
    return {
        "label": label, "started_nanos": str(at), "finished_nanos": str(at + 1000),
        "scheduler": {"accepting": accepting, "capacity": "4", "available": str(4 - leases),
                      "active_leases": str(leases), "quarantined": "0", "queue_depth": str(depth),
                      "queued_tenants": str(tenant_count if depth else 0), "rejected": str(cancelled),
                      "cancellations": str(cancelled), "expired": "0", "granted": str(granted),
                      "total_wait_micros": "0", "max_wait_micros": "0", "oldest_lease_age_micros": "0"},
        "quota": {"active_activations": str(live), "queued_activations": str(depth),
                  "reserved_cpu_fuel": str(live * 100), "reserved_memory_bytes": str(live * 65536),
                  "retained_tenants": str(tenant_count)},
        "work": {"enabled": enabled, "overflowed": False, "tenant_linear_visits": "0",
                 "winner_comparisons": "0", "cancel_entry_visits": "0", "entry_shifted_slots": "0",
                 "tenant_shifted_slots": "0", "entry_unlinks": str(unlinks), "tenant_index_lookups": "0"},
    }


def raw_document(case="closed-one"):
    """Two finite synthetic parser fixtures; neither has a build/owner/archive graph."""
    selected = model.plan("smoke", case=case)
    identity = {"source": {"commit": "a" * 40, "clean": False},
                "diagnostic": "synthetic parser unit fixture; not collected evidence"}
    process_id = os.getpid()
    plan_hash, identity_hash = sha256(canonical(selected)), sha256(canonical(identity))
    value = {"schema": "latent.optimization.scheduler-arm.v1", "plan": copy.deepcopy(selected),
             "identity": copy.deepcopy(identity), "process_id": process_id, "plan_sha256": plan_hash,
             "identity_sha256": identity_hash, "settings": model.settings(selected),
             "outcome": "passed", "failure": None, "runtime_dropped": True, "fixture_dropped": True, "invokes": "0"}
    if case == "closed-one":
        value.update(rows=released_rows(), started_nanos="188000000", finished_nanos="364000000",
                     elapsed_nanos="380000000", frame=None,
                     counts={"offers": "24", "admission_calls": "24", "admitted": "24", "enqueue_calls": "24",
                             "enqueue_results": "24", "cancel_calls": "0", "cancel_accepted": "0",
                             "release_calls": "24", "released": "24", "cleanup_reclaims": "0", "shutdown_calls": "1"},
                     checkpoints=[raw_checkpoint("ready", 0), raw_checkpoint("after-warmup", 187500000, granted=8),
                                  raw_checkpoint("load-finished", 365000000, granted=24),
                                  raw_checkpoint("shutdown", 370000000, granted=24, accepting=False)])
    else:
        if case != "cancel-many":
            raise AssertionError("only the two declared fixture cases exist")
        original, cancelled_index, released_index = [], 0, 0
        for ordinal in range(68):
            holder = ordinal < 4
            index = ordinal if holder else ordinal - 4
            at = (100000000 if holder else 120000000) + index * 1000
            row = dict.fromkeys(rows.TIMES)
            row.update(ordinal=str(ordinal), tenant=str(index % 8), activation_id=f"scheduler-{ordinal:05}",
                       role="holder" if holder else "queued", scheduled_nanos=str(at), dispatched_nanos=str(at),
                       admission_started_nanos=str(at + 1), admission_finished_nanos=str(at + 2), admitted_nanos=str(at + 2),
                       deadline_nanos=str(at + 1000000001), deadline_unix_millis="10000", enqueue_called_nanos=str(at + 3),
                       cancel_accepted=None, cancel_error=None, error=None, cleanup_reclaimed=False)
            # Explicit tenant-local cancellation set, independent of model.cancelled.
            if not holder and index // 8 in (0, 3, 4, 7):
                request = 300000000 + cancelled_index * 1000
                row.update(cancel_requested_nanos=str(request), cancel_finished_nanos=str(request + 1), cancel_accepted=True,
                           result_nanos=str(330000000 + cancelled_index * 1000), outcome="scheduler-error",
                           error={"code": "cancelled", "message": "local scheduling could not proceed", "retryable": False,
                                  "details": [{"kind": "scheduler.limit", "fields": {"reason": "cancelled"}}]})
                cancelled_index += 1
            else:
                returned = at + 4 if holder else 420000000 + released_index * 2000000
                release = 400000000 + ordinal * 1000000 if holder else returned + 1000000
                row.update(result_nanos=str(returned), release_started_nanos=str(release), released_nanos=str(release + 1), outcome="released")
                if not holder:
                    released_index += 1
            original.append(row)
        value.update(rows=original, started_nanos="100000000", finished_nanos="490000000", elapsed_nanos="520000000",
                     counts={"offers": "68", "admission_calls": "68", "admitted": "68", "enqueue_calls": "68",
                             "enqueue_results": "68", "cancel_calls": "32", "cancel_accepted": "32",
                             "release_calls": "36", "released": "36", "cleanup_reclaims": "0", "shutdown_calls": "1"},
                     frame={"symbol": model.SYMBOL, "polls": "1", "started_nanos": "300000000", "finished_nanos": "350000000",
                            "cancel_calls": "32", "settled": "32", "scope": "cancel-and-original-enqueue-future-settlement"},
                     checkpoints=[raw_checkpoint("ready", 0),
                                  raw_checkpoint("four-holders", 110000000, granted=4, live=4, leases=4, tenant_count=4),
                                  raw_checkpoint("queued", 200000000, granted=4, depth=64, live=68, leases=4, tenant_count=8),
                                  raw_checkpoint("cancel-before", 290000000, granted=4, depth=64, live=68, leases=4, tenant_count=8, enabled=True),
                                  raw_checkpoint("cancel-after", 360000000, granted=4, cancelled=32, depth=32, live=36, leases=4, tenant_count=8, enabled=True, unlinks=32),
                                  raw_checkpoint("storm-drained", 500000000, granted=36, cancelled=32),
                                  raw_checkpoint("shutdown", 510000000, granted=36, cancelled=32, accepting=False)])
        # Grant wait counters correspond to the still-original successful queued offers.
        waits = [(int(row["result_nanos"]) - int(row["enqueue_called_nanos"])) // 1000
                 for row in original if row["outcome"] == "released"]
        for item in value["checkpoints"][-2:]:
            item["scheduler"].update(total_wait_micros=str(sum(waits)), max_wait_micros=str(max(waits)))
    return value, (selected, identity, process_id, plan_hash, identity_hash)


class CompleteRawDocuments(unittest.TestCase):
    def test_complete_closed_document_replays_warmup_and_measured_populations(self):
        value, inputs = raw_document()
        result = parse(value, *inputs)
        self.assertEqual(result["counts"]["offers"], "24")
        self.assertEqual(result["warmup"]["offers"], "8")
        self.assertEqual(result["measured"]["outcomes"]["released"], "16")
        self.assertEqual(result["measured"]["observed_hold_nanos"]["median"], "10000000")
        self.assertIsNone(result["frame"])
        self.assertIsNone(result["work"])

    def test_complete_storm_document_replays_original_cancellation_and_refunds(self):
        value, inputs = raw_document("cancel-many")
        result = parse(value, *inputs)
        self.assertEqual(result["counts"]["enqueue_calls"], "68")
        self.assertEqual(result["measured"]["outcomes"], {"released": "36", "admission-error": "0", "scheduler-error": "32", "backpressure": "0"})
        self.assertEqual([row["offers"] for row in result["per_tenant"].values()], ["9"] * 4 + ["8"] * 4)
        self.assertEqual(result["measured"]["cancel_to_original_settlement_nanos"]["count"], "32")
        self.assertEqual(result["frame"]["settled"], "32")
        self.assertEqual(result["work"]["entry_unlinks"], "32")
        self.assertIsNone(result["warmup"])

    def test_raw_pid_plan_and_identity_are_bound_to_independent_inputs(self):
        original, inputs = raw_document()
        changes = {"pid": lambda value: value.update(process_id=inputs[2] + 1),
                   "pid-type": lambda value: value.update(process_id=str(inputs[2])),
                   "plan-hash": lambda value: value.update(plan_sha256="sha256:" + "b" * 64),
                   "identity-hash": lambda value: value.update(identity_sha256="sha256:" + "c" * 64),
                   "plan": lambda value: value["plan"].update(variant="candidate"),
                   "identity": lambda value: value["identity"]["source"].update(clean=True)}
        for name, mutate in changes.items():
            value = copy.deepcopy(original)
            mutate(value)
            with self.subTest(name=name), self.assertRaises(EvidenceError):
                parse(value, *inputs)

    def test_original_cancel_settlements_must_stay_inside_the_actual_frame(self):
        original, inputs = raw_document("cancel-many")
        for field, value in (("started_nanos", "300000001"), ("finished_nanos", "330000000")):
            changed = copy.deepcopy(original)
            changed["frame"][field] = value
            with self.subTest(field=field), self.assertRaisesRegex(EvidenceError, "scheduler-cancel-settlement-outside-frame"):
                parse(changed, *inputs)
        for field, value in (("polls", "0"), ("settled", "31")):
            changed = copy.deepcopy(original)
            changed["frame"][field] = value
            with self.subTest(field=field), self.assertRaisesRegex(EvidenceError, "scheduler-cancellation-frame"):
                parse(changed, *inputs)

    def test_absent_duplicated_and_replaced_checkpoints_are_rejected(self):
        for case in ("closed-one", "cancel-many"):
            original, inputs = raw_document(case)
            for operation in ("absent", "duplicate", "replaced"):
                value = copy.deepcopy(original)
                if operation == "absent":
                    del value["checkpoints"][1]
                elif operation == "duplicate":
                    value["checkpoints"].insert(1, copy.deepcopy(value["checkpoints"][1]))
                else:
                    value["checkpoints"][2] = copy.deepcopy(value["checkpoints"][1])
                with self.subTest(case=case, operation=operation), self.assertRaisesRegex(EvidenceError, "scheduler-checkpoint-(population|order)"):
                    parse(value, *inputs)

    def test_consistent_nonzero_final_owners_and_undropped_runtime_are_rejected(self):
        for case in ("closed-one", "cancel-many"):
            original, inputs = raw_document(case)
            value = copy.deepcopy(original)
            final = value["checkpoints"][-1]
            final["scheduler"].update(available="3", active_leases="1")
            final["quota"].update(active_activations="1", reserved_cpu_fuel="100", reserved_memory_bytes="65536", retained_tenants="1")
            with self.subTest(case=case, kind="owner"), self.assertRaisesRegex(EvidenceError, "scheduler-final-owners-not-idle"):
                parse(value, *inputs)
            value = copy.deepcopy(original)
            value["runtime_dropped"] = False
            with self.subTest(case=case, kind="runtime"), self.assertRaisesRegex(EvidenceError, "scheduler-raw-incomplete-cleanup"):
                parse(value, *inputs)


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
