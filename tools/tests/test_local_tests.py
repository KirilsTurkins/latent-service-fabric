"""Compiler/network-free planning, receipt, delegation and real source-only runs."""
from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
import copy
import io
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from tools import ci_rust_artifacts as artifacts
from tools import local_tests as local
from tools import local_test_support as support
from tools.local_python_suite import result_summary

ROOT = Path(__file__).resolve().parents[2]
SOURCE = {"commit": "a" * 40, "dirty": False}


def invoke(arguments: list[str], repo: Path = ROOT) -> tuple[int, object]:
    output = io.StringIO()
    with redirect_stdout(output), redirect_stderr(io.StringIO()):
        code = local.main([*arguments, "--output", "json"], repo=repo)
    return code, json.loads(output.getvalue())


def receipt(plan: dict | None = None, **changes: object) -> dict:
    plan = plan or local.plan_suite(ROOT, local.TOOLING)
    result = {
        "schema": support.SCHEMA, "suite": plan["suite"], "case": plan["selected_case"],
        "source": dict(SOURCE), "host": support.host_identity(), "recipe": plan["recipe_identity"],
        "fixtures": "source-only", "options": {}, "state": "failed", "exit_code": 1,
        "required_cases": len(plan["cases"]), "observed_cases": len(plan["cases"]),
        "failed_cases": [plan["cases"][0]],
    }
    result.update(changes)
    return result


class PlanningTests(unittest.TestCase):
    def test_planning_is_compiler_network_and_process_free(self) -> None:
        with patch.object(artifacts, "run_owned", side_effect=AssertionError("planning launched a process")):
            for name in local.suite_ids():
                code, plan = invoke(["plan", "--suite", name])
                self.assertEqual(code, 0)
                self.assertGreater(plan["required_case_count"], 0)
            self.assertEqual(invoke(["list"])[0], 0)

    def test_local_ci_semantic_plans_and_recipe_digests_are_identical(self) -> None:
        for name in local.suite_ids():
            for case in (None, local.plan_suite(ROOT, name)["cases"][0]):
                left = local.plan_suite(ROOT, name, case, "local")
                right = local.plan_suite(ROOT, name, case, "ci")
                self.assertEqual(left.pop("context"), "local")
                self.assertEqual(right.pop("context"), "ci")
                self.assertEqual(left, right)

    def test_legacy_suites_are_read_from_the_live_owner_not_copied(self) -> None:
        original = artifacts.SUITES["operator-fixture"]
        suite = artifacts.Suite(original.manifest, original.target, original.source,
                                "new::case", frozenset({"new::case"}), True)
        with patch.dict(artifacts.SUITES, {"new-owner-suite": suite}):
            plan = local.plan_suite(ROOT, "new-owner-suite")
        self.assertEqual(plan["cases"], ["new::case"])
        self.assertEqual(plan["legacy_selection"]["filter"], "new::case")
        self.assertFalse(plan["ready"])
        self.assertIsNone(plan["recipe"])
        self.assertIsNone(plan["fixtures"])

    def test_missing_native_metadata_is_not_manufactured(self) -> None:
        for name in artifacts.SUITES:
            plan = local.plan_suite(ROOT, name)
            self.assertEqual(plan["platforms"], [])
            self.assertIn("#427", plan["classification"])
            self.assertIn("#428", plan["blockers"][0])

    def test_custom_harness_does_not_fall_back_to_libtest(self) -> None:
        with patch.dict(artifacts.SUITES, {"custom-main": object()}):
            with self.assertRaisesRegex(support.LocalTestError, "harness"):
                local.plan_suite(ROOT, "custom-main")

    def test_unknown_suite_case_and_empty_filter_fail_before_launch(self) -> None:
        for suite, case in (("all", None), (local.TOOLING, ""), (local.TOOLING, "InventoryTests"),
                            (local.TOOLING, "test_success;curl example.invalid")):
            with self.subTest(suite=suite, case=case), self.assertRaises(support.LocalTestError):
                local.plan_suite(ROOT, suite, case)

    def test_exact_case_does_not_broaden_selection(self) -> None:
        case = local.plan_suite(ROOT, local.TOOLING)["cases"][0]
        plan = local.plan_suite(ROOT, local.TOOLING, case)
        self.assertEqual(plan["required_case_count"], 1)
        self.assertEqual(plan["command"][-2:], ["--case", case])
        self.assertEqual(plan["prepare_command"][-2:], ["--case", case])

    def test_empty_and_duplicate_declarations_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / local.TEST_SOURCE
            path.parent.mkdir(parents=True)
            for text in ("", "import unittest\nclass T(unittest.TestCase):\n def test_a(self): pass\n def test_a(self): pass\n"):
                path.write_text(text)
                with self.assertRaises(support.LocalTestError):
                    local.tooling_cases(root)

    def test_planner_does_not_import_or_execute_test_source(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / local.TEST_SOURCE
            path.parent.mkdir(parents=True)
            path.write_text("raise RuntimeError('must not execute')\nimport unittest\nclass T(unittest.TestCase):\n def test_a(self): pass\n")
            self.assertEqual(len(local.tooling_cases(root)), 1)

    def test_native_prepare_and_run_fail_without_invoking_legacy_runner(self) -> None:
        with patch.object(artifacts, "run_owned", side_effect=AssertionError("unexpected command")), \
                patch.object(artifacts, "run_suite", side_effect=AssertionError("unvalidated execution")):
            for command in ("check", "prepare", "run"):
                code, result = invoke([command, "--suite", "browser-boundary"])
                self.assertEqual(code, 3)
                self.assertEqual(result["state"], "not-run")
                self.assertIn("#428", json.dumps(result))

    def test_prepare_source_only_inputs_does_not_execute_tests(self) -> None:
        with patch.object(local, "source_identity", return_value=SOURCE), \
                patch.object(local, "execute", side_effect=AssertionError("prepare ran tests")):
            code, result = invoke(["prepare", "--suite", local.TOOLING])
        self.assertEqual(code, 0)
        self.assertEqual(result["state"], "prepared")

    def test_run_requires_explicit_suite_and_no_arbitrary_extra_commands(self) -> None:
        for args in (["run"], ["run", "--suite", local.TOOLING, "--", "cargo", "test"],
                     ["run", "--suit", local.TOOLING]):
            with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
                local.parser().parse_args(args)
            self.assertEqual(error.exception.code, 2)


class DriftTests(unittest.TestCase):
    def test_documented_commands_parse_and_reference_live_suites(self) -> None:
        guide = (ROOT / "docs/development/local-tests.md").read_text()
        commands = [shlex.split(line.strip()) for line in guide.splitlines()
                    if line.strip().startswith("python3 tools/test.py ")]
        self.assertGreaterEqual(len(commands), 15)
        seen = set()
        with patch.object(artifacts, "run_owned", side_effect=AssertionError("documentation executed")):
            for command in commands:
                args = local.parser().parse_args(command[2:])
                seen.add(args.command)
                if hasattr(args, "suite"):
                    local.plan_suite(ROOT, args.suite, args.case)
        self.assertEqual(seen, {"list", "explain", "plan", "check", "prepare", "run",
                                "reproduce", "preview", "doctor"})
        self.assertIn("docs/development/local-tests.md", (ROOT / "CONTRIBUTING.md").read_text())

    def test_workflow_uses_same_entrypoints_and_keeps_legacy_native_coverage(self) -> None:
        workflow = (ROOT / ".github/workflows/ci.yml").read_text()
        commands = [shlex.split(line.strip()) for line in workflow.splitlines()
                    if line.strip().startswith("python3 tools/test.py ")]
        self.assertEqual(len(commands), 3)
        self.assertEqual([argv[2] for argv in commands], ["check", "prepare", "run"])
        for command in commands:
            args = local.parser().parse_args(command[2:])
            self.assertEqual((args.suite, args.case, args.context), (local.TOOLING, None, "ci"))
            left = local.plan_suite(ROOT, args.suite, args.case, args.context)
            right = local.plan_suite(ROOT, args.suite, args.case, "local")
            left.pop("context")
            right.pop("context")
            self.assertEqual(left, right)
        self.assertIn("python3 -m unittest tools.tests.test_local_tests", workflow)
        self.assertIn("python3 -m unittest tools.tests.test_phase2_resource_binaries", workflow)
        self.assertNotIn("python3 -m unittest tools.tests.test_ci_rust_artifacts ", workflow)
        selected = set()
        for line in workflow.splitlines():
            if "python3 tools/ci_rust_artifacts.py " in line:
                argv = shlex.split(line.strip())
                selected.add(argv[argv.index("--suite") + 1])
        self.assertEqual(selected, set(artifacts.SUITES))


class ReceiptTests(unittest.TestCase):
    def test_valid_receipt_and_same_input_reproduction(self) -> None:
        plan = local.plan_suite(ROOT, local.TOOLING)
        record = receipt(plan)
        self.assertIs(support.validate_report(record), record)
        self.assertEqual(support.reproduce_selection(record, plan, SOURCE, support.host_identity()),
                         "same-input-selection")

    def test_commands_environment_secrets_and_unknown_options_are_rejected(self) -> None:
        for key, value in (("command", ["sh", "-c", "false"]), ("env", {"TOKEN": "secret"}),
                           ("options", {"TOKEN": "secret"}), ("fixtures", "arbitrary-native-image")):
            record = receipt()
            record[key] = value
            with self.subTest(key=key), self.assertRaises(support.LocalTestError):
                support.validate_report(record)

    def test_nested_unknown_keys_and_bad_types_are_rejected(self) -> None:
        variants = [receipt(source={**SOURCE, "path": "/private"}), receipt(case="x;sh"),
                    receipt(required_cases=True), receipt(observed_cases=999),
                    receipt(state=[]), receipt(options={"threads": 8}), receipt(exit_code=0),
                    receipt(suite="../../other"), receipt(host={"platform": "x", "machine": "/private", "python": "3"}),
                    receipt(failed_cases=[[]]), receipt(required_cases=0)]
        for record in variants:
            with self.subTest(record=record), self.assertRaises(support.LocalTestError):
                support.validate_report(record)

    def test_unknown_schema_does_not_guess_rich_failure_contract(self) -> None:
        with self.assertRaisesRegex(support.LocalTestError, "#426/#434"):
            support.validate_report(receipt(schema="latent.future.failure.v9"))

    def test_duplicate_keys_oversize_and_deep_json_fail_bounded(self) -> None:
        for raw in (b'{"schema":1,"schema":2}', b" " * (support.MAX_JSON + 1), b"[" * 2000):
            with self.subTest(size=len(raw)), self.assertRaises(support.LocalTestError):
                support.decode(raw)

    def test_changed_dirty_checkout_and_host_never_claim_exact(self) -> None:
        plan = local.plan_suite(ROOT, local.TOOLING)
        for source, host in (({**SOURCE, "dirty": True}, support.host_identity()),
                             ({**SOURCE, "commit": "b" * 40}, support.host_identity()),
                             (SOURCE, {**support.host_identity(), "python": "0.0.0"})):
            with self.assertRaisesRegex(support.LocalTestError, "not exact"):
                support.reproduce_selection(receipt(plan), plan, source, host)
            self.assertEqual(support.reproduce_selection(receipt(plan), plan, source, host, allow_changed=True),
                             "changed-input-rerun")

    def test_same_dirty_source_is_not_an_exact_reproduction(self) -> None:
        plan = local.plan_suite(ROOT, local.TOOLING)
        source = {**SOURCE, "dirty": True}
        with self.assertRaises(support.LocalTestError):
            support.reproduce_selection(receipt(plan, source=source), plan, source, support.host_identity())

    def test_allow_changed_never_bypasses_recipe_case_count_or_selection(self) -> None:
        plan = local.plan_suite(ROOT, local.TOOLING)
        for record in (receipt(plan, recipe="sha256:" + "0" * 64),
                       receipt(plan, failed_cases=["not.a.selected.case"]),
                       receipt(plan, required_cases=len(plan["cases"]) + 1)):
            with self.assertRaises(support.LocalTestError):
                support.reproduce_selection(record, plan, SOURCE, support.host_identity(), allow_changed=True)

    def test_passing_run_is_not_a_failure_record(self) -> None:
        plan = local.plan_suite(ROOT, local.TOOLING)
        record = receipt(plan, state="passed", exit_code=0, failed_cases=[])
        with self.assertRaisesRegex(support.LocalTestError, "passed"):
            support.reproduce_selection(record, plan, SOURCE, support.host_identity())

    def test_private_exclusive_report_creation_does_not_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "result.json"
            support.write_report(path, receipt())
            first = path.read_bytes()
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(support.validate_report(support.decode(support.bounded_read(path)))["suite"], local.TOOLING)
            with self.assertRaises(FileExistsError):
                support.write_report(path, receipt())
            self.assertEqual(path.read_bytes(), first)
            self.assertNotIn(b"/private", first)
            self.assertNotIn(b"PATH", first)

    @unittest.skipUnless(os.name == "posix", "POSIX no-follow and special-file checks")
    def test_symlink_and_fifo_reports_are_never_read_or_overwritten(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "target"
            target.write_text("private")
            link = root / "link"
            link.symlink_to(target)
            with self.assertRaises(OSError):
                support.bounded_read(link)
            with self.assertRaises(FileExistsError):
                support.write_report(link, receipt())
            fifo = root / "fifo"
            os.mkfifo(fifo)
            with self.assertRaises(support.LocalTestError):
                support.bounded_read(fifo)
            self.assertEqual(target.read_text(), "private")


class ExecutionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.plan = local.plan_suite(ROOT, local.TOOLING)

    def output(self, **changes: object) -> bytes:
        data = {"cases": self.plan["cases"], "observed_cases": len(self.plan["cases"]),
                "failed_cases": [], "state": "passed"}
        data.update(changes)
        return local.MARKER + json.dumps(data).encode()

    def test_only_complete_expected_case_execution_can_pass(self) -> None:
        self.assertEqual(local.summarize_output(self.output(), 0, self.plan)["state"], "passed")
        for output in (b"", self.output(cases=[]), self.output(observed_cases=0),
                       self.output(cases=self.plan["cases"] + ["extra.case"]),
                       self.output(state="not-run"), self.output(failed_cases=[self.plan["cases"][0]])):
            result = local.summarize_output(output, 0, self.plan)
            self.assertNotEqual(result["exit_code"], 0)
            self.assertEqual(result["state"], "failed")

    def test_nonzero_exit_and_signal_are_preserved(self) -> None:
        self.assertEqual(local.summarize_output(b"crashed", 37, self.plan)["exit_code"], 37)
        result = local.summarize_output(b"", -15, self.plan)
        self.assertEqual((result["state"], result["exit_code"]), ("cancelled", 143))

    def test_skipped_case_is_not_a_passing_required_case(self) -> None:
        result = unittest.TestResult()
        case = unittest.FunctionTestCase(lambda: None)
        result.startTest(case)
        result.addSkip(case, "unavailable")
        result.stopTest(case)
        code, data = result_summary([case.id()], result)
        self.assertEqual((code, data["state"]), (3, "not-run"))

    def test_expected_failure_and_unexpected_success_keep_unittest_semantics(self) -> None:
        case = unittest.FunctionTestCase(lambda: None)
        result = unittest.TestResult()
        result.testsRun = 1
        result.expectedFailures = [(case, "expected")]
        self.assertEqual(result_summary([case.id()], result)[0], 0)
        result.unexpectedSuccesses = [case]
        self.assertEqual(result_summary([case.id()], result)[0], 1)

    def test_watchdog_overflow_interrupt_and_spawn_failure_are_distinct(self) -> None:
        for error, state, code in ((artifacts.ArtifactError("test-timeout"), "failed", 124),
                                   (artifacts.ArtifactError("test-output-limit"), "failed", 125),
                                   (KeyboardInterrupt(), "cancelled", 130),
                                   (local.Terminated(), "cancelled", 143),
                                   (FileNotFoundError(), "not-run", 3)):
            with patch.object(artifacts, "run_owned", side_effect=error) as run, \
                    patch.object(local, "source_identity", return_value=SOURCE):
                data = local.execute(ROOT, self.plan, SOURCE)
            self.assertEqual((data["state"], data["exit_code"]), (state, code))
            self.assertEqual(run.call_count, 1)  # no automatic test retry

    def test_source_changed_during_execution_is_marked_non_exact(self) -> None:
        with patch.object(artifacts, "run_owned", return_value=(0, self.output())), \
                patch.object(local, "source_identity", return_value={**SOURCE, "commit": "b" * 40}):
            data = local.execute(ROOT, self.plan, SOURCE)
        self.assertTrue(data["source"]["dirty"])

    def test_report_does_not_retain_log_tail_or_credentials(self) -> None:
        with patch.object(artifacts, "run_owned", return_value=(1, b"TOKEN=secret /private/home\n")), \
                patch.object(local, "source_identity", return_value=SOURCE), redirect_stderr(io.StringIO()):
            data = local.execute(ROOT, self.plan, SOURCE)
        self.assertNotIn("secret", json.dumps(data))
        self.assertNotIn("private", json.dumps(data))

    def test_child_environment_does_not_replay_credentials_or_actions_outputs(self) -> None:
        with patch.dict(os.environ, {"GITHUB_TOKEN": "secret", "GITHUB_OUTPUT": "/private/out",
                                    "AWS_SECRET_ACCESS_KEY": "secret", "PYTHONPATH": "/private/code",
                                    "GIT_DIR": "/foreign"}):
            env = support.environment()
        for name in ("GITHUB_TOKEN", "GITHUB_OUTPUT", "AWS_SECRET_ACCESS_KEY", "PYTHONPATH", "GIT_DIR"):
            self.assertNotIn(name, env)
        self.assertEqual(env["PYTHONDONTWRITEBYTECODE"], "1")


class DelegationTests(unittest.TestCase):
    def test_missing_optional_interfaces_do_not_fallback_to_full_checks(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.object(artifacts, "run_owned", side_effect=AssertionError("optional tool absent")):
                for command in (["preview", "--base", "development"], ["doctor", "--scope", "python"]):
                    code, data = invoke(command, root)
                    self.assertEqual((code, data["state"]), (3, "not-run"))

    def test_old_version_checker_is_not_executed_even_with_help(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "tools/check_tool_versions.py"
            path.parent.mkdir()
            path.write_text("raise RuntimeError('legacy checker would probe all SDKs')\n")
            with patch.object(artifacts, "run_owned", side_effect=AssertionError("unscoped probe")):
                code, data = invoke(["doctor", "--scope", "python"], root)
            self.assertEqual(code, 3)
            self.assertIn("all-SDK", data["reason"])

    def test_available_optional_tools_receive_only_their_arguments(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "tools").mkdir()
            (root / "tools/preview_ci.py").write_text("# delegated interface\n")
            (root / "tools/check_tool_versions.py").write_text("parser.add_argument('--scope')\n")
            with patch.object(artifacts, "run_owned", return_value=(9, b'{"delegated": true}\n')) as run:
                self.assertEqual(invoke(["preview", "--base", "development", "--worktree"], root)[0], 9)
                argv = run.call_args.args[0]
                self.assertIn("--worktree", argv)
                self.assertNotIn("--head", argv)
                self.assertNotIn("GITHUB_OUTPUT", run.call_args.kwargs["env"])
                self.assertEqual(invoke(["doctor", "--scope", "python"], root)[0], 9)
                self.assertEqual(run.call_args.args[0][-5:], ["--scope", "python", "--report-all", "--output", "json"])


class RealCheckoutTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for name in ("tools/test.py", "tools/local_tests.py", "tools/local_test_support.py",
                     "tools/local_python_suite.py", "tools/ci_rust_artifacts.py", local.TEST_SOURCE):
            target = self.root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / name, target)
        (self.root / ".gitignore").write_text("__pycache__/\ntarget/\n")
        self.git("init", "-q")
        self.commit()

    def git(self, *args: str) -> None:
        subprocess.run(["git", "-c", "user.name=Local Test", "-c", "user.email=test@example.invalid", *args],
                       cwd=self.root, env=support.environment(), check=True, capture_output=True, timeout=15)

    def commit(self) -> None:
        self.git("add", ".")
        self.git("commit", "-qm", "source-only test fixture")

    def cli(self, *args: str, env: dict | None = None) -> subprocess.CompletedProcess:
        return subprocess.run([sys.executable, "tools/test.py", *args, "--output", "json"],
                              cwd=self.root, env=env or support.environment(),
                              capture_output=True, text=True, timeout=30)

    def test_real_prepared_suite_uses_no_compiler_or_network_tools(self) -> None:
        (self.root / "target").mkdir()
        sentinels = self.root / "target/sentinels"
        sentinels.mkdir()
        invoked = self.root / "target/forbidden-command"
        for name in ("cargo", "rustc", "npm", "node", "docker", "curl", "wget", "pip"):
            path = sentinels / name
            path.write_text(f"#!/bin/sh\nprintf '%s' {shlex.quote(name)} >> {shlex.quote(str(invoked))}\nexit 97\n")
            path.chmod(0o755)
        env = support.environment()
        env["PATH"] = str(sentinels) + os.pathsep + os.environ.get("PATH", "")
        for verb in ("check", "prepare", "run"):
            proc = self.cli(verb, "--suite", local.TOOLING, env=env)
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        result = json.loads(proc.stdout)
        self.assertEqual((result["required_cases"], result["observed_cases"]), (15, 15))
        self.assertEqual(result["state"], "passed")
        self.assertFalse(invoked.exists())

    def test_actual_injected_failure_exact_reproduction_and_changed_checkout(self) -> None:
        source = self.root / local.TEST_SOURCE
        source.write_text(source.read_text().replace('len(artifacts.SUITES["trust-currentness"].names), 4',
                                                    'len(artifacts.SUITES["trust-currentness"].names), 5'))
        self.commit()
        (self.root / "target").mkdir()
        case = local.MODULE + ".SelectionTests.test_expected_exact_lists_cover_both_exporters_and_three_currentness_cases"
        failed = self.cli("run", "--suite", local.TOOLING, "--case", case, "--record", "target/failure.json")
        self.assertEqual(failed.returncode, 1, failed.stdout + failed.stderr)
        data = json.loads(failed.stdout)
        self.assertEqual(data["failed_cases"], [case])
        self.assertEqual((data["required_cases"], data["observed_cases"]), (1, 1))
        repeated = self.cli("reproduce", "target/failure.json")
        self.assertEqual(repeated.returncode, 1, repeated.stdout + repeated.stderr)
        self.assertEqual(json.loads(repeated.stdout)["reproduction"], "same-input-selection")
        source.write_text(source.read_text() + "\n# changed checkout\n")
        rejected = self.cli("reproduce", "target/failure.json")
        self.assertEqual(rejected.returncode, 3)
        self.assertIn("not exact", rejected.stdout)
        labelled = self.cli("reproduce", "target/failure.json", "--allow-changed-checkout")
        self.assertEqual(labelled.returncode, 1)
        self.assertEqual(json.loads(labelled.stdout)["reproduction"], "changed-input-rerun")

    def test_actual_git_dirty_detection_is_read_only_and_includes_untracked(self) -> None:
        index = (self.root / ".git/index").read_bytes()
        self.assertFalse(support.source_identity(self.root)["dirty"])
        self.assertEqual((self.root / ".git/index").read_bytes(), index)
        (self.root / "untracked file.txt").write_text("local input")
        self.assertTrue(support.source_identity(self.root)["dirty"])
        self.assertEqual((self.root / ".git/index").read_bytes(), index)


if __name__ == "__main__":
    unittest.main()
