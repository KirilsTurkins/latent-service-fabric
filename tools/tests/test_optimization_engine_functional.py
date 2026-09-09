"""Replay actual dirty functional graphs; no build or performance qualification."""
import copy
import gzip
import json
from pathlib import Path
import unittest

from tools.optimization_backend_revision.engine import calls, diagnostic, proofs, schedule
from tools.optimization_evidence.common import EvidenceError, sha256

IDENTITIES = {
    "D0": (716101, "0c6299cab9183d8d20b072ad284febafc7e473edb27ec84d82547f2e97ed8970"),
    "P0": (716244, "973e8398f52ebd33b6395a5e03ebbff9ef3ffa3f31c259b3f84b383afb07be41"),
}


def replay(value):
    """Only the actual offer/status/diagnostic/native proof portions are replayed."""
    expected, pins, normalized = schedule.expected("smoke"), {}, {}
    source = diagnostic.Diagnostic(value["final_diagnostic"])
    statuses = {row["target"]: row for row in value["samples"]
                if row["kind"] == "command" and row["operation"] == "get-activation"}
    cancels = [row for row in value["samples"] if row["kind"] == "command" and row["operation"] == "cancel"]
    elapsed, functional = int(value["elapsed_nanos"]), 0
    for row in value["samples"]:
        if row["kind"] != "invoke":
            continue
        ordinal = int(row["ordinal"])
        call = calls.validate(row, expected[ordinal - 1], ordinal, value["fixtures"],
                              int(value["clock"]["unix_origin_nanos"]), elapsed, pins,
                              int(value["clock"]["clock_anchor_uncertainty_nanos"]))
        status = statuses[row["activation_id"]]
        calls.status(status, call, elapsed)
        normalized[row["activation_id"]] = call
        if row["phase"] == "functional":
            source.bind_call(call, status)
            functional += 1
    proof = proofs.functional(value["samples"], normalized, statuses, cancels, source, elapsed)
    return normalized, functional, proof


class EngineActualFunctionalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.inputs = {}
        for label, (size, digest) in IDENTITIES.items():
            path = Path(__file__).parent / f"fixtures/engine-functional11-{label}.json.gz"
            with gzip.open(path, "rb") as source:
                raw = source.read(1024**2 + 1)
            assert len(raw) == size and sha256(raw) == "sha256:" + digest
            cls.inputs[label] = json.loads(raw)

    def changed(self, label="D0", activation="engine-fn-11"):
        value = copy.deepcopy(self.inputs[label])
        row = next(row for row in value["samples"] if row.get("activation_id") == activation)
        return value, row

    def test_both_original_graphs_validate_all_offers_and_native_proofs(self):
        for label, value in self.inputs.items():
            with self.subTest(profile=label):
                normalized, count, proof = replay(value)
                self.assertEqual((len(normalized), count), (52, 24))
                self.assertEqual([name for name, call in normalized.items() if call["row"]["native_fault"] is not None],
                                 ["engine-fn-11", "engine-fn-13"])
                self.assertEqual(proof["actual_running"], "24")
                self.assertEqual(proof["all_idle_proofs"], "20")
                self.assertEqual(proof["accepted_cancellations"], "5")
                self.assertEqual(proof["guest_logs"], "10")
                self.assertTrue(proof["four_live_before_fifth"] and proof["fifth_queued_without_store"]
                                and proof["three_live_after_fifth_success"])

    def test_rehashed_fault_identity_kind_and_consumption_crossings_reject(self):
        mutations = ({"activation_id": "engine-fn-13"}, {"tenant": "engine-b"},
                     {"release_digest": "sha256:" + "0" * 64}, {"revision_id": "revision-v1:sha256:" + "0" * 64},
                     {"route_generation": "9"}, {"kind": "activation.memory-exhausted"},
                     {"detail_count": "0"}, {"detail_field_count": "2"}, {"terminal_state": "completed"},
                     {"source": "public-status"}, {"cell_id": None}, {"cell_id": "x" * 513})
        for mutation in mutations:
            value, row = self.changed()
            row["native_fault"].update(mutation)
            with self.subTest(mutation=mutation), self.assertRaises(EvidenceError):
                replay(value)
        value, row = self.changed()
        row["native_fault"]["consumption"]["cpu_fuel"] = "49999"
        with self.assertRaisesRegex(EvidenceError, "fault-receipt-crossed"):
            replay(value)

    def test_fault_erasure_invention_and_public_redaction_crossings_reject(self):
        for label in IDENTITIES:
            value, row = self.changed(label)
            row["native_fault"] = None
            with self.subTest(profile=label), self.assertRaises(EvidenceError):
                replay(value)
        value, row = self.changed()
        row["response"]["details"] = [{"kind": row["native_fault"]["kind"], "fields": {"cell_id": row["native_fault"]["cell_id"]}}]
        with self.assertRaisesRegex(EvidenceError, "kind-or-redaction-crossed"):
            replay(value)
        value, row = self.changed()
        first = next(row for row in value["samples"] if row.get("activation_id") == "engine-echo-0000")
        first["native_fault"] = copy.deepcopy(row["native_fault"])
        with self.assertRaisesRegex(EvidenceError, "outside-fixed-cases"):
            replay(value)

    def test_fault_capture_must_follow_response_and_precede_public_status(self):
        for boundary in ("response", "status"):
            value, row = self.changed()
            fault = row["native_fault"]
            if boundary == "response":
                fault["capture_started_nanos"] = str(int(row["completed_nanos"]) - 1)
            else:
                status = next(item for item in value["samples"] if item["kind"] == "command"
                              and item["operation"] == "get-activation" and item["target"] == row["activation_id"])
                fault["capture_finished_nanos"] = str(int(status["started_nanos"]) + 1)
            with self.subTest(boundary=boundary), self.assertRaisesRegex(EvidenceError, "native-fault"):
                replay(value)


if __name__ == "__main__":
    unittest.main()
