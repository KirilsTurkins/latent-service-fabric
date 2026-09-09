"""Explicit #119 archive formats, real warm replay and bounded schema rejection."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools import package_phase1_evidence as package, validate_phase1_archive as verify
from tools.optimization_revision_evidence import validate_suite
from tools.optimization_backend_revision.recovery import model
from tools.tests.test_optimization_transport_warm import Fixture


class RecoveryArchiveTests(unittest.TestCase):
    def test_new_formats_keep_both_bounded_transports_and_mandatory_replay(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for kind in ("transport-warm", "recovery"):
                for split in (False, True):
                    source = root / f"{kind}-{split}"
                    source.mkdir()
                    value = {"schema": f"latent.optimization.{kind}-aggregate.v1", "profile": "full", "status": "complete",
                             "population_complete": True, "attempt_count_complete": True}
                    (source / "aggregate.json").write_bytes(verify.canonical(value))
                    (source / "suite.json").write_bytes(b'{"synthetic_transport_fixture":true}')
                    (source / "collector").write_bytes(b"synthetic retained executable")
                    def replay(path):
                        self.assertNotEqual(path.parent, source)
                        self.assertEqual((path.parent / "collector").read_bytes(), b"synthetic retained executable")
                        return value
                    output = root / (source.name + "-package")
                    target = "validate_revision_suite" if kind == "transport-warm" else "validate_backend_revision_suite"
                    with patch.object(verify, target, side_effect=replay) as called:
                        package.package(source, output, root / "unused-policy", split_archive=split)
                        called.assert_called_once()
                    self.assertEqual(verify.evidence_kind(output), kind)
                    self.assertFalse((output / "measurement-policy.json").exists())

    def test_real_smoke_cannot_publish_or_hide_a_rehashed_cleanup_removal(self):
        with tempfile.TemporaryDirectory() as temporary:
            root, source = Path(temporary), Path(temporary) / "source"
            source.mkdir()
            fixture = Fixture(source)
            value = validate_suite(source / "suite.json")
            (source / "aggregate.json").write_bytes(verify.canonical(value))
            with self.assertRaisesRegex(ValueError, "complete full-population"):
                package.package(source, root / "package", root / "unused-policy")
            row = fixture.suite["runs"][1]["cleanup"]
            raw = fixture.read(row)
            del raw["server_shutdown"]["report"]["cleanup"]
            fixture.replace(row, raw)
            fixture.rebind()
            value.update(profile="full", status="complete")
            (source / "aggregate.json").write_bytes(verify.canonical(value))
            with self.assertRaisesRegex(ValueError, "cleanup-presence"):
                package.package(source, root / "package", root / "unused-policy")
            self.assertFalse((root / "package").exists())

    def test_schemas_match_actual_graph_and_forbid_false_completion(self):
        import jsonschema
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fixture = Fixture(root)
            values = {"suite": fixture.suite, "plan": fixture.suite["plan"],
                      "builds": fixture.read(fixture.suite["builds"]), "aggregate": validate_suite(root / "suite.json")}
            directory = Path(__file__).resolve().parents[2] / "benchmarks/optimization"
            for kind, value in values.items():
                schema = json.loads((directory / f"transport-warm-{kind}.schema.json").read_bytes())
                jsonschema.Draft202012Validator.check_schema(schema)
                validator = jsonschema.Draft202012Validator(schema)
                validator.validate(value)
                with self.assertRaises(jsonschema.ValidationError):
                    validator.validate(dict(value, invented=True))
            value = copy.deepcopy(values["aggregate"])
            value["status"] = "complete"
            with self.assertRaises(jsonschema.ValidationError):
                validator.validate(value)
            schema = json.loads((directory / "recovery-plan.schema.json").read_bytes())
            validator = jsonschema.Draft202012Validator(schema)
            for profile in ("smoke", "full"):
                validator.validate(model.plan(profile))
                with self.assertRaises(jsonschema.ValidationError):
                    validator.validate(dict(model.plan(profile), repetition=2))


if __name__ == "__main__":
    unittest.main()
