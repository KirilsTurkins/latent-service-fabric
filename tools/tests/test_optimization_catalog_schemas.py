"""Structural schema checks; these do not qualify a benchmark source graph."""
from copy import deepcopy
import json
from pathlib import Path
import unittest

from jsonschema import Draft202012Validator
from tools.optimization_backend_revision.catalog import model

ROOT = Path(__file__).resolve().parents[2] / "benchmarks/optimization"


class CatalogEnvelopeTests(unittest.TestCase):
    def test_envelopes_accept_the_fixed_plans_and_reject_outside_bounds(self):
        for name in ("suite", "aggregate"):
            with self.subTest(name=name):
                schema = json.loads((ROOT / f"catalog-{name}.schema.json").read_text(encoding="utf-8"))
                Draft202012Validator.check_schema(schema)
                plan_validator = Draft202012Validator({"$ref": "#/$defs/plan", "$defs": schema["$defs"]})
                for profile in ("smoke", "full"):
                    plan = model.suite_plan(profile)
                    plan_validator.validate(plan)
                    changed = deepcopy(plan)
                    changed["rows"][0]["sequence_ordinal"] = True
                    self.assertFalse(plan_validator.is_valid(changed))
                    changed = deepcopy(plan)
                    changed["maximum_artifact_bytes"] = str(2 * 1024**3)
                    self.assertFalse(plan_validator.is_valid(changed))
                    changed = deepcopy(plan)
                    changed["unplanned_calls"] = 1
                    self.assertFalse(plan_validator.is_valid(changed))
                    changed = deepcopy(plan)
                    changed["rows"] = plan["rows"] * 2
                    self.assertFalse(plan_validator.is_valid(changed))


if __name__ == "__main__":
    unittest.main()
