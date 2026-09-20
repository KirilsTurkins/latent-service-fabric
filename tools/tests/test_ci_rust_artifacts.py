"""Bounded fixture selection and process ownership checks; no Cargo or Rust builds."""

from __future__ import annotations

from contextlib import redirect_stdout
import copy
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

from tools import ci_rust_artifacts as artifacts


def listing(suite: artifacts.Suite) -> bytes:
    return ("\n".join(f"{name}: test" for name in sorted(suite.names))
            + f"\n\n{len(suite.names)} tests, 0 benchmarks\n").encode()


class InventoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.repo = Path(self.temporary.name).resolve()
        self.suite = artifacts.SUITES["operator-fixture"]
        self.manifest = self.repo / self.suite.manifest
        self.manifest.parent.joinpath("src").mkdir(parents=True)
        self.manifest.write_text("[package]\n", encoding="utf-8")
        self.source = self.manifest.parent / "src/lib.rs"
        self.source.write_text("", encoding="utf-8")
        self.executable = self.repo / "target/debug/deps/latent_policy-current"
        self.executable.parent.mkdir(parents=True)
        self.executable.write_bytes(b"current fixture placeholder")
        self.inventory = self.repo / "inventory.jsonl"
        self.message = {
            "reason": "compiler-artifact", "manifest_path": str(self.manifest),
            "target": {"kind": ["lib"], "name": self.suite.target, "src_path": str(self.source)},
            "profile": {"test": True}, "executable": str(self.executable), "fresh": True,
        }

    def save(self, messages: list[dict] | None = None) -> None:
        selected = [self.message] if messages is None else messages
        self.inventory.write_text("".join(json.dumps(message) + "\n" for message in [
            *selected, {"reason": "build-finished", "success": True}]), encoding="utf-8")

    def read(self) -> artifacts.Artifact:
        return artifacts.read_inventory(self.inventory, self.repo, self.suite)

    def test_exact_current_artifact_selected_without_globbing_old_binaries(self) -> None:
        self.executable.with_name("latent_policy-stale").write_bytes(b"old")
        normal_library = copy.deepcopy(self.message)
        normal_library["profile"]["test"] = False
        normal_library["executable"] = None
        self.save([normal_library, self.message])
        found = self.read()
        self.assertEqual(found.executable, self.executable)
        self.assertEqual(found.package, self.manifest.parent)

    def test_duplicate_or_foreign_owner_is_never_an_accepted_harness(self) -> None:
        self.save([self.message, self.message])
        with self.assertRaisesRegex(artifacts.ArtifactError, "ambiguous"):
            self.read()
        for field, value in (("manifest_path", str(self.repo / "foreign/Cargo.toml")),
                             ("executable", str(self.source))):
            wrong = copy.deepcopy(self.message)
            wrong[field] = value
            self.save([wrong])
            with self.subTest(field=field), self.assertRaises(artifacts.ArtifactError):
                self.read()

    def test_integration_and_non_test_executables_cannot_substitute_for_libtest(self) -> None:
        for change in ({"kind": ["test"]}, {"name": "other"}, {"src_path": str(self.manifest)}):
            wrong = copy.deepcopy(self.message)
            wrong["target"].update(change)
            self.save([wrong])
            with self.subTest(change=change), self.assertRaises(artifacts.ArtifactError):
                self.read()
        wrong = copy.deepcopy(self.message)
        wrong["profile"]["test"] = 1
        self.save([wrong])
        with self.assertRaises(artifacts.ArtifactError):
            self.read()

    def test_successful_terminal_build_record_is_mandatory(self) -> None:
        for suffix in ("", '\n{"reason":"build-finished","success":false}',
                       '\n{"reason":"build-finished","success":true}\n{}'):
            self.inventory.write_text(json.dumps(self.message) + suffix, encoding="utf-8")
            with self.subTest(suffix=suffix), self.assertRaises(artifacts.ArtifactError):
                self.read()

    def test_angular_integration_fixture_requires_its_exact_cargo_owner(self) -> None:
        self.suite = artifacts.SUITES["angular-t1-fixture"]
        self.manifest = self.repo / self.suite.manifest
        self.manifest.parent.mkdir(parents=True)
        self.manifest.write_text("[package]\n", encoding="utf-8")
        self.source = self.manifest.parent / self.suite.source
        self.source.parent.mkdir()
        self.source.write_text("", encoding="utf-8")
        self.message.update(manifest_path=str(self.manifest), target={
            "kind": ["test"], "name": self.suite.target, "src_path": str(self.source)})
        unrelated = copy.deepcopy(self.message)
        unrelated["target"]["name"] = "catalog_scale"
        self.save([unrelated, self.message])
        self.assertEqual(self.read().executable, self.executable)
        for change in ({"kind": ["lib"]}, {"src_path": str(self.manifest)}):
            wrong = copy.deepcopy(self.message)
            wrong["target"].update(change)
            self.save([wrong])
            with self.subTest(change=change), self.assertRaises(artifacts.ArtifactError):
                self.read()

    def test_inventory_decode_and_allocation_bounds_fail_closed(self) -> None:
        for raw in ('{"reason":"x","reason":"build-finished"}', '[]', '{broken'):
            self.inventory.write_text(raw, encoding="utf-8")
            with self.subTest(raw=raw), self.assertRaises((artifacts.ArtifactError, ValueError)):
                self.read()
        self.save()
        for limit, value in (("MAX_LINE_BYTES", 8), ("MAX_INVENTORY_BYTES", 8), ("MAX_RECORDS", 1)):
            with patch.object(artifacts, limit, value), self.assertRaises(artifacts.ArtifactError):
                self.read()

    def test_dynamic_search_paths_only_retain_bounded_target_owned_paths(self) -> None:
        owned = self.repo / "target/debug/build/native/out"
        self.save([{"reason": "build-script-executed", "linked_paths": [
            f"native={owned}", str(self.repo / "external"), str(owned)]}, self.message])
        self.assertEqual(self.read().link_paths, (owned,))
        self.save([{"reason": "build-script-executed", "linked_paths": ["x"] * 257}, self.message])
        with self.assertRaises(artifacts.ArtifactError):
            self.read()

    def test_execution_uses_exact_ignored_suite_package_cwd_and_inherited_inputs(self) -> None:
        self.save()
        env = {"LSF_OPERATOR_FIXTURE_ROOT": "fresh inputs", "LSF_AOT_COMPILER": "compiler"}
        success = b"test result: ok. 1 passed; 0 failed; 0 ignored; 50 filtered out; finished in 0.00s\n"
        with patch.object(artifacts, "cargo_environment", return_value=env), \
                patch.object(artifacts, "run_owned", side_effect=[(0, listing(self.suite)), (0, success)]) as run, \
                redirect_stdout(io.StringIO()):
            artifacts.run_suite(self.repo, self.inventory, self.suite, env)
        self.assertEqual(run.call_count, 2)
        command = run.call_args.args[0]
        self.assertEqual(command, [str(self.executable), self.suite.filter, "--ignored", "--exact",
                                   "--test-threads=1"])
        self.assertEqual(run.call_args.kwargs["cwd"], self.manifest.parent)
        self.assertIs(run.call_args.kwargs["env"], env)

    def test_zero_tests_or_nonzero_exit_never_pass(self) -> None:
        self.save()
        for status, output in ((0, b"test result: ok. 0 passed; 0 failed; 0 ignored;"),
                               (1, b"test result: FAILED")):
            with patch.object(artifacts, "cargo_environment", return_value={}), \
                    patch.object(artifacts, "run_owned", side_effect=[(0, listing(self.suite)), (status, output)]), \
                    redirect_stdout(io.StringIO()), self.assertRaises(artifacts.ArtifactError):
                artifacts.run_suite(self.repo, self.inventory, self.suite, {})


class SelectionTests(unittest.TestCase):
    def test_success_retires_timer_before_reap_and_never_signals_a_reaped_pid(self) -> None:
        cwd = Path.cwd()
        timer = Mock()
        process = Mock(returncode=None, pid=42, stdout=io.BytesIO(b"done"))

        def reap(*, timeout: int) -> int:
            self.assertTrue(timer.cancel.called)
            self.assertTrue(timer.join.called)
            process.returncode = 0
            return 0

        process.wait.side_effect = reap
        with patch.object(artifacts.subprocess, "Popen", return_value=process), \
                patch.object(artifacts.threading, "Timer", return_value=timer), \
                patch.object(artifacts.os, "name", "posix"), \
                patch.object(artifacts.os, "killpg", create=True) as kill:
            self.assertEqual(artifacts.run_owned(["fixture"], cwd=cwd, env={}, timeout=5, maximum=16),
                             (0, b"done"))
        kill.assert_not_called()
        process.kill.assert_not_called()

    def test_expected_exact_lists_cover_both_exporters_and_three_currentness_cases(self) -> None:
        for suite in artifacts.SUITES.values():
            artifacts.validate_listing(listing(suite), suite)
            for value in (b"0 tests, 0 benchmarks\n", listing(suite).replace(b": test", b": benchmark", 1),
                          listing(suite) + b"unexpected: test\n", listing(suite).replace(b"real_policy", b"old_policy")):
                if value == listing(suite):
                    continue
                with self.subTest(value=value), self.assertRaises(artifacts.ArtifactError):
                    artifacts.validate_listing(value, suite)
        self.assertEqual(len(artifacts.SUITES["trust-currentness"].names), 4)

    def test_source_identity_is_checked_without_running_tests_on_mismatch(self) -> None:
        commit = "a" * 40
        with patch.object(artifacts, "run_owned", return_value=(0, (commit + "\n").encode())) as run:
            artifacts.require_source(Path.cwd(), commit, {})
            self.assertIn("gc.auto=0", run.call_args.args[0])
            for wrong in (None, "not-a-commit", "b" * 40):
                with self.subTest(wrong=wrong), self.assertRaises(artifacts.ArtifactError):
                    artifacts.require_source(Path.cwd(), wrong, {})

    def test_cargo_dynamic_environment_preserves_fixture_inputs_and_prior_search_path(self) -> None:
        root = Path.cwd().resolve()
        artifact = artifacts.Artifact(root / "test", root / "crates/latent-policy", ())
        key = "PATH" if os.name == "nt" else ("DYLD_FALLBACK_LIBRARY_PATH" if sys.platform == "darwin"
                                              else "LD_LIBRARY_PATH")
        base = {key: "existing", "LSF_OPERATOR_FIXTURE_ROOT": "fresh"}
        with patch.object(artifacts, "run_owned", return_value=(0, str(root).encode())):
            env = artifacts.cargo_environment(root, artifact, base)
        self.assertTrue(env[key].endswith(os.pathsep + "existing"))
        self.assertEqual(env["LSF_OPERATOR_FIXTURE_ROOT"], "fresh")
        self.assertEqual(env["CARGO_MANIFEST_DIR"], str(artifact.package))
        self.assertEqual(base[key], "existing")

    def test_owned_process_rejects_excess_output_and_reaps(self) -> None:
        with self.assertRaisesRegex(artifacts.ArtifactError, "output-limit"):
            artifacts.run_owned([sys.executable, "-c", "print('x' * 1000)"], cwd=Path.cwd(),
                                env=dict(os.environ), timeout=5, maximum=16)

    def test_owned_process_times_out_and_reaps(self) -> None:
        with self.assertRaisesRegex(artifacts.ArtifactError, "timeout"):
            artifacts.run_owned([sys.executable, "-c", "import time; time.sleep(30)"], cwd=Path.cwd(),
                                env=dict(os.environ), timeout=0.1, maximum=16)


if __name__ == "__main__":
    unittest.main()
