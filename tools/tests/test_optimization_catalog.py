"""Finite catalog plans and independent fixture/selection rules; no workloads."""
import hashlib
import json
from pathlib import Path
import unittest

from tools.optimization_backend_revision.catalog import fixtures, model
from tools.optimization_evidence.common import EvidenceError, canonical

ROOT = Path(__file__).resolve().parents[2]


class CatalogModelTests(unittest.TestCase):
    def test_full_has_four_initial_and_four_adjacent_reopen_owners(self):
        rows = model.population("full")
        actual = [(row["shape"], row["variant"], row["mode"]) for row in rows[:8]]
        self.assertEqual(actual, [(shape, variant, mode) for shape, variant in (
            ("distinct", "control"), ("distinct", "candidate"),
            ("shared", "candidate"), ("shared", "control")) for mode in ("initial", "reopen")])
        self.assertEqual(len(rows), 24)
        self.assertEqual(len({model.run_id(row) for row in rows}), 24)
        self.assertEqual([row["sequence_ordinal"] for row in rows], list(range(24)))
        self.assertEqual(len(model.population("smoke")), 40)
        self.assertEqual(sum(row["mode"] == "initial" for row in model.population("smoke")), 12)

    def test_populations_count_pin_reopen_preflight_and_warmup(self):
        for profile, initial, profiled, total_commands, total_resolves, measured in (
                ("smoke", 604, 98, 8900, 8292, 7936),
                ("full", 148013, 290, 596720, 196396, 196096)):
            with self.subTest(profile=profile):
                self.assertEqual(model.counts(profile, "initial")["commands"], initial)
                self.assertEqual(model.counts(profile, "reopen")["commands"], 7)
                self.assertEqual(model.counts(profile, "allocation")["commands"], profiled)
                totals = model.suite_plan(profile)["totals"]
                self.assertEqual(totals["commands"], total_commands)
                self.assertEqual(totals["resolves"], total_resolves)
                self.assertEqual(totals["measured_resolves"], measured)
                self.assertEqual(totals["invokes"], 0)
                self.assertEqual(totals["preflight_resolves"], 16)
                self.assertEqual(totals["warmup_resolves"], 256)

    def test_exact_selection_rejects_boolean_ordinal_and_crossed_stage(self):
        row = model.population("full")[0]
        for change in ({"sequence_ordinal": True}, {"repetition": True}, {"sequence_ordinal": 1},
                       {"mode": "reopen"}, {"variant": "candidate"}, {"shape": "shared"},
                       {"case": "default-success"}):
            with self.subTest(change=change), self.assertRaises(EvidenceError):
                model.plan("full", **dict(row, **change))

    def test_all_model_plans_validate_and_schema_rejects_open_selection(self):
        import jsonschema
        schema = json.loads((ROOT / "benchmarks/optimization/catalog-plan.schema.json").read_bytes())
        validator = jsonschema.Draft202012Validator(schema)
        for profile in ("smoke", "full"):
            for row in model.population(profile):
                plan = model.plan(profile, **row)
                validator.validate(plan)
                for change in ({"unknown": 0}, {"profile": "other"}, {"shape": "third"},
                               {"repetition": 4}, {"sequence_ordinal": 40}, {"case": "other"},
                               {"mode": "normal"}, {"sequence_ordinal": False}):
                    with self.subTest(change=change), self.assertRaises(jsonschema.ValidationError):
                        validator.validate(dict(plan, **change))
                if profile == "full":
                    with self.assertRaises(jsonschema.ValidationError):
                        validator.validate(dict(plan, repetition=2))
        for path in (ROOT / "benchmarks/optimization").glob("catalog-*.schema.json"):
            jsonschema.Draft202012Validator.check_schema(json.loads(path.read_bytes()))


class CatalogFixtureTests(unittest.TestCase):
    def fixture(self):
        capsule = json.loads((ROOT / "examples/echo-contract/capsule.json").read_bytes())
        capsule["execution"]["limits"].update(cpuFuel=10_000_000_000, memoryBytes=67_108_864)
        return fixtures.Fixture(fixtures.COMPONENT_HEADER, capsule,
            json.loads((ROOT / "examples/echo-contract/contracts.json").read_bytes()),
            json.loads((ROOT / "examples/echo-contract/deployment.json").read_bytes()), "bounded-test-exports")

    def test_variant_is_exact_original_component_plus_one_index_section(self):
        base = fixtures.COMPONENT_HEADER + b"\0\1\0"
        expected = base + b"\0\x1d\x18latent.scale.identity.v1\x04\x03\x01\x00"
        self.assertEqual(fixtures.component(base, 0x010304), expected)
        for value in (-1, 100000, True):
            with self.assertRaises(EvidenceError):
                fixtures.component(base, value)

    def test_weight_changes_owned_attributes_but_not_revision_identity(self):
        fixture = self.fixture()
        before = fixture.deployment(0, "shared", 1)
        after = fixture.deployment(0, "shared", 2)
        self.assertEqual(before["metadata"]["name"], "scale-000000")
        self.assertEqual(before["spec"]["service"], "scale-shared")
        self.assertNotEqual(fixture.attributes(0, "shared", 1), fixture.attributes(0, "shared", 2))
        after["spec"]["route"]["weight"] = 1
        self.assertEqual(canonical(before), canonical(after))
        payload = canonical(before)
        expected = "revision-v1:sha256:" + hashlib.sha256(
            b"lsf-deployment-revision-v1\0" + len(payload).to_bytes(8, "big") + payload).hexdigest()
        self.assertEqual(fixture.revision(0, "shared"), expected)
        self.assertNotEqual(fixture.revision(0, "distinct"), expected)
        self.assertNotIn("wallTimeLimitMillis", before["spec"]["resources"])
        self.assertEqual(before["spec"]["placement"]["architectures"], ["aarch64", "x86_64"])

    def test_route_frame_preserves_utf8_lengths_and_absent_empty_key_equivalence(self):
        target = {"tenant": "a", "service": "b", "route": None, "contract": "c", "function": "d"}
        framed = b"lsf-route-selection-v1\0"
        for value in (b"a", b"b", b"default", b"c", b"d", "\u03bb|x".encode()):
            framed += len(value).to_bytes(8, "big") + value
        self.assertEqual(fixtures.selection_word(target, "\u03bb|x"), int.from_bytes(hashlib.sha256(framed).digest()[:8], "big"))
        self.assertEqual(fixtures.selection_word(target, None), fixtures.selection_word(target, ""))
        self.assertNotEqual(fixtures.selection_word(target, "ab"), fixtures.selection_word(dict(target, function="da"), "b"))

    def test_case_inputs_keep_misses_on_existing_scope_and_named_route_index(self):
        expected = 7919 % 16
        index, target, key = fixtures.input_case(16, "named-success", 1, "shared")
        self.assertEqual((index, target["service"], target["route"], key),
                         (expected, "scale-shared", f"scale-{expected:06}", "catalog-key-00001"))
        _, target, _ = fixtures.input_case(16, "route-miss", 1, "distinct")
        self.assertEqual((target["service"], target["route"]), (f"scale-{expected:06}", "missing-route"))
        _, target, _ = fixtures.input_case(16, "export-miss", 1, "distinct")
        self.assertEqual((target["function"], target["route"]), ("missing-function", None))
