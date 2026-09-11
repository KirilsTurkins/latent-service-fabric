"""Structural contracts stay aligned with the fixed executable selectors."""
import copy
import json
from pathlib import Path
import unittest

from jsonschema import Draft202012Validator

from tools.optimization_scheduler import model

ROOT = Path(__file__).resolve().parents[1] / "optimization_scheduler/schemas"


class SchedulerSchemaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.schemas = {path.stem.split(".")[0]: json.loads(path.read_text(encoding="utf-8"))
                       for path in ROOT.glob("*.schema.json")}

    def test_all_contracts_are_valid_and_have_distinct_identifiers(self):
        self.assertEqual(set(self.schemas), {"plan", "builds", "suite", "aggregate", "arm"})
        self.assertEqual(len({value["$id"] for value in self.schemas.values()}), 5)
        for schema in self.schemas.values():
            Draft202012Validator.check_schema(schema)

    def test_every_fixed_selector_and_suite_plan_matches_its_contract(self):
        plan = Draft202012Validator(self.schemas["plan"])
        for profile in ("smoke", "full"):
            for selected in model.population(profile):
                plan.validate(selected)
            for name in ("suite", "aggregate"):
                Draft202012Validator(self.schemas[name]["properties"]["plan"]).validate(model.suite_plan(profile))

    def test_structural_plan_rejects_crossed_allocation_case_and_extra_fields(self):
        validator = Draft202012Validator(self.schemas["plan"])
        for change in ({"mode": "allocation"}, {"case": "unknown"}, {"variant": "third"},
                       {"profile": "100k"}, {"observation_hold_millis": 0}, {"extra": True}):
            selected = dict(model.plan("smoke"), **change)
            with self.subTest(change=change):
                self.assertFalse(validator.is_valid(selected))

    def test_qualified_aggregate_requires_full_exact_population(self):
        condition = self.schemas["aggregate"]["allOf"][0]
        validator = Draft202012Validator(condition)
        complete = {"acceptance_qualified": True, "profile": "full", "status": "complete",
                    "completed_paired_run": True, "full_population_completed": True,
                    "validated_attempts": 14, "logical_offers": "9128"}
        validator.validate(complete)
        for field, value in (("profile", "smoke"), ("status", "failed"),
                             ("validated_attempts", 13), ("logical_offers", "9127"),
                             ("completed_paired_run", False), ("full_population_completed", False)):
            changed = copy.deepcopy(complete)
            changed[field] = value
            with self.subTest(field=field):
                self.assertFalse(validator.is_valid(changed))


if __name__ == "__main__":
    unittest.main()
