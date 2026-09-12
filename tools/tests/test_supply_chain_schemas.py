"""Closed admission inputs; these synthetic policy samples grant no authority."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import unittest

from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from tools.tests.test_build_provenance_schemas import samples as provenance_samples
from tools.tests.test_publisher_trust_schemas import policy, revocations

ROOT = Path(__file__).resolve().parents[2]


def upload():
    evidence = {"manifest": "e30=", "configuration": "e30=", "payload": "e30="}
    return {"package": {"manifest": "e30=", "configuration": "e30=",
                        "layers": [{"path": "component.wasm", "data": "AA=="}],
                        "signatures": [copy.deepcopy(evidence)],
                        "provenance": [copy.deepcopy(evidence)], "sboms": []}}


def supply_chain_policy():
    builder = provenance_samples()
    value = {"formatVersion": 1, "generation": 1, "scope": "test:admission",
             "validFrom": 1000, "validUntil": 2000,
             "tenants": [{"tenant": "acme", "publishers": ["openssl-test-publisher"]}],
             "publisher": policy(), "publisherRevocations": revocations(),
             "builder": builder["builder-policy"],
             "builderRevocations": builder["builder-revocations"],
             "sbom": {"formatVersion": 1, "embedded": "required", "detached": "optional",
                      "requireSource": [], "requireLicense": []}}
    for key in ("publisher", "publisherRevocations", "builder", "builderRevocations"):
        value[key]["scope"] = value["scope"]
    return value


class SupplyChainSchemaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        resources = []
        schemas = {}
        for name in ("package-admission-upload", "supply-chain-policy", "publisher-policy",
                     "publisher-revocations", "builder-policy", "builder-revocations", "package-sbom-policy",
                     "package-admission-receipt", "node-supply-chain"):
            schema = json.loads((ROOT / f"schemas/{name}.schema.json").read_bytes())
            Draft202012Validator.check_schema(schema)
            resources.append((schema["$id"], Resource.from_contents(schema)))
            schemas[name] = schema
        registry = Registry().with_resources(resources)
        cls.validators = {name: Draft202012Validator(schema, registry=registry)
                          for name, schema in schemas.items()}

    def test_required_inputs_and_closed_authority_boundary(self):
        for name, original in (("package-admission-upload", upload()),
                               ("supply-chain-policy", supply_chain_policy())):
            validator = self.validators[name]
            validator.validate(original)
            for key in original:
                changed = copy.deepcopy(original)
                del changed[key]
                self.assertFalse(validator.is_valid(changed), key)
            for key in ("artifact", "release", "admitted", "trusted", "privateKey"):
                changed = copy.deepcopy(original)
                changed[key] = True
                self.assertFalse(validator.is_valid(changed), key)

    def test_upload_evidence_and_binary_projection_are_closed_and_bounded(self):
        validator = self.validators["package-admission-upload"]
        for field in ("manifest", "configuration", "layers", "signatures", "provenance", "sboms"):
            value = upload()
            del value["package"][field]
            self.assertFalse(validator.is_valid(value), field)
        for key, invalid in (("manifest", "bad?"), ("configuration", ""), ("layers", []),
                             ("signatures", [upload()["package"]["signatures"][0]] * 9)):
            value = upload()
            value["package"][key] = invalid
            self.assertFalse(validator.is_valid(value), key)
        for field in ("manifest", "configuration", "payload"):
            value = upload()
            del value["package"]["signatures"][0][field]
            self.assertFalse(validator.is_valid(value), field)
        value = upload()
        value["package"]["signatures"][0]["configuration"] = "bnVsbA=="
        self.assertFalse(validator.is_valid(value))
        value = upload()
        value["package"]["layers"][0]["data"] = ""
        validator.validate(value)  # Empty asset bytes are format-valid; role semantics are separate.

    def test_policy_requires_every_snapshot_and_bounds_tenant_authorization(self):
        validator = self.validators["supply-chain-policy"]
        for field in ("publisher", "publisherRevocations", "builder", "builderRevocations", "sbom"):
            value = supply_chain_policy()
            value[field] = None
            self.assertFalse(validator.is_valid(value), field)
        for field, invalid in (("generation", 0), ("scope", "invalid scope"), ("validUntil", -1)):
            value = supply_chain_policy()
            value[field] = invalid
            self.assertFalse(validator.is_valid(value), field)
        value = supply_chain_policy()
        value["tenants"][0]["publishers"] *= 2
        self.assertFalse(validator.is_valid(value))
        value = supply_chain_policy()
        value["tenants"] = [{"tenant": f"tenant-{index}", "publishers": []} for index in range(129)]
        self.assertFalse(validator.is_valid(value))
        value = supply_chain_policy()
        value["publisher"]["keys"] *= 65
        self.assertFalse(validator.is_valid(value))
        value = supply_chain_policy()
        value["tenants"] = []
        validator.validate(value)  # Explicit deny-all is different from missing configuration.
        value = supply_chain_policy()
        value["scope"] = "admission@node/v1"
        for key in ("publisher", "publisherRevocations", "builder", "builderRevocations"):
            value[key]["scope"] = value["scope"]
        value["tenants"] = [{"tenant": "tenant@example", "publishers": ["publisher@example"]}]
        value["builder"]["keys"][0]["builderId"] = "build@source/v1"
        value["builder"]["requirements"][0]["builderId"] = "build@source/v1"
        validator.validate(value)

    def test_node_modes_do_not_allow_an_implicit_enforced_fallback(self):
        validator = self.validators["node-supply-chain"]
        validator.validate({"mode": "trusted-local"})
        validator.validate({"mode": "enforced", "policyFile": "admission-policy.json"})
        for seconds in (1, 5):
            validator.validate({"mode": "enforced", "policyFile": "policy.json", "clockLeaseSeconds": seconds})
        for value in ({}, {"mode": "enforced"}, {"mode": "unknown"},
                      {"mode": "trusted-local", "policyFile": "ignored.json"},
                      {"mode": "enforced", "policyFile": ""},
                      *({"mode": "enforced", "policyFile": "policy.json", "clockLeaseSeconds": seconds}
                        for seconds in (0, 6, 1.5))):
            self.assertFalse(validator.is_valid(value), value)

    def test_historical_receipt_has_closed_identities_and_explicit_nullable_sbom(self):
        digest = "sha256:" + "a" * 64
        generation = {"generation": 1, "digest": digest}
        policy_identity = {"generation": 1, "scope": "test", "validFrom": 1, "validUntil": 2000,
                           "tenantsDigest": digest, "publisher": generation,
                           "publisherRevocations": generation, "builder": generation,
                           "builderRevocations": generation, "sbomDigest": digest}
        value = {"formatVersion": 1, "disposition": "admitted", "tenant": "acme", "package": digest,
                 "release": digest, "publisher": "test:publisher", "publisherKey": digest,
                 "signatureManifest": digest, "signaturePayload": digest, "builder": "test:builder",
                 "builderKey": digest, "provenanceManifest": digest, "provenancePayload": digest,
                 "sbomInventory": None, "sbomReferrer": None, "policy": policy_identity,
                 "policyDigest": digest, "epoch": 1, "verifiedAt": 1000, "validUntil": 1100}
        validator = self.validators["package-admission-receipt"]
        validator.validate(value)
        for field in value:
            changed = copy.deepcopy(value)
            del changed[field]
            self.assertFalse(validator.is_valid(changed), field)
        for field, invalid in (("epoch", 0), ("disposition", "eligible"), ("package", "sha256:invalid"),
                               ("sbomInventory", True), ("admitted", True)):
            changed = copy.deepcopy(value)
            changed[field] = invalid
            self.assertFalse(validator.is_valid(changed), field)


if __name__ == "__main__":
    unittest.main()
