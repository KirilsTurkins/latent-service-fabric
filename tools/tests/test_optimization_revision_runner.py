"""Finite plan and exact-source build seams, without invoking Git or compilers."""
from pathlib import Path
from types import SimpleNamespace
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

from tools.optimization_revision_runner import backend, build
from tools.optimization_revision_runner.model import CONTROL, plan, population, run_id


class RevisionRunnerTests(unittest.TestCase):
    def test_population_alternates_and_labels_do_not_change_client_arm(self):
        values = list(population("full"))
        self.assertEqual(len(values), 14)
        self.assertEqual(values[:4], [(1, "control"), (1, "candidate"), (2, "candidate"), (2, "control")])
        self.assertEqual(len(run_id(1, "control", "warm-echo")), len(run_id(1, "candidate", "warm-echo")))
        self.assertNotEqual(run_id(1, "control", "warm-echo"), run_id(1, "candidate", "warm-echo"))

    def test_mixed_is_a_distinct_hit_and_refill_sequence(self):
        cases = {row["id"]: row["client_plan"] for row in plan("full")["cases"]}
        mixed = cases["cache-mixed"]["services"]
        self.assertEqual(len(set(mixed)), 5)
        self.assertTrue(all(mixed[index] == mixed[index + 1] for index in range(0, 10, 2)))
        self.assertEqual(len(cases["cache-working-set"]["services"]), 5)
        self.assertLess(cases["cache-mixed"]["budget_millis"] + 1, 5000)

    def test_full_requires_immutable_distinct_refs_but_allows_declared_auxiliary_control(self):
        refs = {"control": "e" * 40, "candidate": "c" * 40, "harness": "d" * 40}
        build.validate_refs(refs, "full")
        with self.assertRaises(ValueError):
            build.validate_refs(dict(refs, candidate=refs["control"]), "full")
        with self.assertRaises(ValueError):
            build.validate_refs(dict(refs, control="development"), "smoke")

    def test_changed_shared_client_source_is_rejected_before_build(self):
        refs = {"control": "a" * 40, "candidate": "b" * 40, "harness": "c" * 40}
        def fake_git(root, *arguments):
            return "changed" if arguments[-1].startswith("b" * 40 + ":tools/optimization-bench/src/client") else "same"
        with patch.object(build, "git", side_effect=fake_git), self.assertRaisesRegex(ValueError, "source-controls"):
            build.matching_controls(ROOT, refs)

    def test_backend_command_uses_real_release_libtest_boundary(self):
        self.assertIn("--release --locked", backend.RECIPE)
        self.assertIn("-p latentd --lib --no-run --message-format=json", backend.RECIPE)
        self.assertNotIn("cargo build", backend.RECIPE)


if __name__ == "__main__":
    unittest.main()
