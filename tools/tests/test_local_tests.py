from __future__ import annotations

import io
import json
from pathlib import Path
import shlex
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch
from contextlib import redirect_stderr, redirect_stdout

from tools import ci_suite_inventory as registry
from tools import local_tests as local

ROOT = Path(__file__).resolve().parents[2]
CORE = "latent-core.lib.latent-core"
ECHO = "latent-wasmtime.test.echo-backend"
CUSTOM = "latent-wasmtime.test.aot-supervisor"
METADATA = "selection.metadata-working-set"
PROVIDER = "selection.s3-blobs"


def invoke(argv: list[str], repo: Path = ROOT) -> tuple[int, object]:
    stdout = io.StringIO()
    stderr = io.StringIO()
    with redirect_stdout(stdout), redirect_stderr(stderr):
        code = local.main([*argv, "--output", "json"], repo=repo)
    lines = [line for line in stdout.getvalue().splitlines() if line.strip()]
    return code, json.loads(lines[-1])


class PlanningTests(unittest.TestCase):
    def test_planning_reads_only_the_shared_inventory(self) -> None:
        with patch.object(local.artifacts, "run_owned", side_effect=AssertionError("planning executed a process")), \
                patch.object(local, "run_bounded", side_effect=AssertionError("planning compiled")):
            ids = local.identities(ROOT)
            self.assertIn(CORE, ids)
            self.assertIn(METADATA, ids)
            plan = local.plan_suite(ROOT, CORE)
        data = registry.load()
        row = next(item for item in data["suites"] if item["id"] == CORE)
        self.assertEqual(plan["recipe"], row["recipe"])
        self.assertEqual(plan["recipeDefinition"], data["recipes"][row["recipe"]])
        self.assertEqual(plan["cases"], row["expectedCases"])
        self.assertEqual(plan["requiredCaseCount"], len(row["expectedCases"]))
        self.assertEqual(plan["prerequisites"], row["prerequisites"])

    def test_exact_host_case_never_becomes_a_substring_filter(self) -> None:
        case = "digest::tests::canonical_sha256_text_round_trips_in_each_identity_domain"
        plan = local.plan_suite(ROOT, CORE, case)
        self.assertEqual(plan["cases"], [case])
        self.assertEqual(plan["case"], case)
        self.assertTrue(plan["runSupported"])
        with self.assertRaisesRegex(local.LocalTestError, "exact case"):
            local.plan_suite(ROOT, CORE, "digest::tests")

    def test_ignored_runtime_suite_requires_an_exact_case(self) -> None:
        broad = local.plan_suite(ROOT, ECHO)
        self.assertFalse(broad["runSupported"])
        self.assertIn("opt-in", broad["blocker"])
        case = "invokes_echo_through_the_execution_backend_and_enforces_the_phase_zero_boundary"
        exact = local.plan_suite(ROOT, ECHO, case)
        self.assertTrue(exact["runSupported"])
        self.assertEqual(exact["selectedIgnoredCases"], [case])

    def test_custom_harness_is_never_treated_as_libtest(self) -> None:
        plan = local.plan_suite(ROOT, CUSTOM)
        self.assertEqual(plan["mode"], "custom")
        self.assertFalse(plan["runSupported"])
        self.assertIn("custom harness", plan["blocker"])
        self.assertEqual(plan["runner"], "custom-owner")

    def test_registered_selection_reuses_same_owner_and_cases(self) -> None:
        data = registry.load()
        expected = data["selections"]["metadata-working-set"]
        plan = local.plan_suite(ROOT, METADATA)
        self.assertEqual(plan["ownerSuite"], expected["suite"])
        self.assertEqual(plan["cases"], expected["names"])
        self.assertEqual(plan["runner"], expected["runner"])
        self.assertTrue(plan["runSupported"])
        self.assertEqual(plan["classification"], "explicit qualification")

    def test_provider_selection_keeps_its_existing_fixture_owner(self) -> None:
        plan = local.plan_suite(ROOT, PROVIDER)
        self.assertFalse(plan["runSupported"])
        self.assertEqual(plan["runner"], "provider-owner")
        self.assertIn("fixture/service owner", plan["blocker"])

    def test_prepare_and_run_commands_keep_exact_suite_and_case(self) -> None:
        case = "digest::tests::canonical_sha256_text_round_trips_in_each_identity_domain"
        plan = local.plan_suite(ROOT, CORE, case)
        for key in ("command",):
            self.assertEqual(plan["preparation"][key][3:7], ["--suite", CORE, "--case", case])
        self.assertEqual(plan["runCommand"][3:7], ["--suite", CORE, "--case", case])
        self.assertIn("--inventory", plan["runCommand"])


class CommandTests(unittest.TestCase):
    def test_run_requires_explicit_suite_and_prepared_inventory(self) -> None:
        for argv in (["run"], ["run", "--suite", CORE], ["run", "--suit", CORE, "--inventory", "x"]):
            with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                local.parser().parse_args(argv)

    def test_check_missing_inventory_is_not_success(self) -> None:
        code, result = invoke(["check", "--suite", CORE])
        self.assertEqual(code, 3)
        self.assertEqual(result["state"], "needs-preparation")
        self.assertIn("prepared Cargo inventory is missing", result["problems"])
        self.assertEqual(result["prepareCommand"][2], "prepare")

    def test_prepare_reuses_existing_inventory_without_build(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            inventory = Path(directory) / "cargo.jsonl"
            inventory.write_text("{}\n")
            plan = local.plan_suite(ROOT, CORE, inventory=inventory)
            with patch.object(local, "validate_prepared") as validate, \
                    patch.object(local, "run_bounded", side_effect=AssertionError("unexpected build")):
                result = local.prepare(ROOT, plan, inventory)
            validate.assert_called_once_with(ROOT, plan, inventory)
            self.assertTrue(result["reused"])

    def test_prepare_uses_only_the_registered_build_recipe(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            inventory = Path(directory) / "cargo.jsonl"
            plan = local.plan_suite(ROOT, CORE, inventory=inventory)
            completed = SimpleNamespace(returncode=0, stdout=b'{"reason":"build-finished","success":true}\n',
                                        stderr=b"")
            with patch.object(local.shutil, "which", return_value="/usr/bin/cargo"), \
                    patch.object(local, "run_bounded", return_value=completed) as run, \
                    patch.object(local, "validate_prepared"):
                result = local.prepare(ROOT, plan, inventory)
            self.assertFalse(result["reused"])
            self.assertEqual(run.call_args.args[0], plan["recipeDefinition"]["build"])
            self.assertEqual(inventory.read_bytes(), completed.stdout)

    def test_optional_interfaces_do_not_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for argv in (["preview", "--base", "development"], ["doctor", "--scope", "python"]):
                code, result = invoke(argv, root)
                self.assertEqual(code, 3)
                self.assertEqual(result["state"], "not-run")

    def test_unscoped_version_checker_is_not_executed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "tools").mkdir()
            (root / "tools/check_tool_versions.py").write_text("raise RuntimeError('must not execute')\n")
            with patch.object(local.artifacts, "run_owned", side_effect=AssertionError("unscoped checker executed")):
                code, result = invoke(["doctor", "--scope", "python"], root)
            self.assertEqual(code, 3)
            self.assertIn("all-SDK fallback", result["reason"])


class FailureRecordTests(unittest.TestCase):
    def record(self, **changes: object) -> dict:
        value = {
            "schemaVersion": "latent.test-run.v1",
            "suite": CORE,
            "runId": "0" * 32,
            "outcome": "failed",
            "category": "assertion-failure",
            "reason": "selected-test-failed",
            "stage": "execution",
            "evidenceKind": "runner-diagnostic-not-qualification",
            "source": {"revision": "a" * 40, "dirty": False, "observed": True},
            "fixtures": {"test-manifest": "sha256:" + "1" * 64},
            "child": {"exit": 1, "signal": None, "cleanupAcknowledged": True},
            "elapsedMs": 1.0,
            "timings": [],
            "startupMs": 0.1,
            "teardownMs": 0.1,
            "cleanupFailures": [],
            "logTail": "",
            "reproduction": {
                "suite": CORE,
                "cases": ["digest::tests::canonical_sha256_text_round_trips_in_each_identity_domain"],
                "recipe": "workspace-all-features",
                "mode": "libtest",
                "source": {"revision": "a" * 40, "dirty": False, "observed": True},
                "fixtures": {"test-manifest": "sha256:" + "1" * 64},
            },
        }
        value.update(changes)
        return value

    def test_bounded_failure_record_accepts_only_sanitized_selection(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "failure.json"
            path.write_text(json.dumps(self.record()))
            self.assertEqual(local.read_failure(path)["reproduction"]["suite"], CORE)
            unsafe = self.record()
            unsafe["reproduction"]["command"] = ["sh", "-c", "false"]
            path.write_text(json.dumps(unsafe))
            with self.assertRaisesRegex(local.LocalTestError, "unsafe"):
                local.read_failure(path)

    def test_passing_unknown_duplicate_and_oversized_records_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "failure.json"
            cases = [
                json.dumps(self.record(outcome="passed")).encode(),
                json.dumps({**self.record(), "future": True}).encode(),
                b'{"schemaVersion":"latent.test-run.v1","schemaVersion":"latent.test-run.v1"}',
                b" " * (local.MAX_REPORT + 1),
            ]
            for raw in cases:
                path.write_bytes(raw)
                with self.subTest(size=len(raw)), self.assertRaises(local.LocalTestError):
                    local.read_failure(path)

    def test_reproduction_does_not_accept_a_different_artifact_identity(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            report = root / "failure.json"
            inventory = root / "cargo.jsonl"
            inventory.write_bytes(b"prepared")
            record = self.record()
            report.write_text(json.dumps(record))
            with patch.object(local, "validate_prepared"), \
                    patch.object(local, "plan_suite", return_value={
                        "suite": CORE,
                        "cases": record["reproduction"]["cases"],
                        "recipe": "workspace-all-features",
                    }):
                with self.assertRaisesRegex(local.LocalTestError, "does not match"):
                    local.reproduce(ROOT, report, inventory, False)

    def test_changed_checkout_requires_explicit_label_even_with_same_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            report = Path(directory) / "failure.json"
            inventory = Path(directory) / "cargo.jsonl"
            inventory.write_bytes(b"prepared")
            record = self.record()
            digest = local.file_digest(inventory, local.artifacts.MAX_INVENTORY_BYTES)
            record["fixtures"]["test-manifest"] = digest
            record["reproduction"]["fixtures"]["test-manifest"] = digest
            report.write_text(json.dumps(record))
            plan = {
                "suite": CORE,
                "cases": record["reproduction"]["cases"],
                "recipe": "workspace-all-features",
            }
            changed = {"revision": "b" * 40, "dirty": False, "observed": True}
            with patch.object(local, "validate_prepared"), \
                    patch.object(local, "plan_suite", return_value=plan), \
                    patch.object(local, "_source", return_value=changed), \
                    patch.object(local, "execute", return_value=(1, {"outcome": "failed"})):
                with self.assertRaisesRegex(local.LocalTestError, "not an exact reproduction"):
                    local.reproduce(ROOT, report, inventory, False)
                code, result = local.reproduce(ROOT, report, inventory, True)
            self.assertEqual(code, 1)
            self.assertEqual(result["reproduction"], "changed-input-rerun")


class DriftTests(unittest.TestCase):
    def test_documented_commands_parse_and_cover_three_workflows(self) -> None:
        guide = (ROOT / "docs/development/local-tests.md").read_text(encoding="utf-8")
        commands = [shlex.split(line.strip()) for line in guide.splitlines()
                    if line.strip().startswith("python3 tools/test.py ")]
        self.assertGreaterEqual(len(commands), 12)
        seen = set()
        with patch.object(local.artifacts, "run_owned", side_effect=AssertionError("docs executed")), \
                patch.object(local, "run_bounded", side_effect=AssertionError("docs compiled")):
            for command in commands:
                args = local.parser().parse_args(command[2:])
                seen.add(args.command)
                if hasattr(args, "suite"):
                    local.plan_suite(ROOT, args.suite, getattr(args, "case", None))
        self.assertTrue({"list", "explain", "plan", "check", "prepare", "run", "reproduce",
                         "preview", "doctor"} <= seen)
        for heading in ("Small Rust logic", "Runtime/component integration", "Angular/provider failure reproduction"):
            self.assertIn(heading, guide)

    def test_ci_routes_a_real_prepared_selection_through_the_same_entrypoint(self) -> None:
        workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
        expected = [
            'python3 tools/test.py check --suite selection.metadata-working-set --inventory "$RUNNER_TEMP/lsf-workspace-tests.jsonl" --context ci',
            'python3 tools/test.py prepare --suite selection.metadata-working-set --inventory "$RUNNER_TEMP/lsf-workspace-tests.jsonl" --context ci',
            'python3 tools/test.py run --suite selection.metadata-working-set --inventory "$RUNNER_TEMP/lsf-workspace-tests.jsonl" --context ci',
        ]
        for command in expected:
            self.assertIn(command, workflow)
        self.assertIn("tools.tests.test_local_tests", workflow)
        data = registry.load()
        plan = local.plan_suite(ROOT, METADATA)
        self.assertEqual(plan["cases"], data["selections"]["metadata-working-set"]["names"])
        self.assertEqual(plan["runner"], data["selections"]["metadata-working-set"]["runner"])

    def test_contributor_guide_links_the_local_entrypoint(self) -> None:
        contributing = (ROOT / "CONTRIBUTING.md").read_text(encoding="utf-8")
        self.assertIn("docs/development/local-tests.md", contributing)


if __name__ == "__main__":
    unittest.main()
