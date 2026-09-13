"""Strict publisher-trust shapes and an independently signed public fixture."""

from __future__ import annotations

import base64
import copy
import hashlib
import json
from pathlib import Path
import unittest

from jsonschema import Draft202012Validator


ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "crates/latent-signing/tests/fixtures"
U64_MAX = 2**64 - 1


def policy() -> dict:
    return {
        "formatVersion": 1, "scope": "test:publisher", "generation": 1,
        "validFrom": 1000, "validUntil": 2000,
        "maxSignatureLifetimeSeconds": 1000, "maxProofAgeSeconds": 60,
        "keys": [{
            "publisherId": "openssl-test-publisher",
            "publicKey": (FIXTURES / "openssl-public-key.txt").read_text().strip(),
            "validFrom": 1000, "validUntil": 2000,
        }],
    }


def revocations() -> dict:
    return {
        "formatVersion": 1, "scope": "test:publisher", "generation": 1,
        "policyDigest": "sha256:" + "a" * 64, "validFrom": 1000,
        "validUntil": 2000, "revokedKeys": [], "revokedPublishers": [],
    }


class PublisherTrustSchemaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.validators = {}
        for name in ("package-signature", "package-signature-claims",
                     "publisher-policy", "publisher-revocations"):
            schema = json.loads((ROOT / f"schemas/{name}.schema.json").read_bytes())
            Draft202012Validator.check_schema(schema)
            cls.validators[name] = Draft202012Validator(schema)

    def invalid(self, name: str, value: dict) -> None:
        self.assertFalse(self.validators[name].is_valid(value), name)

    def test_external_signature_fixture_exact_association(self) -> None:
        claims_bytes = (FIXTURES / "openssl-claims.json").read_bytes()
        claims = json.loads(claims_bytes)
        envelope = json.loads((FIXTURES / "openssl-envelope.json").read_bytes())
        self.validators["package-signature"].validate(envelope)
        self.validators["package-signature-claims"].validate(claims)
        public_key = base64.b64decode(policy()["keys"][0]["publicKey"], validate=True)
        signature = envelope["signatures"][0]
        self.assertEqual(base64.b64decode(envelope["payload"], validate=True), claims_bytes)
        self.assertEqual(len(public_key), 32)
        self.assertEqual(len(base64.b64decode(signature["sig"], validate=True)), 64)
        self.assertEqual(signature["keyid"], "sha256:" + hashlib.sha256(public_key).hexdigest())
        manifest = (ROOT / "examples/package-format/browser-assets/manifest.json").read_bytes()
        self.assertEqual(claims["subject"]["digest"], "sha256:" + hashlib.sha256(manifest).hexdigest())
        self.assertEqual(claims["subject"]["size"], len(manifest))

    def test_every_structural_field_is_required_and_unknown_fields_are_rejected(self) -> None:
        samples = {
            "package-signature": json.loads((FIXTURES / "openssl-envelope.json").read_bytes()),
            "package-signature-claims": json.loads((FIXTURES / "openssl-claims.json").read_bytes()),
            "publisher-policy": policy(), "publisher-revocations": revocations(),
        }
        for name, original in samples.items():
            self.validators[name].validate(original)
            for field in original:
                with self.subTest(schema=name, missing=field):
                    changed = copy.deepcopy(original)
                    del changed[field]
                    self.invalid(name, changed)
            changed = copy.deepcopy(original)
            changed["trusted"] = True
            self.invalid(name, changed)
        for parent, name in ((samples["package-signature"]["signatures"][0], "algorithm"),
                             (samples["package-signature-claims"]["subject"], "tenantId"),
                             (samples["publisher-policy"]["keys"][0], "role")):
            parent[name] = "unsupported"
        for name in ("package-signature", "package-signature-claims", "publisher-policy"):
            self.invalid(name, samples[name])

    def test_envelope_has_one_signature_and_canonical_bounded_base64(self) -> None:
        original = json.loads((FIXTURES / "openssl-envelope.json").read_bytes())
        for signatures in ([], original["signatures"] * 2):
            self.invalid("package-signature", {**original, "signatures": signatures})
        for payload in ("", "AAA", "AA-A", "AA_A", "AB==", "AAB=", "AA==\n", "A" * 2736):
            self.invalid("package-signature", {**original, "payload": payload})
        self.invalid("package-signature", {**original, "payloadType": "application/json"})
        for sig in ("A" * 84 + "==", "A" * 85 + "B==", "A" * 88, "A" * 85 + "A=", "A" * 85 + "A==\n"):
            changed = copy.deepcopy(original)
            changed["signatures"][0]["sig"] = sig
            self.invalid("package-signature", changed)
        for digest in ("sha256:" + "A" * 64, "sha256:" + "a" * 63, "sha512:" + "a" * 64):
            changed = copy.deepcopy(original)
            changed["signatures"][0]["keyid"] = digest
            self.invalid("package-signature", changed)

    def test_unsigned_integer_and_identity_boundaries(self) -> None:
        for field in ("generation", "validFrom", "validUntil"):
            for invalid in (-1, U64_MAX + 1, True, None):
                self.invalid("publisher-policy", {**policy(), field: invalid})
        self.invalid("publisher-policy", {**policy(), "generation": 0})
        for field, maximum in (("maxSignatureLifetimeSeconds", 2678400), ("maxProofAgeSeconds", 3600)):
            self.validators["publisher-policy"].validate({**policy(), field: maximum})
            for invalid in (0, -1, maximum + 1):
                self.invalid("publisher-policy", {**policy(), field: invalid})
        for scope in ("", "space forbidden", "é", "x" * 129, "valid\n"):
            self.invalid("publisher-policy", {**policy(), "scope": scope})
        self.validators["publisher-policy"].validate({**policy(), "scope": "x" * 128})
        claims = json.loads((FIXTURES / "openssl-claims.json").read_bytes())
        for size in (0, 262145, -1):
            changed = copy.deepcopy(claims)
            changed["subject"]["size"] = size
            self.invalid("package-signature-claims", changed)

    def test_policy_key_shape_and_hard_array_ceiling(self) -> None:
        self.validators["publisher-policy"].validate({**policy(), "keys": []})
        self.validators["publisher-policy"].validate({**policy(), "keys": policy()["keys"] * 256})
        self.invalid("publisher-policy", {**policy(), "keys": policy()["keys"] * 257})
        for public_key in ("A" * 44, "A" * 42 + "B=", "A" * 42 + "A==", "A" * 42 + "A=\n"):
            changed = policy()
            changed["keys"][0]["publicKey"] = public_key
            self.invalid("publisher-policy", changed)

    def test_explicit_revocation_sets_reject_duplicates_and_overflow(self) -> None:
        for field, values in (
            ("revokedKeys", [f"sha256:{index:064x}" for index in range(256)]),
            ("revokedPublishers", [f"publisher-{index}" for index in range(256)]),
        ):
            self.validators["publisher-revocations"].validate({**revocations(), field: values})
            self.invalid("publisher-revocations", {**revocations(), field: values + values[:1]})
            self.invalid("publisher-revocations", {**revocations(), field: values[:1] * 2})
        self.invalid("publisher-revocations", {**revocations(), "policyDigest": "sha256:" + "A" * 64})


if __name__ == "__main__":
    unittest.main()
