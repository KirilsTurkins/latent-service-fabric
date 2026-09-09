"""Budget-only reuse guards and one-pass build ownership, without actual Git or builds."""
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import Mock, patch

from tools import run_optimization_revision_benchmarks as cli
from tools.optimization_revision_runner import backend, budget, budget_build, build, collect, run


class BudgetRunnerTests(unittest.TestCase):
    def test_data_cleanup_receipt_survives_failed_seed_or_client(self):
        with tempfile.TemporaryDirectory() as temporary:
            result, observed = {"data_removed": False, "status": "failed"}, None
            with self.assertRaisesRegex(RuntimeError, "synthetic failure"):
                with run.owned_data(Path(temporary), result) as state:
                    observed = Path(state)
                    (observed / "durable-data").write_bytes(b"fixture")
                    raise RuntimeError("synthetic failure")
            self.assertTrue(result["data_removed"])
            self.assertFalse(observed.exists())
            self.assertEqual(result["status"], "failed")

    def test_cli_selects_budget_prebuilt_without_fabricating_refs(self):
        seen = []
        def execute(args, root):
            seen.append(args)
            return 0
        with patch.object(cli, "execute", side_effect=execute):
            self.assertEqual(cli.main(["--experiment", "budget", "--profile", "full", "--builds", "fresh/revision-builds.json"]), 0)
        self.assertIsNone(seen[0].candidate_ref)
        self.assertIsNone(seen[0].harness_ref)
        self.assertFalse(seen[0].build_only)

    def test_cli_rejects_ambiguous_or_legacy_build_only(self):
        choices = (["--build-only", "--candidate-ref", "b" * 40, "--harness-ref", "c" * 40, "--output", "unused"],
                   ["--experiment", "budget", "--builds", "receipt.json", "--output", "unused"],
                   ["--experiment", "budget", "--build-only", "--builds", "receipt.json"])
        with patch.object(cli, "execute") as execute:
            for args in choices:
                with self.subTest(args=args), self.assertRaises(SystemExit):
                    cli.main(args)
            execute.assert_not_called()

    def test_measured_prebuilt_root_is_rejected_without_overwriting_suite(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            receipt = root / "revision-builds.json"
            receipt.write_bytes(b"build fixture")
            original = root / "suite.json"
            original.write_bytes(b"preserved failed attempt")
            refs = {"control": "a" * 40, "candidate": "b" * 40, "harness": "c" * 40}
            args = SimpleNamespace(experiment="budget", profile="full", builds=receipt, build_only=False, target_root=root / "data")
            with patch("tools.optimization_revision_evidence.budget_builds.load", return_value={"requested_refs": refs, "artifacts": []}), \
                    patch.object(collect.platform, "system", return_value="Linux"), \
                    patch.object(build, "source", return_value={"commit": refs["harness"], "clean": True}), \
                    self.assertRaisesRegex(ValueError, "already-measured"):
                collect.execute(args, root)
            self.assertEqual(original.read_bytes(), b"preserved failed attempt")

    def test_new_build_pass_has_two_servers_two_collectors_one_client_and_one_generic_recipe(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            output, diagnostic, target = root / "external", root / "lifecycle", root / "owned"
            output.mkdir()
            target.mkdir()
            refs = {"control": "a" * 40, "candidate": "b" * 40, "harness": "c" * 40}
            current = {"ref": refs["control"]}
            suite = {"identity": {"build": {}, "builds": {}}, "cleanup": {"owned_worktree_removed": False}}
            built = []
            def git(repo, *arguments):
                if arguments[:2] == ("worktree", "add"):
                    Path(arguments[3]).mkdir()
                elif arguments[:2] == ("worktree", "remove"):
                    Path(arguments[3]).rmdir()
                elif arguments[0] == "checkout":
                    current["ref"] = arguments[-1]
                return "same"
            def external(source, target, label, out, deadline, **options):
                built.append(("external", label, options))
                return {"label": label}
            def diagnostic_build(source, target, label, out, deadline, kind, controls):
                built.append(("libtest", label, kind))
                return {"label": label}
            def generic(*args):
                built.append(("fixture", "generic"))
                return {"source": "synthetic"}
            suite["identity"]["build"] = {"overrides": {}}
            with patch.object(build, "git", side_effect=git), \
                    patch.object(build, "source", side_effect=lambda root: {"commit": current["ref"]}), \
                    patch.object(build, "build_one", side_effect=external), \
                    patch.object(backend, "build_libtest", side_effect=diagnostic_build), \
                    patch.object(budget_build, "generic", side_effect=generic), \
                    patch.object(backend, "build_echo") as echo:
                build.collect(root, refs, output, target, 0, suite, Mock(), diagnostic, selected=budget)
            self.assertEqual([(row[0], row[1]) for row in built],
                             [("external", "control"), ("libtest", "control"), ("external", "candidate"),
                              ("libtest", "candidate"), ("external", "harness"), ("fixture", "generic")])
            self.assertEqual(built[4][2]["harness_command"], budget.HARNESS_COMMAND)
            self.assertTrue(suite["cleanup"]["owned_worktree_removed"])
            self.assertTrue((diagnostic / "backend-builds.json").is_file())
            echo.assert_not_called()


if __name__ == "__main__":
    unittest.main()
