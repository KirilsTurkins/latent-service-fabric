"""The accounting selector cannot silently enable later-phase operations."""
import json
from pathlib import Path
import unittest

import jsonschema


class BudgetProfileSchema(unittest.TestCase):
    def test_phase4_requires_exact_finite_transaction_counters(self):
        path = Path(__file__).resolve().parents[2] / "schemas/node-budget-profile.schema.json"
        validator = jsonschema.Draft202012Validator(json.loads(path.read_text(encoding="utf-8")))
        declared = {"mode": "phase4", "maximumStateReadBytes": 0,
                    "maximumStateWriteBytes": 1073741824, "maximumEffectCount": 128}
        validator.validate(declared)
        validator.validate(dict(declared, maximumChildCalls=1, maximumOutboundRequests=1))
        for name in ("maximumStateReadBytes", "maximumStateWriteBytes", "maximumEffectCount"):
            missing = dict(declared)
            del missing[name]
            self.assertFalse(validator.is_valid(missing), name)
            for value in (None, True, -1, 1.5):
                self.assertFalse(validator.is_valid(dict(declared, **{name: value})), (name, value))
        for name, maximum in (("maximumStateReadBytes", 1073741824),
                              ("maximumStateWriteBytes", 1073741824), ("maximumEffectCount", 128)):
            self.assertFalse(validator.is_valid(dict(declared, **{name: maximum + 1})), name)
        for name in ("grant", "continuityProven", "restoreApproved"):
            self.assertFalse(validator.is_valid(dict(declared, **{name: True})), name)

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
