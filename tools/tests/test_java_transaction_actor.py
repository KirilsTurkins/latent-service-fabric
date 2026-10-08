"""Exact receipt identity checks; synthetic replies grant no native authority."""
from __future__ import annotations

import copy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools.java_transaction_qualification import configuration as cfg, evidence, lifecycle


ACTOR = "administrator:recovery:sha256:ab6a35565784ad10d26879d1e7fc015ddf100baf7395ec1a3c75b393ca0b26dd"
SCHEMA = "sha256:" + "a" * 64
PUBLICATION = "publication:sha256:" + "b" * 64


def reply():
    return {"outcomeKnown": True, "data": {
        "receipt": {"operationId": "java-create", "authenticatedOperator": ACTOR,
                    "stateSchema": SCHEMA},
        "auditAcknowledgement": {"status": "AUDIT_ACK_STATUS_DURABLE"}}}


class NamespaceActorOracle(unittest.TestCase):
    def test_operator_actor_matches_actual_original_caller_framing(self):
        self.assertEqual(lifecycle.operator_actor(), ACTOR)
        for name, value in (("TENANT", "foreign"), ("OPERATOR", "another-operator")):
            with self.subTest(name=name), patch.object(cfg, name, value):
                self.assertNotEqual(lifecycle.operator_actor(), ACTOR)

    def test_create_retains_exact_scoped_actor_schema_operation_and_audit_checks(self):
        class Client:
            def __init__(self, root, result):
                self.directory, self.result, self.calls = root, result, []
                self.evidence = evidence.Evidence(root / "evidence")

            def call(self, *args):
                self.calls.append(args)
                return self.result

        for change in (None, "bare-subject", "foreign-actor", "kind", "schema", "operation", "audit", "unknown"):
            with self.subTest(change=change), tempfile.TemporaryDirectory() as temporary:
                value = copy.deepcopy(reply())
                receipt = value["data"]["receipt"]
                if change == "bare-subject":
                    receipt["authenticatedOperator"] = cfg.OPERATOR
                elif change == "foreign-actor":
                    with patch.object(cfg, "TENANT", "foreign"):
                        receipt["authenticatedOperator"] = lifecycle.operator_actor()
                elif change == "kind":
                    receipt["authenticatedOperator"] = ACTOR.replace("administrator:", "user:", 1)
                elif change == "schema":
                    receipt["stateSchema"] = "sha256:" + "c" * 64
                elif change == "operation":
                    receipt["operationId"] = "other-create"
                elif change == "audit":
                    value["data"]["auditAcknowledgement"] = None
                elif change == "unknown":
                    value["outcomeKnown"] = False
                client = Client(Path(temporary), value)
                with patch.object(lifecycle, "schema", return_value=SCHEMA):
                    if change is None:
                        self.assertEqual(lifecycle.create_namespace(client, object(), PUBLICATION), receipt)
                        self.assertEqual(len(client.evidence.cases), 1)
                    else:
                        with self.assertRaisesRegex(ValueError, "actual-authorized-namespace-create"):
                            lifecycle.create_namespace(client, object(), PUBLICATION)
                        self.assertEqual(len(client.evidence.cases), 0)
                self.assertEqual(len(client.calls), 1)
                self.assertEqual(client.calls[0][:2], ("state", "create"))


class OfflineQuiesceActorOracle(unittest.TestCase):
    def test_offline_quiesce_keeps_exact_scoped_actor_operation_audit_and_retirement_order(self):
        from types import SimpleNamespace
        from tools.java_transaction_qualification.offline_campaign import OfflineCampaign
        for change in (None, "bare-subject", "foreign-tenant", "kind", "operation", "audit", "unknown"):
            with self.subTest(change=change):
                operation = "original-offline-quiesce"
                value = {"outcomeKnown": True, "data": {"receipt": {
                    "operationId": operation, "authenticatedOperator": ACTOR},
                    "auditAcknowledgement": {"status": "AUDIT_ACK_STATUS_DURABLE"}}}
                receipt = value["data"]["receipt"]
                if change == "bare-subject":
                    receipt["authenticatedOperator"] = cfg.OPERATOR
                elif change == "foreign-tenant":
                    with patch.object(cfg, "TENANT", "foreign"):
                        receipt["authenticatedOperator"] = lifecycle.operator_actor()
                elif change == "kind":
                    receipt["authenticatedOperator"] = ACTOR.replace("administrator:", "user:", 1)
                elif change == "operation":
                    receipt["operationId"] = "other-operation"
                elif change == "audit":
                    value["data"]["auditAcknowledgement"] = None
                elif change == "unknown":
                    value["outcomeKnown"] = False
                events, calls = [], []
                subject = OfflineCampaign.__new__(OfflineCampaign)
                subject.client = SimpleNamespace(call=lambda *args: (calls.append(args), value)[1],
                    evidence=SimpleNamespace(passed=lambda *_: events.append("receipt")))
                subject.node = SimpleNamespace(stop=lambda: events.append("stop"))
                with patch.object(lifecycle, "inspect_namespace", return_value={"generation": "2"}), \
                        patch.object(lifecycle, "admission_lease_interval", side_effect=lambda _: events.append("lease")):
                    if change is None:
                        subject.quiesce(PUBLICATION, operation)
                        self.assertEqual(events, ["receipt", "stop", "lease"])
                    else:
                        with self.assertRaisesRegex(ValueError, "actual-current-authorized-quiesce"):
                            subject.quiesce(PUBLICATION, operation)
                        self.assertEqual(events, [])
                self.assertEqual(len(calls), 1)
                self.assertEqual(calls[0][-4:], ("--operation-id", operation, "--expected-generation", "2"))


if __name__ == "__main__":
    unittest.main()
