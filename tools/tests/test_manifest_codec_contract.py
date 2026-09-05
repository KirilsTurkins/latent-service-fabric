"""Regression checks for the schema-backed manifest codec contract."""

from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[2]

SCHEMA_EXAMPLES = {
    "capsule-manifest.schema.json": ("examples/**/capsule.json",),
    "deployment.schema.json": ("examples/**/deployment.json",),
    "binding.schema.json": ("examples/bindings/*.json",),
    "trigger.schema.json": ("examples/**/*trigger.json",),
    "policy.schema.json": ("examples/policies/*.json",),
}


class ManifestCodecContractTests(unittest.TestCase):
    def schema(self, name: str) -> dict:
        return json.loads((ROOT / "schemas" / name).read_text(encoding="utf-8"))

    def test_every_manifest_example_remains_schema_valid(self) -> None:
        for schema_name, patterns in SCHEMA_EXAMPLES.items():
            validator = Draft202012Validator(self.schema(schema_name))
            examples = sorted(
                {path for pattern in patterns for path in ROOT.glob(pattern)}
            )
            self.assertTrue(examples, f"no examples found for {schema_name}")
            for path in examples:
                document = json.loads(path.read_text(encoding="utf-8"))
                errors = sorted(validator.iter_errors(document), key=lambda error: list(error.path))
                self.assertEqual([], errors, f"{path.relative_to(ROOT)}: {errors}")

    def test_unknown_fields_are_closed_except_trigger_configuration(self) -> None:
        capsule_path = ROOT / "examples" / "echo-contract" / "capsule.json"
        capsule = json.loads(capsule_path.read_text(encoding="utf-8"))
        capsule["futureField"] = True
        capsule_errors = list(
            Draft202012Validator(self.schema("capsule-manifest.schema.json"))
            .iter_errors(capsule)
        )
        self.assertTrue(capsule_errors)

        trigger_path = ROOT / "examples" / "echo-contract" / "http-trigger.json"
        trigger = json.loads(trigger_path.read_text(encoding="utf-8"))
        trigger["spec"]["configuration"]["future"] = {
            "nested": [1, True, None, {"retained": "yes"}]
        }
        trigger_validator = Draft202012Validator(self.schema("trigger.schema.json"))
        self.assertEqual([], list(trigger_validator.iter_errors(trigger)))

        closed_trigger = copy.deepcopy(trigger)
        closed_trigger["spec"]["futureRuntimeField"] = True
        self.assertTrue(list(trigger_validator.iter_errors(closed_trigger)))

    def test_persistent_budgets_expose_only_relative_wall_time(self) -> None:
        for schema_name, pointer in (
            ("capsule-manifest.schema.json", ("properties", "execution", "properties", "limits")),
            ("deployment.schema.json", ("properties", "spec", "properties", "resources")),
        ):
            node = self.schema(schema_name)
            for segment in pointer:
                node = node[segment]
            properties = node["properties"]
            self.assertIn("wallTimeLimitMillis", properties)
            self.assertNotIn("wallDeadlineUnixMillis", properties)
            self.assertFalse(node["additionalProperties"])

        deployment_path = ROOT / "examples" / "echo-contract" / "deployment.json"
        deployment = json.loads(deployment_path.read_text(encoding="utf-8"))
        deployment["spec"]["resources"]["wallDeadlineUnixMillis"] = 1_800_000_000_000
        errors = list(
            Draft202012Validator(self.schema("deployment.schema.json"))
            .iter_errors(deployment)
        )
        self.assertTrue(errors)

    def test_runtime_embeds_each_authoritative_manifest_schema(self) -> None:
        source = (ROOT / "crates" / "latent-manifest" / "src" / "schema.rs").read_text(
            encoding="utf-8"
        )
        for schema_name in SCHEMA_EXAMPLES:
            self.assertIn(f'include_str!("../../../schemas/{schema_name}")', source)


if __name__ == "__main__":
    unittest.main()
