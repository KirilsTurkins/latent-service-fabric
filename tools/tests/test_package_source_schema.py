"""Adversarial shape checks for the explicit package file-selection recipe."""

from __future__ import annotations

import copy
import json
from pathlib import Path
import unittest

from jsonschema import Draft202012Validator


ROOT = Path(__file__).resolve().parents[2]


def recipe(kind: str = "browser-assets") -> dict:
    config = json.loads((ROOT / f"examples/package-format/{kind}/config.json").read_bytes())
    return {
        "formatVersion": 1,
        "kind": kind,
        "name": config["name"],
        "version": config["version"],
        "entrypoint": config["entrypoint"],
        "annotations": {},
        "layers": [
            {"path": layer["path"], "source": layer["path"],
             "role": layer["role"], "mediaType": layer["mediaType"]}
            for layer in config["layers"]
        ],
    }


class PackageSourceSchemaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        schema = json.loads((ROOT / "schemas/package-source.schema.json").read_bytes())
        Draft202012Validator.check_schema(schema)
        cls.validator = Draft202012Validator(schema)

    def assert_invalid(self, value: dict) -> None:
        self.assertFalse(self.validator.is_valid(value), repr(value))

    def test_all_three_recipe_kinds_are_structurally_representable(self) -> None:
        for kind in ("capsule", "browser-assets", "ssr-package"):
            with self.subTest(kind=kind):
                self.validator.validate(recipe(kind))

    def test_closed_recipe_and_file_objects_require_every_field(self) -> None:
        original = recipe()
        for key in original:
            with self.subTest(missing=key):
                changed = copy.deepcopy(original)
                del changed[key]
                self.assert_invalid(changed)
        for key in original["layers"][0]:
            changed = copy.deepcopy(original)
            del changed["layers"][0][key]
            self.assert_invalid(changed)
        for field in ("componentDigest", "trusted", "unknown"):
            changed = copy.deepcopy(original)
            changed[field] = "not authority"
            self.assert_invalid(changed)
            changed = copy.deepcopy(original)
            changed["layers"][0][field] = "not authority"
            self.assert_invalid(changed)

    def test_source_and_logical_paths_reject_traversal_and_nonportable_names(self) -> None:
        invalid = ["", "/absolute", "../secret", "a/../b", "a/./b", "a//b", "a\\b",
                   "C:/secret", "a%2fb", "a?query", "a#fragment", "a.", "a./b",
                   "CON", "nul.txt", "a/LpT1.log", "a" * 65, "valid\n", "café"]
        for field in ("path", "source"):
            for path in invalid:
                with self.subTest(field=field, path=path):
                    changed = recipe()
                    changed["layers"][0][field] = path
                    self.assert_invalid(changed)
        changed = recipe()
        changed["layers"][0]["path"] = "package/build-inputs.json"
        self.assert_invalid(changed)
        changed = recipe()
        changed["layers"][0]["source"] = "inputs/selected-file.js"
        self.validator.validate(changed)

    def test_kind_requires_its_exact_mandatory_roles(self) -> None:
        original = recipe("capsule")
        for index, layer in enumerate(original["layers"]):
            if layer["role"] == "asset":
                continue
            with self.subTest(role=layer["role"]):
                changed = copy.deepcopy(original)
                del changed["layers"][index]
                self.assert_invalid(changed)
                changed = copy.deepcopy(original)
                changed["layers"].append(copy.deepcopy(layer))
                self.assert_invalid(changed)
        for kind in ("browser-assets", "ssr-package"):
            changed = copy.deepcopy(original)
            changed["kind"] = kind
            self.assert_invalid(changed)
        changed = recipe("ssr-package")
        changed["layers"] = [layer for layer in changed["layers"] if layer["role"] != "renderer"]
        self.assert_invalid(changed)

    def test_role_media_types_cannot_be_substituted(self) -> None:
        for kind in ("capsule", "ssr-package"):
            original = recipe(kind)
            for index, layer in enumerate(original["layers"]):
                if layer["role"] == "asset":
                    continue
                with self.subTest(kind=kind, role=layer["role"]):
                    changed = copy.deepcopy(original)
                    changed["layers"][index]["mediaType"] = "text/plain"
                    self.assert_invalid(changed)
        for mime in ("text/HTML", "text/plain; charset=utf-8", "_text/plain", "text/+plain", "text/plain\n"):
            changed = recipe()
            changed["layers"][0]["mediaType"] = mime
            self.assert_invalid(changed)

    def test_layer_count_reserves_one_output_receipt_slot(self) -> None:
        changed = recipe()
        changed["entrypoint"] = "asset-0.txt"
        changed["layers"] = [
            {"path": f"asset-{index}.txt", "source": f"input-{index}.txt",
             "role": "asset", "mediaType": "text/plain"}
            for index in range(255)
        ]
        self.validator.validate(changed)
        changed["layers"].append({"path": "overflow.txt", "source": "overflow.txt", "role": "asset", "mediaType": "text/plain"})
        self.assert_invalid(changed)
        changed["layers"] = []
        self.assert_invalid(changed)

    def test_header_and_annotation_limits(self) -> None:
        for field, values in {
            "formatVersion": [0, 2, "1", None, True],
            "name": ["Upper", "-name", "name-", "name\n", "a" * 129],
            "version": ["1.0", "01.0.0", "1.0.0-01", "1.0.0\n"],
            "annotations": [{"": "value"}, {"bad key": "value"}, {"key": "value\n"},
                            {"key": "x" * 4097}, {str(index): "value" for index in range(33)}],
        }.items():
            for value in values:
                with self.subTest(field=field, value=value):
                    changed = recipe()
                    changed[field] = value
                    self.assert_invalid(changed)


if __name__ == "__main__":
    unittest.main()
