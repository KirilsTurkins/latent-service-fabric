"""Differential exact-number tests shared with the Rust manifest codec."""

from __future__ import annotations

import json
import unittest
from decimal import Decimal
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, validators

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


def _is_exact_integer(_checker: Any, instance: Any) -> bool:
    if isinstance(instance, bool):
        return False
    if isinstance(instance, int):
        return True
    if isinstance(instance, Decimal):
        return instance == instance.to_integral_value()
    return isinstance(instance, float) and instance.is_integer()


EXACT_TYPE_CHECKER = Draft202012Validator.TYPE_CHECKER.redefine(
    "integer", _is_exact_integer
)
ExactDraft202012Validator = validators.extend(
    Draft202012Validator,
    type_checker=EXACT_TYPE_CHECKER,
)


def _load_exact(source: str) -> Any:
    return json.loads(source, parse_float=Decimal)


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
                document = _load_exact(source)
                schema = _load_exact(schema_path.read_text(encoding="utf-8"))
                errors = list(ExactDraft202012Validator(schema).iter_errors(document))
                self.assertEqual(
                    case["valid"],
                    not errors,
                    f"{case['name']}: {[error.message for error in errors]}",
                )

    def test_trigger_schema_accepts_exact_arbitrary_precision_numbers(self) -> None:
        source = (
            ROOT / "examples" / "echo-contract" / "http-trigger.json"
        ).read_text(encoding="utf-8")
        anchor = '"configuration": {'
        replacement = '''"configuration": {
      "wideInteger": 18446744073709551617,
      "wideNegative": -9223372036854775809,
      "ratio": 0.123456789012345678901234567890,
      "largeNumber": 1e400,
      "smallNumber": 1e-400,
      "nested": [18446744073709551617, 1e400, 1e-400],'''
        self.assertIn(anchor, source)
        source = source.replace(anchor, replacement, 1)

        document = _load_exact(source)
        schema = _load_exact(
            (ROOT / "schemas" / "trigger.schema.json").read_text(encoding="utf-8")
        )
        errors = list(ExactDraft202012Validator(schema).iter_errors(document))
        self.assertFalse(errors, [error.message for error in errors])

        configuration = document["spec"]["configuration"]
        self.assertEqual(18446744073709551617, configuration["wideInteger"])
        self.assertEqual(-9223372036854775809, configuration["wideNegative"])
        self.assertEqual(
            Decimal("0.123456789012345678901234567890"),
            configuration["ratio"],
        )
        self.assertEqual(Decimal("1e400"), configuration["largeNumber"])
        self.assertEqual(Decimal("1e-400"), configuration["smallNumber"])


if __name__ == "__main__":
    unittest.main()
