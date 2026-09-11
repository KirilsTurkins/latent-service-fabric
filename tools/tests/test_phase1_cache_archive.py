"""Cache archive dispatch and structural contracts; no guest workloads."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools import package_phase1_evidence as package
from tools import validate_phase1_archive as verify


class CacheArchiveTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="phase1-cache-archive-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.sequence = 0

    def inputs(self, kind):
        self.sequence += 1
        directory = self.root / str(self.sequence)
        source, output = directory / "source", directory / "package"
        source.mkdir(parents=True)
        aggregate = {
            "schema": f"latent.optimization.cache-{kind}-aggregate.v1", "profile": "full",
            "status": "complete", "population_complete": True, "attempt_count_complete": True,
            "suite_sha256": "sha256:" + "a" * 64, "builds": {}, "runs": [], "pairs": [],
            "across_pairs": [], "limitations": ["Synthetic archive dispatch fixture only."],
        }
        if kind == "lookup":
            aggregate.update(attempted_processes=0, validated_measured_gets="0", validated_warmup_gets="0")
        else:
            aggregate.update(validated_calls="0", validated_direct_executions="0")
        self.save(source, aggregate)
        suite = {
            "schema": f"latent.optimization.cache-{kind}-suite.v1", "profile": "full",
            "plan": {}, "builds": {"path": "builds.json", "sha256": "sha256:" + "b" * 64, "bytes": "2"},
            "runner_source": {}, "runner_source_after": {}, "status": "passed", "reason": None,
            "elapsed_nanos": "1", "runs": [], "artifacts": [],
        }
        if kind == "lookup":
            suite.update(tools={}, symbols={})
        (source / "suite.json").write_bytes(verify.canonical(suite))
        (source / "binary").write_bytes(b"synthetic binary\0")
        (source / "empty.log").write_bytes(b"")
        return source, output, aggregate

    @staticmethod
    def save(source, aggregate):
        (source / "aggregate.json").write_bytes(verify.canonical(aggregate))

    @staticmethod
    def validator(kind):
        return "validate_cache_lookup_suite" if kind == "lookup" else "validate_backend_revision_suite"

    def test_both_formats_replay_extracted_bytes_before_monolithic_or_split_publication(self):
        for kind in ("lookup", "behavior"):
            for split in (False, True):
                with self.subTest(kind=kind, split=split):
                    source, output, aggregate = self.inputs(kind)
                    originals = {path.name: path.read_bytes() for path in source.iterdir()}

                    def replay(path):
                        self.assertEqual(path.name, "suite.json")
                        self.assertNotEqual(path.parent, source)
                        self.assertFalse(output.exists())
                        self.assertEqual(originals, {item.name: item.read_bytes() for item in path.parent.iterdir()})
                        return aggregate

                    other = self.validator("behavior" if kind == "lookup" else "lookup")
                    with patch.object(verify, self.validator(kind), side_effect=replay) as called:
                        with patch.object(verify, other) as wrong:
                            manifest = package.package(source, output, self.root / "absent-policy.json", split_archive=split)
                            called.assert_called_once()
                            wrong.assert_not_called()
                    self.assertEqual({row["path"] for row in manifest["files"]}, set(originals))
                    self.assertEqual(originals, {path.name: path.read_bytes() for path in source.iterdir()})
                    self.assertEqual((output / verify.PARTS_MANIFEST).exists(), split)
                    self.assertFalse((output / "measurement-policy.json").exists())
                    self.assertFalse((output / "comparison.json").exists())

    def test_changed_aggregate_never_publishes(self):
        for kind in ("lookup", "behavior"):
            source, output, aggregate = self.inputs(kind)
            self.save(source, dict(aggregate, limitations=[]))
            with patch.object(verify, self.validator(kind), return_value=aggregate):
                with self.assertRaisesRegex(ValueError, "differs from replayed"):
                    package.package(source, output, self.root / "absent-policy.json")
            self.assertFalse(output.exists())

    def test_full_qualification_requires_exact_version_and_true_booleans(self):
        for kind in ("lookup", "behavior"):
            for change in ({"profile": "smoke"}, {"status": "incomplete"}, {"status": "failed"},
                           {"population_complete": False}, {"population_complete": 1},
                           {"attempt_count_complete": False}, {"attempt_count_complete": 1},
                           {"schema": "latent.optimization.cache-lookup-aggregate.v2"}):
                with self.subTest(kind=kind, change=change):
                    source, _, aggregate = self.inputs(kind)
                    changed = dict(aggregate, **change)
                    self.save(source, changed)
                    with patch.object(verify, self.validator(kind), return_value=changed):
                        with self.assertRaisesRegex(ValueError, "requires complete full-population"):
                            verify.verify_cache(source, "cache-" + kind)

    def test_suite_is_mandatory_even_when_semantic_replay_is_explicitly_disabled(self):
        for kind in ("lookup", "behavior"):
            source, output, _ = self.inputs(kind)
            (source / "suite.json").unlink()
            output.mkdir()
            package.create_archive(source, output, self.root / "absent-policy.json")
            with self.assertRaisesRegex(ValueError, "omits suite"):
                verify.verify_package(output, replay=False)

    def test_real_semantic_replay_rejects_invented_full_proof_and_cleans_staging(self):
        # The minimal structural documents intentionally omit actual build and
        # process evidence. Both real validators must refuse them after extraction.
        for kind in ("lookup", "behavior"):
            source, output, _ = self.inputs(kind)
            with self.assertRaises(ValueError):
                package.package(source, output, self.root / "absent-policy.json")
            self.assertFalse(output.exists())
            self.assertEqual(list(output.parent.iterdir()), [source])

    def test_unknown_versions_and_crossed_kind_are_rejected(self):
        for kind in ("lookup", "behavior"):
            source, _, aggregate = self.inputs(kind)
            self.assertEqual(verify.evidence_kind(source), "cache-" + kind)
            self.save(source, dict(aggregate, schema=aggregate["schema"].replace(".v1", ".v2")))
            with self.assertRaisesRegex(ValueError, "unsupported evidence schema"):
                verify.evidence_kind(source)
        with self.assertRaisesRegex(ValueError, "unsupported cache evidence kind"):
            verify.verify_cache(self.root, "cache-unrecognized")

    def test_existing_archive_and_aggregate_bounds_still_precede_replay(self):
        self.assertEqual((verify.MAX_COMPRESSED, verify.MAX_SPLIT_COMPRESSED, verify.MAX_PART_BYTES,
                          verify.MAX_EXPANDED, verify.MAX_FILES, verify.MAX_AGGREGATE_BYTES),
                         (99_000_000, 198_000_000, 50_000_000, 1024**3, 5000, 8 * 1024**2))
        for kind in ("lookup", "behavior"):
            source, output, _ = self.inputs(kind)
            output.mkdir()
            package.create_archive(source, output, self.root / "absent-policy.json")
            for bound in ("MAX_COMPRESSED", "MAX_EXPANDED", "MAX_FILES"):
                with patch.object(verify, bound, 1), patch.object(verify, self.validator(kind)) as replay:
                    with self.assertRaises(ValueError):
                        verify.verify_package(output)
                    replay.assert_not_called()
            with patch.object(verify, "MAX_AGGREGATE_BYTES", 1), patch.object(verify, self.validator(kind)) as replay:
                with self.assertRaisesRegex(ValueError, "json-byte-bound"):
                    verify.evidence_kind(source)
                replay.assert_not_called()

    def test_schema_envelopes_reject_unknown_fields_wrong_types_and_false_completion(self):
        import jsonschema
        schema_root = Path(__file__).resolve().parents[2] / "benchmarks/optimization"
        for kind in ("lookup", "behavior"):
            source, _, aggregate = self.inputs(kind)
            suite = json.loads((source / "suite.json").read_bytes())
            for document, value in (("suite", suite), ("aggregate", aggregate)):
                schema = json.loads((schema_root / f"cache-{kind}-{document}.schema.json").read_bytes())
                jsonschema.Draft202012Validator.check_schema(schema)
                validator = jsonschema.Draft202012Validator(schema)
                validator.validate(value)
                for changed in (dict(value, unexpected=True), dict(value, profile="other")):
                    with self.assertRaises(jsonschema.ValidationError):
                        validator.validate(changed)
                changed = copy.deepcopy(value)
                changed["status"] = "failed"
                if document == "suite":
                    with self.assertRaises(jsonschema.ValidationError):
                        validator.validate(changed)
                else:
                    for override in ({"profile": "smoke"}, {"population_complete": False},
                                     {"attempt_count_complete": 1}):
                        with self.assertRaises(jsonschema.ValidationError):
                            validator.validate(dict(value, **override))


if __name__ == "__main__":
    unittest.main()
