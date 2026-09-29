"""Offline evaluator contract tests; fixture streams are not performance evidence."""
from __future__ import annotations

import io
import json
import os
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest import mock

from tools import ci_cargo, ci_cargo_evaluate as evaluation


class EvaluationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.repo = self.root / "repo"
        self.repo.mkdir()
        self.output = self.root / "observations"

    def test_never_deletes_preexisting_or_linked_target(self):
        target = self.repo / "target"
        target.mkdir()
        marker = target / "keep"
        marker.write_text("existing developer product")
        with self.assertRaises(ValueError):
            evaluation.evaluate(self.repo, self.output, "current")
        self.assertTrue(marker.exists())
        marker.unlink()
        target.rmdir()
        target.symlink_to(self.root / "absent")
        with self.assertRaises(ValueError):
            evaluation.evaluate(self.repo, self.output, "current")
        self.assertTrue(target.is_symlink())

    def test_report_directory_must_survive_private_target_resets(self):
        for output in (self.repo / "target/output", self.repo / "target/../source"):
            with self.subTest(output=output), self.assertRaises(ValueError):
                evaluation.evaluate(self.repo, output, "current")
        self.assertEqual(list(self.repo.iterdir()), [])

    def test_discovery_comparison_excludes_time_not_case_identity(self):
        receipt = {"activeCases": 1, "suites": [{"id": "one", "cases": ["a"], "ignored": [], "discoverySeconds": 99}]}
        expected = evaluation.exact_discovery(receipt)
        receipt["suites"][0]["discoverySeconds"] = 1
        self.assertEqual(evaluation.exact_discovery(receipt), expected)
        receipt["suites"][0]["cases"] = ["different"]
        self.assertNotEqual(evaluation.exact_discovery(receipt), expected)

    def test_artifact_overlap_does_not_waive_independent_coverage(self):
        items = [{"invocation": {"name": name}, "units": [{"identity": "shared"}]} for name in ("check", "clippy", "test")]
        report = evaluation.overlaps(items)
        self.assertEqual(report["sharedArtifactIdentities"]["shared"], ["check", "clippy", "test"])
        self.assertEqual(report["commandEliminations"], [])

    def replay(self, *, drift=False):
        metadata = {"workspace_members": ["package-id"], "packages": [{"id": "package-id", "name": "application"}],
                    "target_directory": str(self.repo / "target")}
        receipt = {"activeCases": 1, "suites": [{"id": "one", "cases": ["a"], "ignored": []}]}
        other = {"activeCases": 1, "suites": [{"id": "one", "cases": ["different"], "ignored": []}]}
        observed = []

        def observe(invocation, *, output, **kwargs):
            observed.append((invocation.name, kwargs.get("inventory"), dict(kwargs["environment"])))
            output.mkdir(parents=True)
            (output / "cargo.log").write_text("synthetic test output")
            return {"invocation": {"name": invocation.name}, "units": [{"identity": "unit"}],
                    "builtArtifactRecords": 1, "freshArtifactRecords": 0}

        def restore(target, *args):
            target.mkdir()
            return {"seconds": 0.1}

        with mock.patch.dict(os.environ, {}, clear=True), \
             mock.patch.object(evaluation.ci_cargo_cache, "observe", return_value={"digest": "synthetic"}), \
             mock.patch.object(evaluation, "checked", return_value=json.dumps(metadata).encode()), \
             mock.patch.object(evaluation.registry, "load", return_value={}), \
             mock.patch.object(evaluation.observations, "observe", side_effect=observe), \
             mock.patch.object(evaluation.discovery, "discover", side_effect=[receipt, other if drift else receipt, receipt]), \
             mock.patch.object(evaluation.discovery, "validate_custom_execution") as custom, \
             mock.patch.object(evaluation.discovery, "validate_recipe_execution") as recipes, \
             mock.patch.object(evaluation.aot_test_inputs, "prepare", return_value=self.root / "aot.json"), \
             mock.patch.object(evaluation.aot_test_inputs, "validate", return_value={}), \
             mock.patch.object(evaluation.aot_test_inputs, "environment", return_value={"LSF_AOT_TEST_EXECUTION_ONLY": "1", "LD_LIBRARY_PATH": "do-not-export"}), \
             mock.patch.object(evaluation, "cache_archive", return_value={"sha256": "synthetic", "seconds": 0.1}), \
             mock.patch.object(evaluation, "restore", side_effect=restore):
            result = evaluation.evaluate(self.repo, self.output, "current")
        return result, observed, custom.call_count, recipes.call_count

    def test_cold_and_two_warm_rows_run_every_recipe_and_revalidate_handoffs(self):
        record, observed, custom_count, recipe_count = self.replay()
        expected = [invocation.name for recipe in ci_cargo.RUST_RECIPES for invocation in ci_cargo.RECIPES[recipe]]
        self.assertEqual([name for name, _, _ in observed], expected * 3)
        self.assertEqual(custom_count, 3)
        self.assertEqual(recipe_count, 6)
        self.assertEqual([sample["state"] for sample in record["samples"]], list(evaluation.STATES))
        self.assertTrue(record["passed"])
        self.assertFalse(record["eligibleForDefaultPromotion"])
        self.assertIsNone(record["networkTransferSeconds"])
        for name, inventory, env in observed:
            self.assertEqual(inventory is not None, name == ci_cargo.RECIPES["prepare"][1].name)
            self.assertNotIn("LD_LIBRARY_PATH", env)
            self.assertEqual(env.get("LSF_AOT_TEST_EXECUTION_ONLY"), "1" if name in [i.name for i in ci_cargo.RECIPES["test"]] else None)

    def test_changed_warm_suite_identity_is_failure_not_faster_result(self):
        with self.assertRaisesRegex(ValueError, "identity-mismatch"):
            self.replay(drift=True)
        record = json.loads((self.output / "evaluation.json").read_text())
        self.assertFalse(record["passed"])
        self.assertTrue(record["samples"][0]["passed"])
        self.assertFalse(record["samples"][1]["passed"])


class DependencyArchiveTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.target = self.root / "target"
        self.dep = self.target / "debug/deps/libdependency-abcdef.rlib"
        self.dep.parent.mkdir(parents=True)
        self.dep.write_text("synthetic dependency")
        self.archive = self.root / "dependencies.tar.gz"

    def test_only_explicit_pruned_dependency_directories_are_restored(self):
        (self.target / "positive-result.json").write_text("must not be restored")
        record = evaluation.cache_archive(self.target, self.archive, ["application"])
        destination = self.root / "restored"
        result = evaluation.restore(destination, self.archive, record["sha256"])
        self.assertEqual(result["files"], 1)
        self.assertFalse((destination / "positive-result.json").exists())

    def test_workspace_fingerprint_and_library_spellings_are_both_rejected(self):
        for name in ("debug/deps/liblatent_testkit-abcdef.rlib", "debug/.fingerprint/latent-testkit-abcdef/lib-latent_testkit.json"):
            path = self.target / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("workspace control")
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, "workspace-product"):
                evaluation.cache_archive(self.target, self.archive, ["latent-testkit"])
            path.unlink()

    def test_bounds_and_links_are_enforced(self):
        with mock.patch.object(evaluation, "MAX_ARCHIVE_BYTES", 1), self.assertRaises(ValueError):
            evaluation.cache_archive(self.target, self.archive, ["application"])
        self.dep.unlink()
        self.dep.symlink_to(self.root / "secret")
        with self.assertRaises(ValueError):
            evaluation.cache_archive(self.target, self.archive, ["application"])

    def test_corruption_or_traversal_never_writes_destination(self):
        saved = evaluation.cache_archive(self.target, self.archive, ["application"])
        self.archive.write_bytes(b"damaged")
        destination = self.root / "restored"
        with self.assertRaises(ValueError):
            evaluation.restore(destination, self.archive, saved["sha256"])
        self.assertFalse(destination.exists())
        with tarfile.open(self.archive, "w:gz") as archive:
            info = tarfile.TarInfo("../escape")
            info.size = 1
            archive.addfile(info, io.BytesIO(b"x"))
        with self.assertRaises(ValueError):
            evaluation.restore(destination, self.archive, evaluation.hashed_file(self.archive))
        self.assertFalse(destination.exists())


if __name__ == "__main__":
    unittest.main()
