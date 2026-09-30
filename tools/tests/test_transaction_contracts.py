"""Shared guest/client/HTTP boundaries; these checks do not execute an engine."""
from __future__ import annotations

import base64
import copy
import json
from pathlib import Path
import re
import unittest

from jsonschema import Draft202012Validator
from tools.generate_transaction_contracts import matrix, vectors
from tools.transaction_contracts import bytes_value, command_identity, content, digest, fingerprint, identity, metadata, unsigned64

ROOT = Path(__file__).resolve().parents[2]


class TransactionContractsTests(unittest.TestCase):
    def test_exact_generated_matrix_and_vectors_have_no_execution_claim(self):
        self.assertEqual(matrix(), json.loads((ROOT / "wit/host-abi-phase4-v1.json").read_text()))
        self.assertEqual(vectors(), json.loads((ROOT / "sdk/profile/transaction-vectors.json").read_text()))
        self.assertFalse(vectors()["executionQualified"])
        self.assertTrue(all(not item["installed"] for item in matrix()["interfaces"] if item["binding"] == "provider"))

    def test_profile_exact_sources_owned_resources_and_stateless_default(self):
        value = matrix()
        schema = json.loads((ROOT / "schemas/host-abi-profile.schema.json").read_text())
        Draft202012Validator(schema).validate(value)
        state = (ROOT / "wit/platform/state/package.wit").read_text()
        self.assertNotRegex(state, r"\b(?:begin|commit|rollback|constructor)\s*[:(]")
        self.assertEqual(set(re.findall(r"resource ([a-z-]+);", state)), {"transaction", "query-view", "page"})
        self.assertIn("pub const PHASE3_HOST_ABI_CURRENT: HostAbiProfile = PHASE3_HOST_ABI_V4;",
                      (ROOT / "crates/latent-core/src/host_profile.rs").read_text())
        self.assertIn("borrow<transaction>", (ROOT / "wit/platform/intents/package.wit").read_text())

    def test_full_width_unsigned_json_never_uses_numbers_or_coerces(self):
        for value in vectors()["unsigned64"]:
            self.assertEqual(unsigned64(value), int(value))
        for value in vectors()["invalidUnsigned64"] + [0, True, None, "1.0", " 1"]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                unsigned64(value)

    def test_identity_presence_and_utf8_bytes_are_exact(self):
        self.assertEqual(identity("é" * 128), ("é" * 128).encode())
        for value in (None, "", "x\0y", "é" * 129, "\ud800"):
            with self.subTest(value=repr(value)), self.assertRaises(ValueError):
                identity(value)

    def test_base64_empty_present_and_exact_maximum_are_distinct(self):
        self.assertEqual(bytes_value("", 1024), b"")
        self.assertEqual(bytes_value(base64.b64encode(b"a" * 1024).decode(), 1024), b"a" * 1024)
        for value, maximum, nonempty in (("", 1024, True), ("YQ", 1024, False), ("YR==", 1024, False),
                ("YQ==\n", 1024, False), (None, 1024, False), ("YWE=", 1, False)):
            with self.subTest(value=value), self.assertRaises(ValueError):
                bytes_value(value, maximum, nonempty=nonempty)

    def test_metadata_is_bounded_unique_and_does_not_flatten_empty_values(self):
        self.assertEqual(metadata([["key", ""]]), [(b"key", b"")])
        for value in ([["key", "a"], ["key", "b"]], [["x", "é" * 513]], [[str(i), ""] for i in range(33)],
                      [[str(i), "x" * 1024] for i in range(9)], [["", "value"]]):
            with self.subTest(value=value[:1]), self.assertRaises(ValueError):
                metadata(value)

    def test_command_and_fingerprint_exact_known_frames_share_one_identity_vocabulary(self):
        value = vectors()
        for item in value["identities"]:
            actual = command_identity(item["value"])
            self.assertEqual(actual.hex(), item["framedHex"])
            self.assertEqual(digest(actual), item["sha256"])
        self.assertEqual(len(set(item["sha256"] for item in value["identities"])), len(value["identities"]))
        for item in value["fingerprints"]:
            actual = fingerprint(item["value"])
            self.assertEqual(actual.hex(), item["framedHex"])
            self.assertEqual(digest(actual), item["sha256"])

    def test_invalid_precondition_presence_and_unknown_values_reject(self):
        original = vectors()["fingerprints"][0]["value"]
        for condition in ({"key": "YQ==", "absent": False}, {"key": "YQ==", "version": ""},
            {"key": "YQ=="}, {"key": "YQ==", "absent": True, "version": "Yg=="}):
            value = copy.deepcopy(original)
            value["expectedVersions"] = [condition]
            with self.subTest(condition=condition), self.assertRaises(ValueError):
                fingerprint(value)
        value = copy.deepcopy(original)
        value["expectedVersions"] = [{"key": "YQ==", "absent": True}] * 2
        with self.assertRaises(ValueError):
            fingerprint(value)

    def test_http_command_query_recovery_profiles_are_distinct_and_fail_closed(self):
        schema = json.loads((ROOT / "schemas/transaction-api.schema.json").read_text())
        validator = Draft202012Validator(schema)
        common = dict(profile="lsf-transaction-v1", namespace="app", incarnation="i1", operation="save")
        input_value = dict(bytes="", mediaType="application/octet-stream", metadata=[])
        query = {**common, "kind": "query", "input": input_value}
        command = {**common, "kind": "command", "clientKey": "one", "inputFormat": "raw-v1", "input": input_value, "expectedVersions": []}
        recovery = {**common, "kind": "recovery", "clientKey": "one"}
        for value in (query, command, recovery):
            validator.validate(value)
        for value in ({**query, "clientKey": "one"}, {**command, "clientKey": ""}, {**command, "profile": "future"},
                      {**command, "expectedVersions": [{"key": "YQ==", "absent": False}]}, {**recovery, "management": True}):
            with self.subTest(value=value):
                self.assertFalse(validator.is_valid(value))

    def test_independent_durable_formats_and_unknown_version_rejection(self):
        schema = json.loads((ROOT / "schemas/transaction-durable-record.schema.json").read_text())
        validator = Draft202012Validator(schema)
        for name in schema["properties"]["recordFormat"]["enum"]:
            value = dict(recordFormat=name, recordVersion=1, recordId="one", namespaceIncarnation="i1", payload="", payloadFormat="raw-v1", linkedRecords=[])
            validator.validate(value)
            self.assertFalse(validator.is_valid({**value, "recordVersion": 2}))
        self.assertEqual(len(schema["properties"]["recordFormat"]["enum"]), 5)

    def test_companion_rejects_workflow_cluster_modes_and_unknown_authority(self):
        schema = json.loads((ROOT / "schemas/transaction-binding.schema.json").read_text())
        validator = Draft202012Validator(schema)
        value = dict(apiVersion="latent.dev/v1", kind="TransactionBinding", capsule="capsule", deployment="deployment", binding="binding",
            profile="lsf-transaction-v1", hostAbiDigest=matrix()["digest"], namespace="app", stateSchema="sha256:" + "1" * 64,
            operations=[dict(operation="save", mode="strict-command", inputFormat="raw-v1", resultFormat="result-v1")])
        validator.validate(value)
        for mode in ("cluster", "workflow", "historical-query"):
            invalid = copy.deepcopy(value)
            invalid["operations"][0]["mode"] = mode
            self.assertFalse(validator.is_valid(invalid))
        self.assertFalse(validator.is_valid({**value, "authority": "admin"}))

if __name__ == "__main__":
    unittest.main()
