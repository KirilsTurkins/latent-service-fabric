"""Opt-in checks for research assets; no production schema registration."""
import copy
import json
from pathlib import Path
import re
import unittest
import tempfile

import run as evidence_runner

from jsonschema import Draft202012Validator, ValidationError

ROOT = Path(__file__).resolve().parent


class ContractTests(unittest.TestCase):
    def setUp(self):
        self.schema = json.loads((ROOT / "grant.schema.json").read_text())
        self.example = json.loads((ROOT / "grant.example.json").read_text())
        self.validator = Draft202012Validator(self.schema)

    def test_disabled_example_and_schema(self):
        Draft202012Validator.check_schema(self.schema)
        self.validator.validate(self.example)

    def test_no_enablement_or_http_authority_substitution(self):
        for field, value in (("enabled", True), ("capability", "http"),
                             ("profile", "bounded-http-v1"), ("epoch", 0),
                             ("retry", True), ("listeners", [])):
            with self.subTest(field=field):
                changed = copy.deepcopy(self.example)
                changed[field] = value
                with self.assertRaises(ValidationError):
                    self.validator.validate(changed)

    def test_unknown_and_unbounded_inputs_rejected(self):
        for field, value in (("activationConnections", 3), ("queuedCalls", 1),
                             ("chunkBytes", 0), ("absoluteMillis", 10001),
                             ("totalBytesPerDirection", 1048577)):
            with self.subTest(field=field):
                changed = copy.deepcopy(self.example)
                changed["limits"][field] = value
                with self.assertRaises(ValidationError):
                    self.validator.validate(changed)
        changed = copy.deepcopy(self.example)
        changed["destinations"][0]["ports"] = [0]
        with self.assertRaises(ValidationError):
            self.validator.validate(changed)

    def test_tls_requires_explicit_trust_no_insecure_fallback(self):
        changed = copy.deepcopy(self.example)
        tls = {"mode": "host-tls", "serverName": "mail.test",
               "rootBundleDigest": "sha256:" + "a" * 64}
        changed["destinations"][0]["tls"] = tls
        self.validator.validate(changed)
        tls["insecureSkipVerify"] = True
        with self.assertRaises(ValidationError):
            self.validator.validate(changed)
        del tls["insecureSkipVerify"]
        del tls["rootBundleDigest"]
        with self.assertRaises(ValidationError):
            self.validator.validate(changed)

    def test_acceptance_map_points_to_existing_sources_and_tests(self):
        mapping = json.loads((ROOT / "requirements.json").read_text())
        self.assertEqual([r["criterion"] for r in mapping], list(range(1, 10)))
        tests = set(re.findall(r"func (Test\w+)\(", (ROOT / "gateway_test.go").read_text()))
        for row in mapping:
            for path in row["sources"]:
                self.assertTrue((ROOT / path).is_file(), path)
            for test in row["tests"]:
                self.assertIn(test, tests)
        # A text assertion is NOT a WIT parser or component conformance test.
        wit = (ROOT / "streams.wit").read_text()
        self.assertIn("package latent-research:outbound-streams@0.1.0;", wit)
        self.assertNotIn("listen:", wit)
        # Verification is source-sensitive and refuses path traversal.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "case.go"
            source.write_text("original")
            receipt = {"status": "passed", "sources": {"case.go": evidence_runner.digest(source)},
                       "commands": [{"exitCode": 0}]}
            evidence_runner.verify_sources(receipt, root)
            source.write_text("edited")
            with self.assertRaises(ValueError):
                evidence_runner.verify_sources(receipt, root)
            receipt["sources"] = {"../outside": "0" * 64}
            with self.assertRaises(ValueError):
                evidence_runner.verify_sources(receipt, root)


if __name__ == "__main__":
    unittest.main()
