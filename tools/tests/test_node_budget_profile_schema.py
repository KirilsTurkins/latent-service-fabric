"""The accounting selector cannot silently enable later-phase operations."""
import json
from pathlib import Path
import unittest

import jsonschema


class BudgetProfileSchema(unittest.TestCase):
    def test_explicit_profiles_counter_ranges_and_finite_tree_bounds(self):
        path = Path(__file__).resolve().parents[2] / "schemas/node-budget-profile.schema.json"
        schema = json.loads(path.read_text(encoding="utf-8"))
        jsonschema.Draft202012Validator.check_schema(schema)
        validator = jsonschema.Draft202012Validator(schema)
        for value in ({"mode": "phase1"}, {"mode": "phase3"},
                      {"mode": "phase3", "maximumChildCalls": 0, "maximumDepth": 16,
                       "maximumLiveChildren": 32, "maximumLiveDescendants": 256}):
            self.assertTrue(validator.is_valid(value), value)
        for value in (None, {}, {"mode": "phase4"}, {"mode": "phase3", "maximumDepth": 17},
                      {"mode": "phase1", "maximumChildCalls": 0},
                      {"mode": "phase3", "stateReadBytes": 1},
                      {"mode": "phase3", "maximumLiveDescendants": 0},
                      {"mode": "phase3", "maximumLiveChildren": 33},
                      {"mode": "phase3", "maximumChildCalls": 4294967296},
                      {"mode": "phase3", "maximumBlobReadBytes": -1},
                      {"mode": "phase3", "maximumOutboundRequests": True}):
            self.assertFalse(validator.is_valid(value), value)


if __name__ == "__main__":
    unittest.main()
