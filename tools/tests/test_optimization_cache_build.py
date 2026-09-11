"""Exact-ref controls and failure cleanup without invoking Git or a compiler."""
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from tools.optimization_cache_lookup import build, builds
from tools.optimization_revision_runner import backend

REFS = {"control": "a" * 40, "candidate": "b" * 40, "harness": "c" * 40}


class CacheBuildTests(unittest.TestCase):
    def test_only_declared_library_targets_and_legacy_recipe(self):
        self.assertEqual(backend.libtest_recipe("backend"), backend.RECIPE)
        self.assertEqual(backend.libtest_recipe("lookup"), backend.RECIPE.replace("-p latentd", "-p latent-wasmtime"))
        with self.assertRaises(ValueError):
            backend.libtest_recipe("arbitrary-package")

    def test_lock_and_common_collector_changes_rejected_before_build(self):
        names = [name for name in builds.COMMON if not name.endswith("/cache/measurement")]
        def git(_repo, *args):
            if args[0] == "ls-tree":
                return "\n".join(names)
            ref, name = args[-1].split(":", 1)
            return "different" if ref == REFS["candidate"] and name == changed[0] else "same"
        for name in ("Cargo.lock", builds.LOOKUP_CONTROLS[0], backend.COLD_CONTROLS[0]):
            changed = [name]
            with self.subTest(name=name), patch.object(build.shared, "git", side_effect=git):
                with self.assertRaisesRegex(ValueError, "common-source-controls-differ"):
                    build.matching_controls(Path("unused"), REFS)

    def test_symbolic_or_dirty_harness_rejected_before_checkout(self):
        args = SimpleNamespace(profile="full", control_ref="development", candidate_ref=REFS["candidate"], harness_ref=REFS["harness"])
        with patch.object(build.platform, "system", return_value="Linux"), patch.object(build.shared, "owned_checkout") as checkout:
            with self.assertRaisesRegex(ValueError, "full-commit"):
                build.execute(args, Path("unused"))
            args.control_ref = REFS["control"]
            with patch.object(build.shared, "source", return_value={"commit": REFS["harness"], "clean": False}):
                with self.assertRaisesRegex(ValueError, "clean-ref"):
                    build.execute(args, Path("unused"))
            checkout.assert_not_called()

    def test_failed_first_library_removes_owned_source_and_preserves_both_failures(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = root / "repo"
            repo.mkdir()
            args = SimpleNamespace(profile="smoke", **{name + "_ref": value for name, value in REFS.items()},
                                   lookup_output=root / "lookup", behavior_output=root / "behavior", target_root=root / "external")
            def git(_repo, *argv):
                if argv[:2] == ("worktree", "add"):
                    Path(argv[3]).mkdir()
                elif argv[:2] == ("worktree", "remove"):
                    Path(argv[3]).rmdir()
                return ""
            def source(path):
                return {"commit": REFS["harness"] if path == repo else REFS["control"], "clean": True}
            with patch.object(build.platform, "system", return_value="Linux"), \
                    patch.object(build.shared, "source", side_effect=source), patch.object(build, "matching_controls"), \
                    patch.object(build.shared, "git", side_effect=git), \
                    patch.object(build, "build_configuration", return_value={"overrides": {}}), \
                    patch.object(build.backend, "build_libtest", side_effect=RuntimeError("synthetic-first-build-failure")) as compiler:
                self.assertEqual(build.execute(args, repo), 1)
            compiler.assert_called_once()
            self.assertEqual(compiler.call_args.args[5], "lookup")
            self.assertEqual(list(args.target_root.iterdir()), [])
            for out in (args.lookup_output, args.behavior_output):
                receipt = json.loads((out / "cache-builds.json").read_bytes())
                self.assertEqual(receipt["cleanup"], {"owned_worktree_removed": True})
                self.assertEqual(receipt["builds"], {})
                self.assertIn("synthetic-first-build-failure", (out / "failure.json").read_text())
