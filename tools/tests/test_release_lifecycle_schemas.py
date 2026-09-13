"""Lifecycle storage and RPC projections are closed, bounded and distinct."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import unittest

from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from tools.tests.test_phase1_contracts import descriptor_file, field, load_descriptor_golden, message

ROOT = Path(__file__).resolve().parents[2]
BASE = "https://latent.dev/schemas/v1/"
DIGEST = "sha256:" + "a" * 64


def record():
    return {"scope": {"kind": "tenant", "tenant": "acme"}, "release": DIGEST,
            "package": None, "state": "admitted", "generation": 1,
            "actor": {"subject": "alice", "kind": "administrator"}, "reason": "admitted",
            "operationId": "create-1", "policy": None, "observedAtUnixMillis": None,
            "evidenceRevisionDigest": None}


def receipt():
    return {"operationId": "create-1", "requestDigest": DIGEST,
            "scope": {"kind": "tenant", "tenant": "acme"},
            "actor": {"subject": "alice", "kind": "administrator"}, "action": "publish",
            "disposition": "committed", "reason": "admitted", "componentDigest": DIGEST,
            "packageManifestDigest": None, "expectedGeneration": 0, "record": record(),
            "policy": None, "observedAtUnixMillis": None}


class ReleaseLifecycleSchemaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.schemas = {}
        for name in ("release-lifecycle-record", "release-operation-receipt",
                     "release-lifecycle-api", "package-admission-upload"):
            schema = json.loads((ROOT / f"schemas/{name}.schema.json").read_bytes())
            Draft202012Validator.check_schema(schema)
            cls.schemas[name] = schema
        cls.registry = Registry().with_resources(
            (schema["$id"], Resource.from_contents(schema)) for schema in cls.schemas.values())

    def validator(self, name):
        return Draft202012Validator(self.schemas[name], registry=self.registry)

    def api(self, name):
        return Draft202012Validator({"$ref": BASE + "release-lifecycle-api.schema.json#/$defs/" + name},
                                   registry=self.registry)

    def test_shared_rust_serializer_fixture_matches_both_schemas(self):
        fixture = json.loads((ROOT / "tools/tests/fixtures/release_lifecycle/pair.json").read_bytes())
        self.assertEqual(set(fixture), {"record", "receipt"})
        self.validator("release-lifecycle-record").validate(fixture["record"])
        self.validator("release-operation-receipt").validate(fixture["receipt"])
        self.assertEqual(fixture["receipt"]["record"], fixture["record"])
        self.assertEqual(fixture["record"]["observedAtUnixMillis"], 1_700_000_000_000)
        self.assertIsNone(fixture["record"]["package"])
        self.assertIsNone(fixture["record"]["policy"])

    def test_canonical_record_and_receipt_have_explicit_optional_fields(self):
        for name, sample in (("release-lifecycle-record", record()),
                             ("release-operation-receipt", receipt())):
            validator = self.validator(name)
            validator.validate(sample)
            for key in sample:
                changed = copy.deepcopy(sample)
                del changed[key]
                self.assertFalse(validator.is_valid(changed), (name, key))
            changed = copy.deepcopy(sample)
            changed["trusted"] = True
            self.assertFalse(validator.is_valid(changed))
        local = record()
        local["scope"] = {"kind": "local-unscoped"}
        local["actor"] = {"subject": "catalog-bootstrap", "kind": "host"}
        self.validator("release-lifecycle-record").validate(local)

    def test_state_and_operation_outcomes_do_not_fabricate_success(self):
        validator = self.validator("release-lifecycle-record")
        for state, reason in (("revoked", "security-incident"), ("retired", "superseded")):
            value = record()
            value.update(state=state, reason=reason)
            validator.validate(value)
            value["reason"] = "admitted"
            self.assertFalse(validator.is_valid(value))
        for invalid in (0, 2**64, -1):
            value = record()
            value["generation"] = invalid
            self.assertFalse(validator.is_valid(value))
        value = receipt()
        value.update(disposition="rejected", reason="invalid-package", record=None,
                     componentDigest=None, packageManifestDigest=DIGEST)
        self.validator("release-operation-receipt").validate(value)
        value["disposition"] = "committed"
        self.assertFalse(self.validator("release-operation-receipt").is_valid(value))

    def test_protobuf_generation_presence_and_exact_uint64_strings(self):
        validator = self.api("MutationPrecondition")
        for value in ("1", str(2**64 - 1)):
            validator.validate({"operationId": "known-operation", "expectedGeneration": value})
        for value in (None, 1, "0", "01", "-1", "1e2", "1\n", str(2**64), "9" * 21):
            self.assertFalse(validator.is_valid({"operationId": "known-operation", "expectedGeneration": value}), value)
        self.assertFalse(validator.is_valid({"operationId": "known-operation"}))
        for value in ("", "bad id", "known\n", "x" * 129):
            self.assertFalse(validator.is_valid({"operationId": value, "expectedGeneration": "1"}))

    def test_rpc_reasons_and_actor_authority_are_closed(self):
        validator = self.api("ChangeReleaseLifecycleRequest")
        value = {"digest": DIGEST, "action": "RELEASE_LIFECYCLE_ACTION_REVOKE",
                 "reason": "RELEASE_LIFECYCLE_REASON_SECURITY_INCIDENT",
                 "operation": {"operationId": "revoke-1", "expectedGeneration": "1"}}
        validator.validate(value)
        for key in ("actor", "tenant", "publisher", "admitted", "policy"):
            changed = copy.deepcopy(value)
            changed[key] = "forged"
            self.assertFalse(validator.is_valid(changed), key)
        for action in ("RELEASE_LIFECYCLE_ACTION_PUBLISH", "RELEASE_LIFECYCLE_ACTION_UNSPECIFIED", 2):
            changed = copy.deepcopy(value)
            changed["action"] = action
            self.assertFalse(validator.is_valid(changed))
        value["action"] = "RELEASE_LIFECYCLE_ACTION_RETIRE"
        self.assertFalse(validator.is_valid(value))

    def test_unknown_operation_status_is_not_a_committed_receipt(self):
        validator = self.api("GetReleaseOperationResponse")
        for lookup in ("UNKNOWN", "UNCERTAIN"):
            value = {"lookup": "RELEASE_OPERATION_LOOKUP_DISPOSITION_" + lookup}
            validator.validate(value)
            value["receipt"] = {}
            self.assertFalse(validator.is_valid(value))
        self.assertFalse(validator.is_valid({"lookup": "RELEASE_OPERATION_LOOKUP_DISPOSITION_FOUND"}))
        self.assertFalse(self.api("Record").is_valid(record()))  # distinct storage representation

    def test_additive_descriptor_preserves_existing_field_numbers(self):
        source = descriptor_file(load_descriptor_golden(), "latent/control/v1/release.proto")
        request = message(source, "PublishReleaseRequest")
        self.assertEqual({item["name"]: item["number"] for item in request["field"]},
                         {"release": 1, "artifact": 2, "package": 3, "operation": 4})
        self.assertEqual(field(message(source, "PublishReleaseResponse"), "operation")["number"], 3)
        self.assertEqual(field(message(source, "ReleaseDescriptor"), "admitted")["number"], 10)
        generation = field(message(source, "ReleaseOperationPrecondition"), "expected_generation")
        self.assertTrue(generation["proto3Optional"])
        service = next(item for item in source["service"] if item["name"] == "ReleaseService")
        self.assertEqual({item["name"] for item in service["method"]},
                         {"PublishRelease", "GetRelease", "ListReleases", "GetReleaseLifecycle",
                          "GetReleaseOperation", "ChangeReleaseLifecycle", "RenewReleaseEvidence"})


if __name__ == "__main__":
    unittest.main()
