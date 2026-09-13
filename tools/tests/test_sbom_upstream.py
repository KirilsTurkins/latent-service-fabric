"""Pinned upstream conformance and limits of CycloneDX schema validation."""
from __future__ import annotations

import copy
import hashlib
import json
import unittest

from referencing.exceptions import NoSuchResource

from tools.tests.sbom_schema_support import UPSTREAM, no_remote_resource, upstream_validator


def document():
    return {
        "bomFormat": "CycloneDX", "specVersion": "1.6", "version": 1,
        "metadata": {"component": {"type": "application", "name": "schema-example"}},
        "components": [{"type": "library", "name": "dependency", "version": "1.0.0"}],
    }


class SbomUpstreamSchemaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.validator = upstream_validator()

    def test_declared_expression_and_named_license_are_upstream_valid(self):
        for license_choice in (
            {"expression": "MIT OR Apache-2.0", "acknowledgement": "declared"},
            {"license": {"name": "Example supplied custom license", "acknowledgement": "declared"}},
        ):
            sample = document()
            sample["components"][0]["licenses"] = [license_choice]
            self.validator.validate(sample)
            invalid = copy.deepcopy(sample)
            invalid["components"][0]["licenses"][0]["extra"] = True
            self.assertFalse(self.validator.is_valid(invalid))

    def test_local_transitive_id_schema_and_rejected_unknown_resources(self):
        sample = document()
        sample["components"][0]["licenses"] = [{"license": {"id": "MIT"}}]
        self.validator.validate(sample)
        sample["components"][0]["licenses"][0]["license"]["id"] = "unrecognized-license"
        self.assertFalse(self.validator.is_valid(sample))
        with self.assertRaises(NoSuchResource):
            no_remote_resource("https://example.invalid/never-fetched.schema.json")

    def test_component_version_has_a_real_upstream_ceiling(self):
        for size in (1024, 1025):
            sample = document()
            sample["components"][0]["version"] = "v" * size
            self.assertEqual(self.validator.is_valid(sample), size == 1024)

    def test_producer_identifier_subset_has_pinned_license_only_identity(self):
        raw = (UPSTREAM / "spdx-license-ids.json").read_bytes()
        self.assertEqual(hashlib.sha256(raw).hexdigest(),
                         "27f8b5e7c6feae722d7947ac30182dc33ce9235ac7932ccdf5ba86156892c372")
        output = json.loads(raw)
        self.assertEqual(output["licenseListVersion"], "3.23")
        self.assertEqual(output["parserVersion"], "spdx-0.13.5")
        ids = output["licenses"]
        self.assertEqual(ids, sorted(set(ids)))
        self.assertEqual(len(ids), 605)
        allowed = json.loads((UPSTREAM / "spdx.schema.json").read_bytes())["enum"]
        self.assertLessEqual(set(ids), set(allowed))
        self.assertLessEqual({"MIT", "Apache-2.0", "GPL-2.0-only"}, set(ids))
        self.assertFalse({"Linux-syscall-note", "GPL-CC-1.0", "389-exception", "GPL-2.0", "Net-SNMP"} & set(ids))
        provenance = json.loads((UPSTREAM / "SPDX-DERIVATION.json").read_bytes())
        self.assertEqual(provenance["output"], {
            "path": "spdx-license-ids.json", "bytes": len(raw),
            "sha256": hashlib.sha256(raw).hexdigest(), "licenses": len(ids),
        })
        self.assertEqual(provenance["classificationSource"]["sha256"],
                         "2eb4b4253ada6af3f24c72e9d716ff0ab5ddb8f8a58c3cb3e2708b69a50f144b")
        self.assertEqual(provenance["parserSource"]["sha256"],
                         "8f53921a86dfecda6092980d1c12dd99ae5132e6692ab45f45a4e23b779ea48e")

    def test_upstream_does_not_replace_license_or_digest_semantics(self):
        sample = document()
        sample["components"][0]["licenses"] = [{"expression": "not an SPDX expression"}]
        # Upstream accepts string expressions and generic hash lengths. The
        # stricter LSF schema/codec must enforce their actual supported meanings.
        sample["components"][0]["hashes"] = [{"alg": "SHA-256", "content": "a" * 32}]
        self.validator.validate(sample)


if __name__ == "__main__":
    unittest.main()
