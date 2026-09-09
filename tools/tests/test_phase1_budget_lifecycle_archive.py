"""Explicit lifecycle transport dispatch; synthetic archive bytes are labeled."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools import package_phase1_evidence as package
from tools import validate_phase1_archive as verify
from tools.optimization_backend_revision.budget import aggregate, model


class LifecycleArchiveTests(unittest.TestCase):
    def test_both_transports_invoke_strict_lifecycle_replay(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for split in (False, True):
                source, output = root / str(split), root / (str(split) + '-package')
                source.mkdir()
                value = {"schema": "latent.optimization.budget-lifecycle-aggregate.v1", "profile": "full", "status": "complete",
                         "population_complete": True, "attempt_count_complete": True}
                (source / "aggregate.json").write_bytes(verify.canonical(value))
                (source / "suite.json").write_bytes(b'{"synthetic_transport_fixture":true}')
                (source / "collector").write_bytes(b"synthetic retained executable")
                def replay(path):
                    self.assertNotEqual(path.parent, source)
                    self.assertEqual((path.parent / "collector").read_bytes(), b"synthetic retained executable")
                    return value
                with patch.object(verify, "validate_backend_revision_suite", side_effect=replay) as called:
                    package.package(source, output, root / "unused-policy", split_archive=split)
                    called.assert_called_once()
                self.assertEqual(verify.evidence_kind(output), "budget-lifecycle")
                self.assertFalse((output / "measurement-policy.json").exists())

    def test_smoke_failed_or_changed_aggregate_cannot_publish_full(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "suite.json").write_bytes(b'{"synthetic_transport_fixture":true}')
            value = {"schema": "latent.optimization.budget-lifecycle-aggregate.v1", "profile": "smoke", "status": "incomplete",
                     "population_complete": True, "attempt_count_complete": True}
            (root / "aggregate.json").write_bytes(verify.canonical(value))
            with patch.object(verify, "validate_backend_revision_suite", return_value=value):
                with self.assertRaisesRegex(ValueError, "complete full-population"):
                    verify.verify_revision(root, lifecycle=True)
            changed = dict(value, status="failed")
            with patch.object(verify, "validate_backend_revision_suite", return_value=changed):
                with self.assertRaisesRegex(ValueError, "differs from replayed"):
                    verify.verify_revision(root, lifecycle=True)

    def test_structural_schemas_reject_unknown_fields_and_false_completion(self):
        import jsonschema
        root = Path(__file__).resolve().parents[2] / "benchmarks/optimization"
        for name in ("plan", "suite", "builds", "aggregate"):
            schema = json.loads((root / f"budget-lifecycle-{name}.schema.json").read_bytes())
            jsonschema.Draft202012Validator.check_schema(schema)
        schema = json.loads((root / "budget-lifecycle-plan.schema.json").read_bytes())
        validator = jsonschema.Draft202012Validator(schema)
        validator.validate(model.plan("smoke"))
        with self.assertRaises(jsonschema.ValidationError):
            validator.validate(dict(model.plan("smoke"), repetition=2))
        with self.assertRaises(jsonschema.ValidationError):
            validator.validate(dict(model.plan("smoke"), guessed=True))
        value = aggregate.aggregate({"profile": "smoke"}, "sha256:" + "a" * 64, {}, [], False, True)
        schema = json.loads((root / "budget-lifecycle-aggregate.schema.json").read_bytes())
        validator = jsonschema.Draft202012Validator(schema)
        validator.validate(value)
        with self.assertRaises(jsonschema.ValidationError):
            validator.validate(dict(value, status="complete"))


if __name__ == '__main__':
    unittest.main()
