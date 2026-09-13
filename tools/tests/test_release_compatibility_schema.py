"""Closed host-requirement examples; schema validation is not node eligibility."""

from __future__ import annotations

import copy
import json
from pathlib import Path
import re
import unittest

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[2]


def capsule() -> dict:
    return json.loads((ROOT / "examples/echo-contract/capsule.json").read_bytes())


def requirements() -> dict:
    return {
        "minimumFabricVersion": "0.1.0",
        "runtime": {"engine": "wasmtime", "minimumVersion": "47.0.3"},
        "targetTriples": ["x86_64-unknown-linux-gnu"],
        "cpuFeatures": ["x86_64.sse2"],
    }


class ReleaseCompatibilitySchemaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        schema = json.loads((ROOT / "schemas/capsule-manifest.schema.json").read_bytes())
        Draft202012Validator.check_schema(schema)
        cls.validator = Draft202012Validator(schema)

    def check_requirements(self, value: dict, valid: bool) -> None:
        document = capsule()
        document["compatibility"] = value
        errors = list(self.validator.iter_errors(document))
        if valid:
            self.assertEqual([], errors)
        else:
            self.assertTrue(errors, value)

    def test_existing_capsules_keep_optional_requirements_absent(self):
        for name in ("echo-contract", "counter-contract"):
            document = json.loads((ROOT / f"examples/{name}/capsule.json").read_bytes())
            self.validator.validate(document)
            self.assertEqual({"minimumFabricVersion"}, set(document["compatibility"]))

    def test_reference_examples_are_actual_schema_valid_members(self):
        text = (ROOT / "docs/reference/release-compatibility.md").read_text(encoding="utf-8")
        blocks = re.findall(r"```json\n(.*?)\n```", text, re.DOTALL)
        self.assertTrue(blocks)
        for block in blocks:
            self.check_requirements(json.loads(block), True)
        self.check_requirements(requirements(), True)

    def test_requirement_objects_reject_unknown_missing_and_null_values(self):
        for key in ("runtime", "targetTriples", "cpuFeatures"):
            value = requirements()
            value[key] = None
            self.check_requirements(value, False)
        for key in ("minimumFabricVersion",):
            value = requirements()
            del value[key]
            self.check_requirements(value, False)
        for key in ("engine", "minimumVersion"):
            for replacement in (None, ""):
                value = requirements()
                value["runtime"][key] = replacement
                self.check_requirements(value, False)
            value = requirements()
            del value["runtime"][key]
            self.check_requirements(value, False)
        for key in ("trusted", "compatible", "allowUnknown"):
            value = requirements()
            value[key] = True
            self.check_requirements(value, False)
            value = requirements()
            value["runtime"][key] = True
            self.check_requirements(value, False)
        value = requirements()
        value["runtime"]["engine"] = "unapproved-engine"
        self.check_requirements(value, False)

    def test_target_and_cpu_collections_are_bounded_and_unique(self):
        for key, maximum, example in (("targetTriples", 8, "x86_64-unknown-linux-gnu"),
                                       ("cpuFeatures", 32, "x86_64.sse2")):
            for invalid in (example, [None], [""], [example, example],
                            [f"item-{index}" for index in range(maximum + 1)]):
                value = copy.deepcopy(requirements())
                value[key] = invalid
                self.check_requirements(value, False)

    def test_empty_lists_and_target_count_boundary(self):
        value = requirements()
        value["targetTriples"] = []
        value["cpuFeatures"] = []
        self.check_requirements(value, True)
        value["targetTriples"] = [f"arch-vendor-os{index}" for index in range(8)]
        self.check_requirements(value, True)
        value["targetTriples"].append("arch-vendor-os8")
        self.check_requirements(value, False)

    def test_target_syntax_closed_feature_vocabulary_and_string_bound(self):
        for target in ("linux", "x86_64-linux", "x86_64--linux", "x86_64-vendor-linux\n",
                       "x86_64-vendor/linux", "x86_64-" + "v" * 116 + "-linux"):
            value = requirements()
            value["targetTriples"] = [target]
            self.check_requirements(value, False)
        for feature in ("sse2", "x86_64.invented", "aarch64.unknown"):
            value = requirements()
            value["cpuFeatures"] = [feature]
            self.check_requirements(value, False)
        value = requirements()
        value["runtime"]["minimumVersion"] = "47.0.3+" + "a" * 121
        self.check_requirements(value, True)
        value["runtime"]["minimumVersion"] += "a"
        self.check_requirements(value, False)


if __name__ == "__main__":
    unittest.main()
