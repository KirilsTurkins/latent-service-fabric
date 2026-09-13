"""Build-input receipt shapes; identities asserted here do not establish provenance."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import unittest

from jsonschema import Draft202012Validator


ROOT = Path(__file__).resolve().parents[2]
ABC_DIGEST = "sha256:ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
EMPTY_DIGEST = "sha256:e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"


def receipt() -> dict:
    return {
        "formatVersion": 1,
        "operation": "package-supplied-artifacts",
        "packager": "latent-packaging",
        "packagerVersion": "0.1.0-alpha.2",
        "inputs": [{
            "path": "asset.txt", "role": "asset",
            "inputDigest": ABC_DIGEST, "inputSize": 3,
            "outputDigest": ABC_DIGEST, "outputSize": 3,
        }],
    }


class PackageReceiptSchemaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        schema = json.loads((ROOT / "schemas/package-build-inputs.schema.json").read_bytes())
        Draft202012Validator.check_schema(schema)
        cls.validator = Draft202012Validator(schema)

    def assert_invalid(self, value: dict) -> None:
        self.assertFalse(self.validator.is_valid(value), repr(value))

    def test_known_hashes_and_real_recipe_inputs_have_valid_receipt_shapes(self) -> None:
        self.assertEqual("sha256:" + hashlib.sha256(b"abc").hexdigest(), ABC_DIGEST)
        self.assertEqual("sha256:" + hashlib.sha256(b"").hexdigest(), EMPTY_DIGEST)
        self.validator.validate(receipt())
        for kind in ("browser", "ssr"):
            directory = ROOT / "examples/package-inputs" / kind
            recipe = json.loads((directory / "package-source.json").read_bytes())
            value = receipt()
            value["inputs"] = []
            for layer in sorted(recipe["layers"], key=lambda item: item["path"]):
                data = (directory / layer["source"]).read_bytes()
                digest = "sha256:" + hashlib.sha256(data).hexdigest()
                value["inputs"].append({
                    "path": layer["path"], "role": layer["role"],
                    "inputDigest": digest, "inputSize": len(data),
                    "outputDigest": digest, "outputSize": len(data),
                })
            with self.subTest(kind=kind):
                self.validator.validate(value)

    def test_closed_receipt_and_input_objects_require_every_member(self) -> None:
        original = receipt()
        for field in original:
            changed = copy.deepcopy(original)
            del changed[field]
            self.assert_invalid(changed)
        for field in original["inputs"][0]:
            changed = copy.deepcopy(original)
            del changed["inputs"][0][field]
            self.assert_invalid(changed)
        for field in ("trusted", "provenance", "sourcePath", "unknown"):
            changed = receipt()
            changed[field] = "not authority"
            self.assert_invalid(changed)
            changed = receipt()
            changed["inputs"][0][field] = "not authority"
            self.assert_invalid(changed)

    def test_input_and_output_digests_require_complete_lowercase_sha256(self) -> None:
        invalid = ["", "a" * 64, "sha512:" + "a" * 64,
                   "sha256:" + "A" * 64, "sha256:" + "g" * 64,
                   "sha256:" + "a" * 63, "sha256:" + "a" * 65,
                   ABC_DIGEST + "\n", None, 123]
        for field in ("inputDigest", "outputDigest"):
            for digest in invalid:
                with self.subTest(field=field, digest=digest):
                    changed = receipt()
                    changed["inputs"][0][field] = digest
                    self.assert_invalid(changed)

    def test_input_identity_remains_a_separate_unverified_claim(self) -> None:
        value = receipt()
        value["inputs"][0].update(inputDigest=EMPTY_DIGEST, inputSize=0)
        self.validator.validate(value)
        # Schema validation deliberately cannot authenticate this input claim or
        # prove that the asserted transformation actually produced the output.
        self.assertNotEqual(value["inputs"][0]["inputDigest"], value["inputs"][0]["outputDigest"])

    def test_zero_bytes_are_allowed_only_for_asset_inputs_and_outputs(self) -> None:
        for role in ("component", "capsule-manifest", "contracts", "wit-lock", "renderer", "asset"):
            value = receipt()
            value["inputs"][0]["role"] = role
            self.validator.validate(value)
            for field in ("inputSize", "outputSize"):
                with self.subTest(role=role, field=field):
                    changed = copy.deepcopy(value)
                    changed["inputs"][0][field] = 0
                    if role == "asset":
                        self.validator.validate(changed)
                    else:
                        self.assert_invalid(changed)
        for field in ("inputSize", "outputSize"):
            for size in (-1, 67108865, 1.5, "3", True, None):
                value = receipt()
                value["inputs"][0][field] = size
                self.assert_invalid(value)

    def test_paths_reject_traversal_reserved_receipt_and_nonportable_names(self) -> None:
        for path in ("", "/absolute", "../secret", "a/../b", "a/./b", "a//b", "a\\b",
                     "C:/secret", "a%2fb", "a?query", "a#fragment", "a.", "a./b",
                     "CON", "nul.txt", "a/LpT1.log", "a" * 65, "valid\n", "café",
                     "package/build-inputs.json"):
            with self.subTest(path=path):
                value = receipt()
                value["inputs"][0]["path"] = path
                self.assert_invalid(value)

    def test_input_count_reserves_one_layer_for_the_receipt(self) -> None:
        value = receipt()
        entry = value["inputs"][0]
        value["inputs"] = [dict(entry, path=f"asset-{index:03}.txt") for index in range(255)]
        self.validator.validate(value)
        value["inputs"].append(dict(entry, path="overflow.txt"))
        self.assert_invalid(value)
        value["inputs"] = []
        self.assert_invalid(value)

    def test_header_and_role_constraints_match_the_receipt_codec(self) -> None:
        for field, values in {
            "formatVersion": [0, 2, "1", None, True],
            "operation": ["compile", "package-supplied-artifacts\n", None],
            "packager": ["other", "latent-packaging\n", None],
            "packagerVersion": ["", "1.0.0\n", "1.0.0_", "café", "a" * 129, None],
        }.items():
            for selected in values:
                with self.subTest(field=field, value=selected):
                    value = receipt()
                    value[field] = selected
                    self.assert_invalid(value)
        for role in ("evidence", "future-role", None):
            value = receipt()
            value["inputs"][0]["role"] = role
            self.assert_invalid(value)


if __name__ == "__main__":
    unittest.main()
