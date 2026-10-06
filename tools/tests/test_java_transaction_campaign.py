"""Bounded evidence/oracle tests; synthetic frames grant no native authority."""
from __future__ import annotations

import copy
from pathlib import Path
import tempfile
import unittest

from tools.java_transaction_qualification import campaign, evidence, lifecycle
from tools.tests.test_java_transaction_qualification import result


def inspection(value):
    return {"commandId": value["command-id"], "attemptId": value["attempt-id"], "metadataDurable": True,
            "applicationStateCommitted": True, "source": {"publicationId": "original-signed-publication"},
            "key": {"clientKey": "original-id"}, "outcome": "COMMAND_OUTCOME_COMMITTED",
            "retainedResult": {"kind": "success", "value": {"payload": {
                "encoding": "base64", "data": value["result"]["body-base64"]}}}}


def retirement():
    report = {name: 0 for name in ("activeConnections", "activeRpcs", "activeControlJobs", "activeActivations",
        "cancellationRegistrations", "observerCorrelations", "quotaReservations", "queuedReservations",
        "reservedCpuFuel", "reservedMemoryBytes", "activeLeases", "queuedActivations", "quarantinedCells",
        "activeBackendInvocations", "instanceReservations", "preparingComponents", "liveStores",
        "liveHostStates", "liveInstances", "liveTemporaryBuffers", "liveCancellationProbes")}
    state = {name: 0 for name in ("ordinaryReservations", "ordinaryBytes", "recoveryReservations", "recoveryBytes",
        "storeAcceptedJobs", "storeRetainedBytes", "storePhysicalOwners", "storeQueuedRetirements", "storeLiveWorkers")}
    state.update(clean=True, nativeQuarantined=False, storeQuarantined=False, storeEngine="closed", storeThreadsJoined=1)
    report.update(clean=True, state=state)
    return report


class CampaignOracle(unittest.TestCase):
    def test_original_evidence_is_exclusive_and_never_overwritten(self):
        with tempfile.TemporaryDirectory() as temporary:
            collector = evidence.Evidence(Path(temporary) / "evidence")
            collector.write("actual.stdout", b"original")
            with self.assertRaises(FileExistsError):
                collector.write("actual.stdout", b"replacement")
            self.assertEqual((collector.directory / "actual.stdout").read_bytes(), b"original")
            self.assertEqual(collector.total, len(b"original"))

    def test_evidence_path_and_byte_limits_refuse_before_publication(self):
        with tempfile.TemporaryDirectory() as temporary:
            collector = evidence.Evidence(Path(temporary) / "evidence")
            for name, data in (("../outside", b"secret"), ("oversized", bytes(1048577))):
                with self.subTest(name=name), self.assertRaises(ValueError):
                    collector.write(name, data)
            self.assertEqual(list(collector.directory.iterdir()), [])
            self.assertEqual(collector.files, [])

    def test_original_result_cannot_adopt_current_publication_or_another_caller_key(self):
        value = result()
        original = inspection(value)
        campaign.rpc_result(original, value, "original-signed-publication", "original-id")
        for name, mutation in (("publication", {"source": {"publicationId": "current-publication"}}),
                               ("key", {"key": {"clientKey": "other-id"}}),
                               ("attempt", {"attemptId": "9" * 64}),
                               ("durability", {"metadataDurable": False})):
            changed = copy.deepcopy(original)
            changed.update(mutation)
            with self.subTest(name=name), self.assertRaises(ValueError):
                campaign.rpc_result(changed, value, "original-signed-publication", "original-id")

    def test_current_rpc_result_bytes_must_equal_original_http_payload(self):
        value = result()
        changed = inspection(value)
        changed["retainedResult"]["value"]["payload"]["data"] = "W10="
        with self.assertRaises(ValueError):
            campaign.rpc_result(changed, value, "original-signed-publication", "original-id")

    def test_clean_boolean_does_not_replace_actual_retired_owners(self):
        report = retirement()
        lifecycle.require_retirement(report)
        for owner in ("liveStores", "activeBackendInvocations", "quotaReservations", "quarantinedCells"):
            changed = copy.deepcopy(report)
            changed[owner] = 1
            with self.subTest(owner=owner), self.assertRaises(ValueError):
                lifecycle.require_retirement(changed)
        for owner in ("ordinaryReservations", "storePhysicalOwners", "storeLiveWorkers", "storeRetainedBytes"):
            changed = copy.deepcopy(report)
            changed["state"][owner] = 1
            with self.subTest(owner=owner), self.assertRaises(ValueError):
                lifecycle.require_retirement(changed)
        changed = copy.deepcopy(report)
        changed["state"]["storeEngine"] = "finalizing"
        with self.assertRaises(ValueError):
            lifecycle.require_retirement(changed)

    def test_generic_platform_refusal_is_distinct_from_durable_abort_json(self):
        with tempfile.TemporaryDirectory() as temporary:
            collector = evidence.Evidence(Path(temporary) / "evidence")
            subject = campaign.Campaign.__new__(campaign.Campaign)
            subject.client = type("Observer", (), {"evidence": collector})()
            subject.refusal("read-denied", {"status": 403, "body": b""}, {403})
            subject.refusal("state-conflict", {"status": 409, "body": b"Conflict\n"}, {409})
            for body in (b'{"disposition":"aborted"}', b'Forbidden: private-debug\n'):
                with self.subTest(body=body), self.assertRaises(ValueError):
                    subject.refusal("unknown-error", {"status": 403, "body": body}, {403})


if __name__ == "__main__":
    unittest.main()
