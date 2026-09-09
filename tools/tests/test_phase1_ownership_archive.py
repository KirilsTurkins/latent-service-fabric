"""Ownership archive transport/dispatch tests, with explicitly synthetic evidence.

Only semantic suite replay is substituted: these are not ownership measurements
or executable fixtures. Packaging, hashes, extraction and publication are real.
"""
import copy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools import package_phase1_evidence as package
from tools import validate_phase1_archive as verify


KINDS = ("ownership-rpc", "ownership")


class OwnershipArchiveTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="ownership-archive-test-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.sequence = 0

    def fixture(self, kind):
        self.sequence += 1
        parent = self.root / str(self.sequence)
        source, output = parent / "source", parent / "published"
        (source / "raw").mkdir(parents=True)
        value = {
            "schema": f"latent.optimization.{kind}-aggregate.v1",
            "profile": "full", "status": "complete",
            "population_complete": True, "attempt_count_complete": True,
            "statistics": {"synthetic_count": "3"},
        }
        self.write_aggregate(source, value)
        (source / "suite.json").write_bytes(verify.canonical({
            "schema": f"latent.optimization.{kind}-suite.v1",
            "synthetic_transport_fixture": True,
        }))
        (source / "collector").write_bytes(b"synthetic bytes; never execute\0")
        (source / "raw" / "calls.json").write_bytes(b'{"synthetic":true}\n')
        (source / "raw" / "empty.log").write_bytes(b"")
        return source, output, value

    @staticmethod
    def write_aggregate(directory, value):
        (directory / "aggregate.json").write_bytes(verify.canonical(value))

    @staticmethod
    def validator(kind):
        return ("validate_revision_suite" if kind == "ownership-rpc"
                else "validate_backend_revision_suite")

    @staticmethod
    def contents(directory):
        return {path.relative_to(directory).as_posix(): path.read_bytes()
                for path in directory.rglob("*") if path.is_file()}

    def test_both_formats_replay_extracted_files_before_either_transport_publishes(self):
        for kind in KINDS:
            for split in (False, True):
                with self.subTest(kind=kind, split=split):
                    source, output, value = self.fixture(kind)
                    original = self.contents(source)

                    def replay(path):
                        self.assertEqual(path.name, "suite.json")
                        self.assertNotEqual(path.parent, source)
                        self.assertFalse(output.exists())
                        self.assertEqual(self.contents(path.parent), original)
                        return value

                    other_kind = KINDS[1] if kind == KINDS[0] else KINDS[0]
                    with patch.object(verify, self.validator(kind), side_effect=replay) as selected:
                        with patch.object(verify, self.validator(other_kind)) as other:
                            manifest = package.package(
                                source, output, self.root / "absent-policy.json", split_archive=split)
                            selected.assert_called_once()
                            other.assert_not_called()
                    self.assertEqual(self.contents(source), original)
                    self.assertEqual(verify.evidence_kind(output), kind)
                    self.assertEqual({row["path"] for row in manifest["files"]}, set(original))
                    self.assertEqual(next(row["bytes"] for row in manifest["files"]
                                          if row["path"] == "raw/empty.log"), "0")
                    self.assertEqual((output / verify.PARTS_MANIFEST).exists(), split)
                    self.assertEqual((output / verify.ARCHIVE).exists(), not split)
                    self.assertFalse((output / "measurement-policy.json").exists())
                    self.assertFalse((output / "comparison.json").exists())

    def test_rehashed_aggregate_mismatch_cannot_publish(self):
        for kind in KINDS:
            for split in (False, True):
                with self.subTest(kind=kind, split=split):
                    source, output, replayed = self.fixture(kind)
                    changed = copy.deepcopy(replayed)
                    changed["statistics"]["synthetic_count"] = "4"
                    self.write_aggregate(source, changed)
                    with patch.object(verify, self.validator(kind), return_value=replayed) as selected:
                        with self.assertRaisesRegex(ValueError, "differs from replayed evidence"):
                            package.package(source, output, None, split_archive=split)
                        selected.assert_called_once()
                    self.assertFalse(output.exists())

    def test_full_complete_and_both_exact_boolean_flags_are_mandatory(self):
        changes = [{"profile": "smoke"}, {"status": "incomplete"}, {"status": "failed"},
                   {"schema": "latent.optimization.revision-aggregate.v1"}]
        changes += [{field: value} for field in ("population_complete", "attempt_count_complete")
                    for value in (False, 1, "true", None)]
        for kind in KINDS:
            for change in changes:
                with self.subTest(kind=kind, change=change):
                    source, _, value = self.fixture(kind)
                    value.update(change)
                    self.write_aggregate(source, value)
                    with patch.object(verify, self.validator(kind), return_value=value):
                        with self.assertRaisesRegex(ValueError, "complete full-population"):
                            verify.verify_revision(source, ownership=kind)
            for missing in ("profile", "status", "population_complete", "attempt_count_complete"):
                with self.subTest(kind=kind, missing=missing):
                    source, _, value = self.fixture(kind)
                    del value[missing]
                    self.write_aggregate(source, value)
                    with patch.object(verify, self.validator(kind), return_value=value):
                        with self.assertRaisesRegex(ValueError, "complete full-population"):
                            verify.verify_revision(source, ownership=kind)

    def test_semantic_failure_propagates_and_shape_only_remains_explicit(self):
        for kind in KINDS:
            source, output, _ = self.fixture(kind)
            output.mkdir()
            package.create_archive(source, output, None)
            with patch.object(verify, self.validator(kind), side_effect=ValueError("synthetic semantic rejection")) as selected:
                verify.verify_package(output, replay=False)
                selected.assert_not_called()
                with self.assertRaisesRegex(ValueError, "synthetic semantic rejection"):
                    verify.verify_package(output)
                selected.assert_called_once()
                unpublished = output.parent / "must-not-publish"
                with self.assertRaisesRegex(ValueError, "synthetic semantic rejection"):
                    package.package(source, unpublished, None)
                self.assertFalse(unpublished.exists())

    def test_suite_is_required_even_for_shape_only_verification(self):
        for kind in KINDS:
            source, output, _ = self.fixture(kind)
            (source / "suite.json").unlink()
            output.mkdir()
            package.create_archive(source, output, None, split_archive=True)
            with patch.object(verify, self.validator(kind)) as selected:
                with self.assertRaisesRegex(ValueError, "archive omits suite"):
                    verify.verify_package(output, replay=False)
                selected.assert_not_called()

    def test_invalid_or_ambiguous_dispatch_rejects_before_any_replay(self):
        with patch.object(verify, "validate_revision_suite") as external:
            with patch.object(verify, "validate_backend_revision_suite") as backend:
                for invalid in ("", "ownership.v2", "recovery", True, [], {}):
                    with self.subTest(invalid=invalid):
                        with self.assertRaisesRegex(ValueError, "invalid ownership archive dispatch"):
                            verify.verify_revision(self.root / "absent", ownership=invalid)
                for kind in KINDS:
                    for flag in ("backend", "cold", "budget", "lifecycle", "transport", "recovery"):
                        with self.subTest(kind=kind, flag=flag):
                            with self.assertRaisesRegex(ValueError, "ambiguous revision archive dispatch"):
                                verify.verify_revision(self.root / "absent", ownership=kind, **{flag: True})
                external.assert_not_called()
                backend.assert_not_called()

    def test_unknown_schema_version_cannot_dispatch_as_supported_ownership(self):
        for kind in KINDS:
            source, output, value = self.fixture(kind)
            value["schema"] = value["schema"].replace(".v1", ".v2")
            self.write_aggregate(source, value)
            with patch.object(verify, self.validator(kind)) as selected:
                with self.assertRaisesRegex(ValueError, "unsupported evidence schema"):
                    package.package(source, output, None)
                selected.assert_not_called()
            self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
