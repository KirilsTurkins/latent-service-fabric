"""Protocol-owner/presence regressions; compiler and node execution are separate."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import unittest

from tools.transaction_client_models import derive, qualify_external, render

ROOT = Path(__file__).resolve().parents[2]


def fixture():
    field = {"name": "page", "jsonName": "page", "number": 1, "label": "LABEL_OPTIONAL",
             "type": "TYPE_MESSAGE", "typeName": ".latent.transaction.v1.PageRequest"}
    image = {"file": [
        {"name": "transaction.proto", "package": "latent.transaction.v1", "messageType": [
            {"name": "Request", "field": [field]}, {"name": "Response"}, {"name": "PageRequest"}],
         "service": [{"name": "TransactionService", "method": [{"name": "Call", "inputType": ".latent.transaction.v1.Request", "outputType": ".latent.transaction.v1.Response"}]}]},
        {"name": "common.proto", "package": "latent.control.v1", "messageType": [{"name": "PageRequest"}]},
    ]}
    requirements = {"wireProfile": "lsf-transaction-v1", "hostAbiDigest": "sha256:wire",
                    "preparationProfileDigest": "sha256:prepare", "externalClient": {
        "profile": "latent.transaction-client.v1", "requiredServices": [{
            "source": "api/proto/transaction.proto", "sourceSha256": "sha256:source",
            "service": "latent.transaction.v1.TransactionService", "messages": ["Request", "Response", "PageRequest"], "enums": [],
            "operations": [{"name": "Call", "request": "Request", "response": "Response"}]}]}}
    legacy = {"sources": {"api/proto/common.proto": ["PageRequest"]}}
    return image, requirements, legacy, {"PageRequest": []}, {}


class TransactionClientModelTests(unittest.TestCase):
    def test_paging_uses_exact_protobuf_owner_and_rejects_an_external_alias(self):
        args = fixture()
        contract = derive(*args)
        self.assertEqual(contract["messages"]["Request"][0]["wireType"], ".latent.transaction.v1.PageRequest")
        self.assertFalse(contract["externalClientExecutionQualified"])
        bad = copy.deepcopy(args)
        bad[0]["file"][0]["messageType"][0]["field"][0]["typeName"] = ".latent.control.v1.PageRequest"
        with self.assertRaisesRegex(ValueError, "external owner cannot alias"):
            derive(*bad)

    def test_future_external_package_cannot_reuse_an_approved_short_name(self):
        args = copy.deepcopy(fixture())
        args[0]["file"][0]["messageType"][0]["field"][0]["typeName"] = ".future.control.v1.PageRequest"
        with self.assertRaisesRegex(ValueError, "unreviewed external transaction model owner"):
            derive(*args)

    def test_qualification_preserves_go_fields_and_dotnet_record_properties(self):
        contract = {"externalTypes": ["Success", "AuditAck"]}
        go = qualify_external("type Outcome struct {\n\tSuccess *Success\n\tAuditAck *AuditAck\n}\n", contract, "go")
        self.assertIn("\tSuccess *profile.Success", go)
        self.assertIn("\tAuditAck *profile.AuditAck", go)
        dotnet = qualify_external("public sealed record Outcome(Success? Success, AuditAck? AuditAck);", contract, "dotnet")
        self.assertEqual(dotnet, "public sealed record Outcome(global::Latent.Sdk.Profile.Success? Success, global::Latent.Sdk.Profile.AuditAck? AuditAck);")

    def test_all_six_models_preserve_optional_full_width_preconditions_and_protocol_data(self):
        contract = json.loads((ROOT / "sdk/profile/transaction-client-contract.json").read_bytes())
        fields = {field["name"]: field for field in contract["messages"]["MutateNamespaceRequest"]}
        self.assertTrue(fields["expected_generation"]["optional"])
        self.assertEqual(fields["expected_generation"]["type"], "uint64")
        for language in ("rust", "c", "typescript", "go", "java", "dotnet"):
            with self.subTest(language=language):
                source = render(contract, language)
                self.assertIn(contract["hostAbiDigest"], source)
                self.assertIn(contract["preparationProfileDigest"], source)
                self.assertNotIn("autoRetry", source)
                self.assertNotIn("implicitRetry", source)
        self.assertIn("bigint", render(contract, "typescript"))


if __name__ == "__main__":
    unittest.main()
