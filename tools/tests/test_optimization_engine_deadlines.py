"""Actual failed-smoke oracle regression plus bounded projection/status units."""
import copy
import gzip
import json
from pathlib import Path
import unittest

from tools.optimization_backend_revision.engine import calls, diagnostic, parse, schedule
from tools.optimization_evidence.common import EvidenceError, sha256
from tools.optimization_evidence.workload import framed


class EngineFailedSmokeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path = Path(__file__).parent / "fixtures/engine-smoke02-failed.json.gz"
        with gzip.open(path, "rb") as source:
            raw = source.read(1024**2 + 1)
        assert len(raw) == 582470
        assert sha256(raw) == "sha256:f02088348773dde6a5d2f221ab9a80dc2a73c45a32f4492d1eea622085a5b6d3"
        cls.raw = json.loads(raw)

    def snapshot(self):
        row = copy.deepcopy(next(row for row in self.raw["samples"] if row.get("activation_id") == "engine-fn-01"))
        records = [item["observation"] for item in self.raw["final_diagnostic"]["records"]
                   if item["token"] == row["diagnostic_token"]]
        expected = next(row for row in schedule.expected("smoke") if row["activation_id"] == "engine-fn-01")
        return {"row": row, "expected": expected, "output": row["response"]["payload"]["value"]}, records

    def test_original_failed_population_cannot_become_qualified(self):
        self.assertEqual(self.raw["status"], "failed")
        self.assertEqual(len([row for row in self.raw["samples"] if row["kind"] == "invoke"]), 52)
        with self.assertRaisesRegex(EvidenceError, "raw-not-qualified"):
            parse.parse(self.raw, self.raw["plan"], self.raw["identity"], None, None, None, None)

    def test_actual_snapshot_uses_wit_none_and_inner_ledger_deadline(self):
        call, records = self.snapshot()
        self.assertTrue(call["row"]["valid_response"])
        self.assertFalse(call["row"]["semantic_validated"])
        ledger = next(row for row in records if row["kind"] == "admitted-ledger")
        self.assertEqual(call["output"][0]["principal"]["service"], {"none": None})
        self.assertEqual(call["output"][0]["deadline"], {"some": ledger["deadline"]["unix_millis"]})
        self.assertEqual(int(call["row"]["deadline_unix_millis"]) - int(ledger["deadline"]["unix_millis"]), 4000)
        diagnostic.oracle(call, records)
        # This correct per-offer oracle cannot change the failed arm's status.
        self.assertFalse(call["row"]["semantic_validated"])

    def test_rehashed_context_none_and_outer_deadline_crossings_reject(self):
        for mutation in ("service", "deadline"):
            call, records = self.snapshot()
            value = call["output"][0]
            if mutation == "service":
                value["principal"]["service"] = None
            else:
                value["deadline"] = {"some": call["row"]["deadline_unix_millis"]}
            payload = call["row"]["response"]["payload"]
            changed = framed(call["output"])
            payload.update(utf8=changed.decode(), sha256=sha256(changed), bytes=str(len(changed)))
            calls.blob(payload, response=True)
            with self.subTest(mutation=mutation), self.assertRaisesRegex(EvidenceError, "context-authority-or-deadline-crossed"):
                diagnostic.oracle(call, records)


class EngineLegacyDeadlineProjectionTests(unittest.TestCase):
    def offer(self, origin, uncertainty):
        # Projection arithmetic unit; no forged successful RPC/source receipt.
        absolute, remainder = divmod(origin - uncertainty + 5_000_000_000, 1_000_000)
        return {"scheduled_nanos": "0", "dispatch_nanos": "100000", "completed_nanos": "200000",
                "deadline_nanos": "5000000000", "deadline_unix_millis": str(absolute),
                "absolute_deadline_floor_loss_nanos": str(remainder),
                "absolute_deadline_total_loss_nanos": str(uncertainty + remainder),
                "dispatch_lag_nanos": "100000", "overshoot_nanos": "0", "grpc_timeout_header": "4999900u"}

    def test_conservative_projection_never_extends_anchor_at_ms_boundary(self):
        for origin, uncertainty in ((1_000_001, 2), (1_000_000, 0), (1_999_999, 649),
                                    (1_788_987_889_384_972_573, 649)):
            row = self.offer(origin, uncertainty)
            calls.clock(row, origin, 300000, uncertainty, legacy_clock=True)
            projected = int(row["deadline_unix_millis"]) * 1_000_000
            self.assertLessEqual(projected, origin - uncertainty + 5_000_000_000)
            self.assertLess(int(row["absolute_deadline_floor_loss_nanos"]), 1_000_000)
            self.assertEqual(origin + 5_000_000_000 - projected, int(row["absolute_deadline_total_loss_nanos"]))
        # Without subtracting the measured anchor interval even a floor can be
        # one millisecond above the conservative value at this exact boundary.
        self.assertEqual((1_000_001 + 5_000_000_000) // 1_000_000,
                         int(self.offer(1_000_001, 2)["deadline_unix_millis"]) + 1)

    def test_upward_projection_and_crossed_losses_reject(self):
        original = self.offer(1_000_001, 2)
        for key in ("deadline_unix_millis", "absolute_deadline_floor_loss_nanos", "absolute_deadline_total_loss_nanos"):
            row = dict(original)
            row[key] = str(int(row[key]) + 1)
            with self.subTest(key=key), self.assertRaisesRegex(EvidenceError, "outer-deadline-crossed"):
                calls.clock(row, 1_000_001, 300000, 2, legacy_clock=True)
        with self.assertRaisesRegex(EvidenceError, "anchor-underflow"):
            calls.clock(original, 1, 300000, 2, legacy_clock=True)

    def test_actual_old_ceil_request_is_not_accepted_as_new_floor_evidence(self):
        path = Path(__file__).parent / "fixtures/engine-smoke02-failed.json.gz"
        with gzip.open(path, "rb") as source:
            value = json.loads(source.read(1024**2 + 1))
        row = copy.deepcopy(next(row for row in value["samples"] if row.get("activation_id") == "engine-fn-02"))
        origin, uncertainty = (int(value["clock"][key]) for key in ("unix_origin_nanos", "clock_anchor_uncertainty_nanos"))
        conservative = origin - uncertainty + int(row["deadline_nanos"])
        row["absolute_deadline_floor_loss_nanos"] = str(conservative % 1_000_000)
        row["absolute_deadline_total_loss_nanos"] = str(uncertainty + conservative % 1_000_000)
        self.assertEqual(row["grpc_code"], 3)
        with self.assertRaisesRegex(EvidenceError, "outer-deadline-crossed"):
            calls.clock(row, origin, int(value["elapsed_nanos"]), uncertainty, legacy_clock=True)


class EngineFreshDeadlineProjectionTests(unittest.TestCase):
    ORIGIN = 1_788_987_889_384_972_573
    UNCERTAINTY = 649

    def offer(self, unix=None, interval=20000):
        # Projection-only unit: no successful RPC or source/build receipt is
        # fabricated. The wall sample is independent of the campaign anchor.
        scheduled, start = 1_100_000_000, 1_100_010_000
        finish, dispatch, completed = start + interval, scheduled + 100000, scheduled + 200000
        deadline = scheduled + 5_000_000_000
        unix = self.ORIGIN + start if unix is None else unix
        absolute, remainder = divmod(unix + max(0, deadline - finish), 1_000_000)
        return {"scheduled_nanos": str(scheduled), "dispatch_nanos": str(dispatch), "completed_nanos": str(completed),
                "deadline_nanos": str(deadline), "deadline_unix_millis": str(absolute),
                "deadline_clock_sample": {"started_nanos": str(start), "finished_nanos": str(finish), "unix_nanos": str(unix)},
                "absolute_deadline_floor_loss_nanos": str(remainder),
                "absolute_deadline_total_loss_nanos": str(interval + remainder),
                "dispatch_lag_nanos": "100000", "overshoot_nanos": "0", "grpc_timeout_header": "4999900u"}

    def check(self, row, **options):
        return calls.clock(row, self.ORIGIN, 1_200_000_000, self.UNCERTAINTY, **options)

    def test_fresh_floor_and_bracket_loss_at_millisecond_boundaries(self):
        for unix, interval in ((1_000_000, 0), (1_000_001, 1), (1_999_999, 20000), (self.ORIGIN, 90000)):
            row = self.offer(unix, interval)
            self.check(row)
            sample = row["deadline_clock_sample"]
            projected = int(row["deadline_unix_millis"]) * 1_000_000
            conservative = unix + int(row["deadline_nanos"]) - int(sample["finished_nanos"])
            self.assertLessEqual(projected, conservative)
            self.assertLess(conservative - projected, 1_000_000)
            self.assertEqual(unix + int(row["deadline_nanos"]) - int(sample["started_nanos"]) - projected,
                             int(row["absolute_deadline_total_loss_nanos"]))

    def test_three_millisecond_backward_wall_drift_uses_actual_offer_sample(self):
        row = self.offer(self.ORIGIN + 1_100_010_000 - 3_000_000)
        self.check(row)
        legacy_absolute = (self.ORIGIN - self.UNCERTAINTY + int(row["deadline_nanos"])) // 1_000_000
        self.assertGreaterEqual(legacy_absolute - int(row["deadline_unix_millis"]), 3)
        row["deadline_unix_millis"] = str(legacy_absolute)
        with self.assertRaisesRegex(EvidenceError, "outer-deadline-crossed"):
            self.check(row)

    def test_sample_clock_chronology_and_wall_projection_crossings_reject(self):
        changes = ({"started_nanos": "1099999999"}, {"finished_nanos": "1100009999"},
                   {"finished_nanos": "1100100001"}, {"unix_nanos": "0"},
                   {"started_nanos": True}, {"unix_nanos": "-1"}, {"unexpected": "1"})
        for mutation in changes:
            row = self.offer()
            row["deadline_clock_sample"].update(mutation)
            with self.subTest(mutation=mutation), self.assertRaises(EvidenceError):
                self.check(row)
        for key in ("deadline_unix_millis", "absolute_deadline_floor_loss_nanos", "absolute_deadline_total_loss_nanos"):
            row = self.offer()
            row[key] = str(int(row[key]) + 1)
            with self.subTest(field=key), self.assertRaisesRegex(EvidenceError, "outer-deadline-crossed"):
                self.check(row)

    def test_fresh_sample_required_without_implicit_legacy_fallback(self):
        row = self.offer()
        with self.assertRaisesRegex(EvidenceError, "legacy-clock-with-fresh-sample"):
            self.check(row, legacy_clock=True)
        del row["deadline_clock_sample"]
        with self.assertRaisesRegex(EvidenceError, "fresh-deadline-clock-missing"):
            self.check(row)
        for invalid in (None, 1, "legacy"):
            with self.subTest(mode=invalid), self.assertRaisesRegex(EvidenceError, "clock-mode"):
                self.check(row, legacy_clock=invalid)


class EngineTransportStatusTests(unittest.TestCase):
    def test_actual_length_and_utf8_prefix_truncation_are_distinct(self):
        message = "deadline exceeds the configured maximum"
        for message, original in ((message, len(message.encode())), ("", 0),
                                  ("x" * 2048, 2049), ("x" * 2045, 2049)):
            # The fixed error string is a status-field unit, not a claim that
            # the previous failed producer retained its missing message.
            calls.transport_status({"outcome": "transport-failure", "grpc_status": {
                "code": 3, "message": message, "message_bytes": str(original),
                "message_truncated": original > len(message.encode())}})
        calls.transport_status({"outcome": "success", "grpc_status": None})

    def test_missing_crossed_and_oversized_transport_status_reject(self):
        status = {"code": 3, "message": "failure", "message_bytes": "7", "message_truncated": False}
        mutations = (None, dict(status, code=True), dict(status, code=17), dict(status, message="x" * 2049),
                     dict(status, message_bytes="8"), dict(status, message_truncated=True),
                     dict(status, extra=True), dict(status, message="x" * 2044, message_bytes="2049", message_truncated=True),
                     dict(status, message="x" * 2045, message_bytes="2046", message_truncated=True))
        for value in mutations:
            with self.subTest(value=value), self.assertRaises(EvidenceError):
                calls.transport_status({"outcome": "transport-failure", "grpc_status": value})
        with self.assertRaisesRegex(EvidenceError, "without-failure"):
            calls.transport_status({"outcome": "success", "grpc_status": status})


if __name__ == "__main__":
    unittest.main()
