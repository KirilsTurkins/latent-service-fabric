"""Narrow reuse seams preserve real artifact warming and resolved tool ownership."""
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
from tools.artifact_identity_runner import run
from tools.optimization_cache_lookup import collect


class CollectionSeamTests(unittest.TestCase):
    def test_lookup_absent_fixture_never_warms_nonempty_evidence_root(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "retained-build.bin").write_bytes(b"existing retained build input")
            with patch.dict(sys.modules, resource=SimpleNamespace()), patch.object(run, "warm") as warm, \
                    patch.object(run, "reference", return_value={"different": True}):
                with self.assertRaisesRegex(ValueError, "retained-binary-mutated"):
                    run.collect({}, root / "run", {"path": "retained-build.bin"}, None, root, 2**63, "unused", "unused")
            warm.assert_not_called()

    def test_existing_artifact_mode_still_checks_real_fixture_manifest(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "unexpected.bin").write_bytes(b"not declared")
            with patch.dict(sys.modules, resource=SimpleNamespace()):
                with self.assertRaisesRegex(ValueError, "fixture-mutated"):
                    run.collect({}, root / "run", {}, {"root": ".", "files": {}}, root, 2**63, "unused", "unused")

    def test_tool_hash_command_and_receipt_use_one_resolved_path(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            actual = root / "real-nm"
            actual.write_bytes(b"synthetic tool file")
            unresolved = root / "bin" / ".." / "real-nm"
            (root / "bin").mkdir()
            def command(argv, log, *_args, **_kwargs):
                self.assertEqual(argv[0], str(actual.resolve()))
                log.write_text("synthetic version\n")
                return {"synthetic": True}
            with patch.object(collect.shutil, "which", return_value=str(unresolved)), patch.object(collect, "command", side_effect=command):
                result = collect.tool("nm", root, 2**63)
            self.assertEqual(result["path"], str(actual.resolve()))
