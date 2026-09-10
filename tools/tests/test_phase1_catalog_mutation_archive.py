"""Actual archive transport dispatch; synthetic semantics never qualify a workload."""
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from tools import package_phase1_evidence as package
from tools import validate_phase1_archive as verify


class CatalogMutationArchiveTests(unittest.TestCase):
    def test_publication_replays_the_extracted_mutation_graph(self):
        with TemporaryDirectory() as temporary:
            parent = Path(temporary)
            source, output = parent / "source", parent / "publication"
            source.mkdir()
            value = {"schema": "latent.optimization.catalog-mutation-aggregate.v1", "profile": "full",
                     "status": "complete", "population_complete": True, "attempt_count_complete": True,
                     "validated_commands": "45096"}
            (source / "aggregate.json").write_bytes(verify.canonical(value))
            (source / "suite.json").write_bytes(verify.canonical({"schema": "latent.optimization.catalog-mutation-suite.v1"}))
            (source / "raw.log").write_bytes(b"retained raw transport fixture\n")
            before = {p.name: p.read_bytes() for p in source.iterdir()}

            def replay(path):
                self.assertNotEqual(path.parent, source)
                self.assertFalse(output.exists())
                self.assertEqual({p.name: p.read_bytes() for p in path.parent.iterdir()}, before)
                return value

            with patch.object(verify, "validate_backend_revision_suite", side_effect=replay) as checked:
                manifest = package.package(source, output, parent / "absent-policy.json")
                checked.assert_called_once()
            self.assertEqual({row["path"] for row in manifest["files"]}, set(before))
            self.assertEqual({p.name: p.read_bytes() for p in source.iterdir()}, before)
            self.assertEqual(verify.evidence_kind(output), "catalog-mutation")

    def test_partial_population_and_changed_replay_never_publish(self):
        for failure in ("partial", "changed"):
            with self.subTest(failure=failure), TemporaryDirectory() as temporary:
                parent = Path(temporary)
                source, output = parent / "source", parent / "publication"
                source.mkdir()
                value = {"schema": "latent.optimization.catalog-mutation-aggregate.v1", "profile": "full",
                         "status": "complete", "population_complete": failure != "partial",
                         "attempt_count_complete": failure != "partial", "validated_commands": "45096"}
                (source / "aggregate.json").write_bytes(verify.canonical(value))
                (source / "suite.json").write_bytes(b"{}")
                replayed = dict(value, validated_commands="45095") if failure == "changed" else value
                with patch.object(verify, "validate_backend_revision_suite", return_value=replayed), \
                     self.assertRaises(ValueError):
                    package.package(source, output, parent / "absent-policy.json")
                self.assertFalse(output.exists())

    def test_new_discriminator_keeps_existing_finite_archive_limits(self):
        self.assertEqual(verify.archive_bounds("catalog-mutation"), verify.archive_bounds("catalog"))
        for flag in (1, "yes", None):
            with self.subTest(flag=flag), self.assertRaises(ValueError):
                verify.verify_revision(Path("unused"), catalog_mutation=flag)
