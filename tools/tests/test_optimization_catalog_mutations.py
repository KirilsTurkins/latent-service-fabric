"""Closed mutation populations; no constructed performance evidence."""
import json
from pathlib import Path
import unittest

from tools.optimization_backend_revision.catalog_mutations import model


class CatalogMutationPlanTests(unittest.TestCase):
    def test_schema_allows_each_actual_plan_and_rejects_closed_shape_crossings(self):
        import jsonschema
        root = Path(__file__).resolve().parents[2]
        schema = json.loads((root / "benchmarks/optimization/catalog-mutation-plan.schema.json").read_text())
        validator = jsonschema.Draft202012Validator(schema)
        validator.check_schema(schema)
        for profile in ("smoke", "full"):
            for row in model.population(profile):
                validator.validate(model.plan(profile, **row))
        valid = model.plan("full")
        for change in ({"unknown": 1}, {"repetition": True}, {"repetition": 2},
                       {"profile": "smoke"}, {"populated_size": 100000}, {"mode": "allocation"},
                       {"sequence_ordinal": 32}, {"schema": "latent.optimization.catalog-plan.v1"}):
            with self.subTest(change=change), self.assertRaises(jsonschema.ValidationError):
                validator.validate({**valid, **change})

    def test_fixed_full_and_smoke_public_operation_populations(self):
        for profile, owners, normal_owners, normal_commands, allocation_commands, commands in (
                ("smoke", 16, 8, 186, 234, 420), ("full", 32, 24, 44910, 682, 45592)):
            with self.subTest(profile=profile):
                plan = model.suite_plan(profile)
                self.assertEqual(plan["totals"]["collector_processes"], owners)
                self.assertEqual(plan["normal_totals"]["collector_processes"], normal_owners)
                self.assertEqual(plan["normal_totals"]["commands"], normal_commands)
                self.assertEqual(plan["allocation_totals"]["commands"], allocation_commands)
                self.assertEqual(plan["totals"]["commands"], commands)
                self.assertEqual(plan["totals"]["invokes"], 0)
                self.assertEqual(plan["totals"]["warmup_calls"], 0)
                self.assertEqual(plan["totals"]["preflight_calls"], 0)
                self.assertEqual(plan["totals"]["measured_mutations"], owners // 2 * 4)
                self.assertEqual(plan["totals"]["reopen_observations"], owners // 2)

    def test_every_selected_owner_is_exactly_bound_and_adjacent_to_its_root_reopen(self):
        for profile in ("smoke", "full"):
            rows = model.population(profile)
            roots, names = set(), set()
            for ordinal, row in enumerate(rows):
                self.assertEqual(row["sequence_ordinal"], ordinal)
                self.assertEqual(model.plan(profile, **row), {
                    "schema": "latent.optimization.catalog-mutation-plan.v1", "profile": profile, **row})
                names.add(model.run_id(row))
            for initial, reopen in zip(rows[::2], rows[1::2], strict=True):
                self.assertTrue(model.is_initial(initial["mode"]))
                self.assertTrue(model.is_reopen(reopen["mode"]))
                self.assertEqual(model.group_id(initial), model.group_id(reopen))
                self.assertEqual(model.profiled(initial["mode"]), model.profiled(reopen["mode"]))
                roots.add(model.group_id(initial))
            self.assertEqual(len(names), len(rows))
            self.assertEqual(len(roots), len(rows) // 2)

    def test_normal_arm_order_reverses_across_size_and_shape(self):
        rows = model.population("full")[:24]
        self.assertEqual([rows[offset]["variant"] for offset in range(0, 24, 4)],
                         ["control", "candidate", "candidate", "control", "control", "candidate"])
        self.assertEqual([rows[offset]["populated_size"] for offset in range(0, 24, 4)],
                         [100, 100, 1000, 1000, 10000, 10000])

    def test_deleted_get_is_an_actual_call_not_an_implicit_inspection(self):
        distinct = model.counts("smoke", "initial", "distinct", 4)
        shared = model.counts("smoke", "initial", "shared", 4)
        self.assertEqual({key: distinct[key] for key in model.OPERATION_KEYS}, {
            "publications": 4, "seed_batches": 1, "applies": 3, "deletes": 1,
            "gets": 4, "resolves": 12, "policies": 10, "pins": 5})
        self.assertEqual(shared["commands"], distinct["commands"] + 1)
        self.assertEqual(shared["policies"], 11)
        self.assertEqual(model.counts("full", "reopen", "shared", 10000)["commands"], 6)

    def test_selector_crossings_and_boolean_integer_aliases_are_rejected(self):
        valid = model.population("full")[0]
        mutations = {"repetition": (True, 0, 2), "populated_size": (True, 16, 128, 100000),
                     "sequence_ordinal": (False, 1, 32), "variant": ("candidate", "unknown"),
                     "mode": ("reopen", "allocation"), "shape": ("shared", "unknown")}
        for field, values in mutations.items():
            for value in values:
                with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                    model.plan("full", **{**valid, field: value})
        with self.assertRaises(TypeError):
            model.plan("full", **valid, invented=True)
        for value in (True, 0, 100000):
            with self.subTest(count=value), self.assertRaises(ValueError):
                model.counts("full", "initial", "distinct", value)

    def test_profile_and_finite_bounds_are_explicit(self):
        for profile in ("smoke", "full"):
            value = model.suite_plan(profile)
            self.assertEqual(value["maximum_artifact_bytes"], "1073741824")
            self.assertEqual(value["maximum_folded_expanded_bytes"], "268435456")
            self.assertEqual(value["maximum_profile_records"], 4000000)
            self.assertEqual(model.run_seconds(profile, "allocation"), 180)
            self.assertEqual(model.run_seconds(profile, "allocation-reopen"), 180)
        for bad in (None, True, "FULL", "diagnostic"):
            with self.subTest(profile=bad), self.assertRaises(ValueError):
                model.population(bad)


if __name__ == "__main__":
    unittest.main()
