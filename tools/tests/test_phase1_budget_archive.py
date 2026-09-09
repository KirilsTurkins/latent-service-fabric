"""Explicit budget archive dispatch plus real smoke/schema rejection; no workloads."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools import package_phase1_evidence as package
from tools import validate_phase1_archive as verify
from tools.optimization_revision_evidence import validate_suite
from tools.tests.test_optimization_budget_evidence import Fixture


class BudgetArchiveTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def test_explicit_budget_dispatch_preserves_normal_and_split_transport(self):
        for split in (False, True):
            source = self.root / ("split" if split else "ordinary")
            source.mkdir()
            aggregate = {"schema": "latent.optimization.budget-aggregate.v1", "profile": "full", "status": "complete",
                         "population_complete": True, "attempt_count_complete": True}
            (source / "aggregate.json").write_bytes(verify.canonical(aggregate))
            (source / "suite.json").write_bytes(b'{"synthetic_transport_fixture":true}')
            (source / "binary").write_bytes(b"synthetic retained binary")
            output = self.root / (source.name + "-package")
            def replay(path):
                self.assertNotEqual(path.parent, source)
                self.assertEqual((path.parent / "binary").read_bytes(), b"synthetic retained binary")
                return aggregate
            with patch.object(verify, "validate_revision_suite", side_effect=replay) as called:
                package.package(source, output, self.root / "no-policy", split_archive=split)
                called.assert_called_once()
            self.assertEqual(verify.evidence_kind(output), "budget")
            self.assertFalse((output / "measurement-policy.json").exists())

    def test_real_smoke_cannot_publish_as_full(self):
        source = self.root / "source"
        source.mkdir()
        fixture = Fixture(source)
        aggregate = validate_suite(source / "suite.json")
        (source / "aggregate.json").write_bytes(verify.canonical(aggregate))
        with self.assertRaisesRegex(ValueError, "complete full-population"):
            package.package(source, self.root / "package", self.root / "no-policy")
        self.assertFalse((self.root / "package").exists())

    def test_rehashed_wrong_plan_cannot_become_full_publication(self):
        source = self.root / "source"
        source.mkdir()
        fixture = Fixture(source)
        aggregate = validate_suite(source / "suite.json")
        fixture.suite["plan"]["cases"][2]["client_plan"]["budget_millis"] = 1000
        fixture.save()
        aggregate.update(profile="full", status="complete")
        (source / "aggregate.json").write_bytes(verify.canonical(aggregate))
        with self.assertRaisesRegex(ValueError, "population"):
            package.package(source, self.root / "package", self.root / "no-policy")
        self.assertFalse((self.root / "package").exists())

    def test_new_structural_schemas_match_actual_replay_and_reject_false_completion(self):
        import jsonschema
        fixture = Fixture(self.root)
        values = {"suite": fixture.suite, "aggregate": validate_suite(self.root / "suite.json"),
                  "plan": fixture.suite["plan"], "builds": fixture.read(fixture.suite["builds"])}
        directory = Path(__file__).resolve().parents[2] / "benchmarks/optimization"
        for kind, value in values.items():
            schema = json.loads((directory / f"budget-{kind}.schema.json").read_bytes())
            jsonschema.Draft202012Validator.check_schema(schema)
            validator = jsonschema.Draft202012Validator(schema)
            validator.validate(value)
            with self.assertRaises(jsonschema.ValidationError):
                validator.validate(dict(value, unknown=True))
        changed = copy.deepcopy(values["aggregate"])
        changed["status"] = "complete"
        schema = json.loads((directory / "budget-aggregate.schema.json").read_bytes())
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.Draft202012Validator(schema).validate(changed)


if __name__ == "__main__":
    unittest.main()
