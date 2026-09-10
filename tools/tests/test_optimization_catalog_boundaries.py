"""Small actual filesystem and mocked publication-boundary checks; no workloads."""
from contextlib import redirect_stdout
from copy import deepcopy
import io
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from tools import package_phase1_evidence as package, validate_phase1_archive as archive
from tools import validate_optimization_backend_revision as cli
from tools.optimization_backend_revision.catalog import data, model
from tools.optimization_evidence.common import EvidenceError, canonical


class CatalogDataTests(unittest.TestCase):
    def test_same_owner_walk_and_removal_refuse_crossed_identity(self):
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary)
            root = parent / "catalog-data-owned-small"
            root.mkdir()
            selected = model.plan("smoke", **model.population("smoke")[0])
            identity = data.create(root, data.marker(selected, "a" * 40, nonce="b" * 32))
            (root / "data").mkdir()
            (root / "data" / "small").write_bytes(b"abc")
            closed = data.close_tree(root)
            self.assertEqual(closed["regular_files"], "2")
            self.assertEqual(closed["directories_including_root"], "2")
            self.assertEqual(int(closed["logical_file_bytes"]), (root / "owner.json").stat().st_size + 3)
            crossed = dict(identity, inode=str(int(identity["inode"]) + 1))
            with self.assertRaises(EvidenceError):
                data.remove_owned(root, parent, crossed)
            self.assertTrue((root / "data" / "small").exists())
            data.remove_owned(root, parent, identity)
            self.assertFalse(root.exists())

    def test_walk_rejects_a_file_limit_without_large_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "one").write_bytes(b"a")
            (root / "two").write_bytes(b"b")
            with patch.object(data, "MAX_TREE_FILES", 1), self.assertRaises(EvidenceError):
                data.close_tree(root)
            self.assertTrue((root / "two").exists())

    def test_native_reserve_is_explicit_and_does_not_assert_host_capacity(self):
        observed = SimpleNamespace(f_bavail=16 * 1024**2, f_frsize=1024)
        with patch.object(data.os, "statvfs", return_value=observed, create=True):
            receipt = data.reserve("unused", True)
            self.assertEqual(receipt["required_bytes"], str(16 * 1024**3))
            self.assertIn("not-host-backing", receipt["scope"])
            observed.f_bavail -= 1
            with self.assertRaises(EvidenceError):
                data.reserve("unused", True)
            self.assertEqual(data.reserve("unused", False)["required_bytes"], "0")


class CatalogPublicationTests(unittest.TestCase):
    VALUE = {"schema": "latent.optimization.catalog-aggregate.v1", "profile": "full", "status": "complete",
             "population_complete": True, "attempt_count_complete": True, "validated_commands": "596720"}

    def test_catalog_archive_roundtrip_uses_backend_replay_and_legacy_byte_bound(self):
        self.assertEqual(archive.archive_bounds("catalog"), (1024**3, 1024**3))
        self.assertEqual(archive.archive_bounds("engine"), archive.archive_bounds("catalog"))
        self.assertEqual(archive.archive_bounds("codec")[0], 2 * 1024**3)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            source.mkdir()
            (source / "aggregate.json").write_bytes(canonical(self.VALUE))
            (source / "suite.json").write_bytes(b'{"synthetic_archive_transport_fixture":true}')
            with patch.object(archive, "validate_backend_revision_suite", return_value=self.VALUE) as replay:
                package.package(source, root / "package", root / "unused-policy", split_archive=True)
                replay.assert_called_once()
                self.assertNotEqual(replay.call_args.args[0].parent, source)
            self.assertEqual(archive.evidence_kind(root / "package"), "catalog")

    def test_smoke_failed_crossed_and_incomplete_catalog_cannot_publish(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "suite.json").write_bytes(b'{"synthetic_archive_transport_fixture":true}')
            for change in ({"profile": "smoke"}, {"status": "failed"}, {"population_complete": False},
                    {"attempt_count_complete": False}, {"schema": "latent.optimization.engine-aggregate.v1"}):
                value = dict(self.VALUE, **change)
                (root / "aggregate.json").write_bytes(canonical(value))
                with self.subTest(change=change), patch.object(archive, "validate_backend_revision_suite", return_value=value), \
                        self.assertRaisesRegex(ValueError, "complete full-population"):
                    archive.verify_revision(root, catalog=True)
            (root / "aggregate.json").write_bytes(canonical(self.VALUE))
            with patch.object(archive, "validate_backend_revision_suite", return_value=dict(self.VALUE, validated_commands="1")), \
                    self.assertRaisesRegex(ValueError, "differs from replayed"):
                archive.verify_revision(root, catalog=True)
            for selector in (1, "catalog", None):
                with self.subTest(selector=selector), self.assertRaisesRegex(ValueError, "invalid catalog archive dispatch"):
                    archive.verify_revision(root, catalog=selector)
            with self.assertRaisesRegex(ValueError, "ambiguous"):
                archive.verify_revision(root, catalog=True, backend=True)

    def test_catalog_cli_displays_actual_command_count_after_equal_replay(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            suite, retained = root / "suite.json", root / "aggregate.json"
            suite.write_bytes(b"{}")
            retained.write_bytes(canonical(self.VALUE))
            output = io.StringIO()
            with patch.object(cli, "validate_suite", return_value=deepcopy(self.VALUE)), \
                    patch.object(cli.sys, "argv", ["validator", str(suite), "--aggregate", str(retained)]), redirect_stdout(output):
                status = cli.main()
            self.assertEqual(status, 0)
            self.assertEqual(output.getvalue(), "complete: 596720 catalog operations; population_complete=True\n")
