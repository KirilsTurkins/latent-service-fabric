"""Closed SBOM content-policy wire choices; no trust or currentness claims."""
from __future__ import annotations

import json
from pathlib import Path
import unittest

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[2]
ROLES = ["guest-dependency", "build-dependency", "proc-macro", "build-script",
         "wit-package", "build-tool", "asset", "component", "renderer"]


def policy():
    return {"formatVersion": 1, "embedded": "required", "detached": "optional",
            "requireSource": ["guest-dependency"], "requireLicense": []}


class SbomPolicySchemaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        schema = json.loads((ROOT / "schemas/package-sbom-policy.schema.json").read_bytes())
        Draft202012Validator.check_schema(schema)
        cls.validator = Draft202012Validator(schema)

    def test_explicit_presence_and_role_choices(self):
        for embedded in ("optional", "required"):
            for detached in ("optional", "required"):
                for roles in ([], ROLES, list(reversed(ROLES))):
                    self.validator.validate({**policy(), "embedded": embedded, "detached": detached,
                                             "requireSource": roles, "requireLicense": roles})

    def test_missing_unknown_and_null_fields_are_rejected(self):
        for field in policy():
            changed = policy()
            del changed[field]
            self.assertFalse(self.validator.is_valid(changed), field)
            self.assertFalse(self.validator.is_valid({**policy(), field: None}), field)
        self.assertFalse(self.validator.is_valid({**policy(), "trusted": True}))
        for version in (0, 2, True, "1"):
            self.assertFalse(self.validator.is_valid({**policy(), "formatVersion": version}))

    def test_unknown_duplicate_and_unbounded_roles_are_rejected(self):
        for field in ("requireSource", "requireLicense"):
            for roles in (["unknown"], ["asset", "asset"], ROLES + ["asset"], [None], "asset"):
                self.assertFalse(self.validator.is_valid({**policy(), field: roles}), (field, roles))
        for field in ("embedded", "detached"):
            for value in ("ignore", "forbidden", "required\n", True):
                self.assertFalse(self.validator.is_valid({**policy(), field: value}), (field, value))


if __name__ == "__main__":
    unittest.main()
