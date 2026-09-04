"""Differential integer tests shared with the Rust manifest codec."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[2]
CASES = (
    ROOT
    / "crates"
    / "latent-manifest"
    / "tests"
    / "fixtures"
    / "integer-dialect-cases.json"
)

TARGETS = {
    "deployment-weight": (
        ROOT / "examples" / "echo-contract" / "deployment.json",
        ROOT / "schemas" / "deployment.schema.json",
        '"weight": 10000',
        '"weight": {lexeme}',
    ),
    "capsule-host-call-depth": (
        ROOT / "examples" / "echo-contract" / "capsule.json",
        ROOT / "schemas" / "capsule-manifest.schema.json",
        '"hostCallDepthMaximum": 8',
        '"hostCallDepthMaximum": {lexeme}',
    ),
    "capsule-memory-bytes": (
        ROOT / "examples" / "echo-contract" / "capsule.json",
        ROOT / "schemas" / "capsule-manifest.schema.json",
        '"memoryBytes": 4194304',
        '"memoryBytes": {lexeme}',
    ),
}


class ManifestIntegerDialectTests(unittest.TestCase):
    def test_shared_cases_match_full_draft_2020_12_validation(self) -> None:
        cases = json.loads(CASES.read_text(encoding="utf-8"))
        for case in cases:
            with self.subTest(case=case["name"]):
                document_path, schema_path, anchor, replacement = TARGETS[case["target"]]
                source = document_path.read_text(encoding="utf-8")
                self.assertIn(anchor, source)
                source = source.replace(
                    anchor,
                    replacement.format(lexeme=case["lexeme"]),
                    1,
                )
                document = json.loads(source)
                schema = json.loads(schema_path.read_text(encoding="utf-8"))
                errors = list(Draft202012Validator(schema).iter_errors(document))
                self.assertEqual(
                    case["valid"],
                    not errors,
                    f"{case['name']}: {[error.message for error in errors]}",
                )


if __name__ == "__main__":
    unittest.main()
