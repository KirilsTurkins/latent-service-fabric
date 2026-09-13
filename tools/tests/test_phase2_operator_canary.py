"""The workflow may promote only the samples its actual receipts attribute."""
from copy import deepcopy
import unittest
from unittest.mock import Mock

from tools.phase2_operator_canary import rollback_target, validate_window
from tools.phase2_operator_process import WorkflowError


def fixture(candidate_count=8):
    summaries = {"blue": {"componentDigest": "sha256:" + "1" * 64},
                 "green": {"componentDigest": "sha256:" + "2" * 64}}
    started = {"revision": "1", "routeGeneration": "9"}
    rows, pins = [], []
    for name, count in (("blue", 16 - candidate_count), ("green", candidate_count)):
        digest = summaries[name]["componentDigest"]
        counters = {key: str(count) for key in ("selected", "admitted", "admittedTerminal", "success")}
        counters.update({key: "0" for key in ("domainError", "platformError", "deadlineExceeded", "cancelled")})
        counters["latencyBuckets"] = [str(count)] + ["0"] * 8
        rows.append({"revision": name, "componentDigest": digest, "counters": counters})
        pins.extend({"revisionId": name, "releaseDigest": digest, "routeGeneration": "9"} for _ in range(count))
    report = {"rolloutId": "healthy", "revision": "1", "routeGeneration": "9", "candidateRevision": "green",
              "starts": "16", "selected": "16", "admitted": "16", "terminal": "16", "live": "0",
              "unattributed": "0", "abandoned": "0", "revisions": rows,
              "assessment": {"verdict": "CANARY_VERDICT_HEALTHY", "admittedTerminal": str(candidate_count)}}
    return report, pins, started, summaries


class OperatorCanaryTests(unittest.TestCase):
    def test_start_target_is_read_from_exact_matching_status(self):
        started = {"rolloutId": "manual", "revision": "1", "routeGeneration": "9",
                   "planDigest": "sha256:" + "a" * 64, "rollbackTarget": None}
        status = {"id": "manual", "revision": "1", "routeGeneration": "9", "planDigest": started["planDigest"],
                  "rollbackTarget": {"formatVersion": 1, "historicalRouteGeneration": "8",
                                     "manifestDigest": "sha256:" + "b" * 64}}
        client = Mock()
        client.call.return_value = {"data": {"status": status}}
        self.assertEqual(rollback_target(client, "manual", started), "8")
        client.call.assert_called_once_with("rollout", "get", "manual")
        for key, replacement in (("id", "other"), ("revision", "2"), ("routeGeneration", "10"),
                                 ("planDigest", "sha256:" + "c" * 64)):
            client.call.return_value = {"data": {"status": dict(status, **{key: replacement})}}
            with self.subTest(key=key), self.assertRaisesRegex(WorkflowError, "rollback-status-association"):
                rollback_target(client, "manual", started)

    def test_exact_attributed_counts_are_returned_for_receipt_comparison(self):
        candidate, baseline = validate_window(*fixture())
        self.assertEqual(candidate["selected"], "8")
        self.assertEqual(baseline["success"], "8")

    def test_a_claimed_healthy_result_never_substitutes_for_candidate_samples(self):
        with self.assertRaisesRegex(WorkflowError, "canary-no-candidate-sample"):
            validate_window(*fixture(candidate_count=0))

    def test_other_route_generation_or_loss_cannot_pass(self):
        report, pins, started, summaries = fixture()
        changed = deepcopy(pins)
        changed[0]["routeGeneration"] = "10"
        with self.assertRaisesRegex(WorkflowError, "canary-invoke-attribution"):
            validate_window(report, changed, started, summaries)
        for key in ("live", "unattributed", "abandoned"):
            changed = dict(report, **{key: "1"})
            with self.subTest(key=key), self.assertRaisesRegex(WorkflowError, "canary-loss-or-live"):
                validate_window(changed, pins, started, summaries)

    def test_counter_disagreement_is_not_smoothed_over(self):
        report, pins, started, summaries = fixture()
        report["revisions"][1]["counters"]["success"] = "7"
        with self.assertRaisesRegex(WorkflowError, "canary-attributed-counters"):
            validate_window(report, pins, started, summaries)
