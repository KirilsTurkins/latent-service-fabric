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
                patch.object(local, "owned_run", side_effect=AssertionError("planning executed an owned process")), \
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
        self.assertIn("fixture/service", plan["blocker"])

        browser = local.plan_suite(ROOT, "selection.browser-boundary")
        self.assertFalse(browser["runSupported"])
        self.assertIn("execution-only", browser["blocker"])

        data = registry.load()
        angular = local.plan_suite(ROOT, local.ANGULAR_PROCESS)
        self.assertTrue(angular["runSupported"])
        self.assertEqual(angular["runner"], "run_angular_renderer_tests")
        self.assertEqual(angular["ownerSuite"], data["processContracts"]["angular-renderer"]["suiteIds"])
        self.assertEqual(angular["cases"], local._angular_cases(data))
        self.assertEqual(angular["prerequisites"], data["processContracts"]["angular-renderer"]["prerequisites"])

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
            with patch.object(local, "_validate_generic_inventory"), \
                    patch.object(local, "validate_prepared") as validate, \
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
                    patch.object(local, "_validate_generic_inventory"), \
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
        plan = local.plan_suite(ROOT, CORE, value["reproduction"]["cases"][0])
        value["reproduction"].update(recipe=plan["recipe"], recipeIdentity=plan["recipeIdentity"],
                                     requiredCaseCount=1,
                                     caseSetDigest=local.case_digest(plan["cases"]))
        value["requiredCaseCount"] = 1
        value["fixtures"]["test-executable"] = "sha256:" + "2" * 64
        value["reproduction"]["fixtures"]["test-executable"] = "sha256:" + "2" * 64
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
            report = Path(directory) / "failure.json"
            inventory = Path(directory) / "cargo.jsonl"
            inventory.write_bytes(b"prepared")
            executable = Path(directory) / "test"
            executable.write_bytes(b"executable")
            record = self.record()
            report.write_text(json.dumps(record))
            prepared = SimpleNamespace(executable=executable)
            with patch.object(local, "_source", return_value=record["source"]), \
                    patch.object(local, "validate_prepared"), \
                    patch.object(local, "_generic_prepared", return_value=(None, None, prepared, {}, set(), set())), \
                    patch.object(local, "execute", side_effect=AssertionError("mismatched fixture executed")):
                with self.assertRaisesRegex(local.LocalTestError, "do not match"):
                    local.reproduce(ROOT, report, inventory, False)

    def test_changed_checkout_requires_explicit_label_even_with_same_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            report = Path(directory) / "failure.json"
            inventory = Path(directory) / "cargo.jsonl"
            executable = Path(directory) / "test"
            inventory.write_bytes(b"prepared")
            executable.write_bytes(b"executable")
            record = self.record()
            fixtures = {"test-manifest": local.file_digest(inventory, 1024),
                        "test-executable": local.file_digest(executable, 1024)}
            record["fixtures"] = record["reproduction"]["fixtures"] = fixtures
            report.write_text(json.dumps(record))
            prepared = SimpleNamespace(executable=executable)
            changed = {"revision": "b" * 40, "dirty": False, "observed": True}
            with patch.object(local, "validate_prepared") as validate, \
                    patch.object(local, "_generic_prepared", return_value=(None, None, prepared, {}, set(), set())), \
                    patch.object(local, "_source", return_value=changed), \
                    patch.object(local, "execute", return_value=(101, {"outcome": "failed"})) as execute:
                with self.assertRaisesRegex(local.LocalTestError, "not an exact reproduction"):
                    local.reproduce(ROOT, report, inventory, False)
                validate.assert_not_called()
                execute.assert_not_called()
                code, result = local.reproduce(ROOT, report, inventory, True)
            self.assertEqual(code, 101)
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



class CompletionRegressionTests(unittest.TestCase):
    def test_local_and_ci_plans_have_identical_commands_cases_and_fixtures(self):
        data = registry.load()
        keys = [CORE, "selection.echo-runtime", METADATA, local.ANGULAR_PROCESS]
        with patch.object(local.artifacts, "run_owned", side_effect=AssertionError("process in planning")), \
                patch.object(local, "owned_run", side_effect=AssertionError("process in planning")), \
                patch.object(local, "run_bounded", side_effect=AssertionError("build in planning")):
            for key in keys:
                left = local.plan_suite(ROOT, key, context="local")
                right = local.plan_suite(ROOT, key, context="ci")
                left.pop("context")
                right.pop("context")
                self.assertEqual(left, right)
                self.assertEqual(left["recipeDefinition"], data["recipes"][left["recipe"]])

    def test_runtime_case_selects_only_its_required_fixture_builders(self):
        ordinary = local.plan_suite(ROOT, ECHO,
            "invokes_echo_through_the_execution_backend_and_enforces_the_phase_zero_boundary")
        oversized = local.plan_suite(ROOT, ECHO,
            "oversized_canonical_abi_log_payload_is_rejected_by_hostcall_fuel")
        self.assertEqual(list(ordinary["preparation"]["fixtureRecipes"]), ["echo-capsule"])
        self.assertEqual(list(oversized["preparation"]["fixtureRecipes"]), ["echo-capsule", "oversized-log"])
        whole = local.plan_suite(ROOT, "selection.echo-runtime")
        self.assertEqual(whole["requiredCaseCount"], 4)
        self.assertEqual(set(local._fixture_environment(ROOT, whole)), {
            "LSF_ECHO_COMPONENT", "LSF_ECHO_CAPSULE", "LSF_OVERSIZED_LOG_COMPONENT"})

    def test_exact_physical_case_keeps_its_observation_owner(self):
        case = registry.load()["selections"]["metadata-working-set"]["names"][0]
        plan = local.plan_suite(ROOT, "latent-control-store.lib.latent-control-store", case)
        self.assertEqual(plan["selection"], "metadata-working-set")
        self.assertEqual(plan["classification"], "explicit qualification")
        self.assertEqual(plan["runner"], "ci_rust_artifacts")

    def test_raw_provider_case_cannot_bypass_service_owner(self):
        selected = registry.load()["selections"]["s3-blobs"]
        plan = local.plan_suite(ROOT, selected["suite"], selected["names"][0])
        self.assertFalse(plan["runSupported"])

    def test_unsupported_owner_is_never_ready_even_with_inventory(self):
        plan = local.plan_suite(ROOT, CUSTOM)
        with patch.object(local, "validate_prepared"), patch.object(local.shutil, "which", return_value="tool"):
            result = local.prerequisite_check(ROOT, plan, Path("unused"))
        self.assertEqual(result["state"], "needs-preparation")
        self.assertIn(plan["blocker"], result["problems"])

    def test_wasm_header_accepts_real_magic_and_rejects_literal_escape(self):
        with tempfile.TemporaryDirectory() as directory:
            wasm = Path(directory) / "application.wasm"
            for content, valid in ((b"\0asm\x0d\0\x01\0", True), (b"\\0asm000", False),
                                   (b"\0asm", False), (b"not wasm", False)):
                wasm.write_bytes(content)
                self.assertEqual(local._wasm_prepared(wasm), valid)
            link = Path(directory) / "link.wasm"
            link.symlink_to(wasm)
            self.assertFalse(local._wasm_prepared(link))

    def test_preparation_failure_keeps_exit_and_does_not_publish_inventory(self):
        with tempfile.TemporaryDirectory() as directory:
            inventory = Path(directory) / "test.jsonl"
            plan = local.plan_suite(ROOT, CORE, inventory=inventory)
            failed = SimpleNamespace(returncode=101, stdout=b"{}", stderr=b"token=private")
            with patch.object(local.shutil, "which", return_value="cargo"), \
                    patch.object(local, "run_bounded", return_value=failed), redirect_stderr(io.StringIO()):
                with self.assertRaises(local.LocalTestError) as error:
                    local.prepare(ROOT, plan, inventory)
            self.assertEqual(error.exception.code, 101)
            self.assertEqual(error.exception.state, "failed")
            self.assertFalse(inventory.exists())

    def test_missing_fixture_tool_is_reported_before_any_cargo_build(self):
        with tempfile.TemporaryDirectory() as directory:
            plan = local.plan_suite(ROOT, ECHO,
                "invokes_echo_through_the_execution_backend_and_enforces_the_phase_zero_boundary")
            with patch.object(local.shutil, "which", side_effect=lambda tool: None if tool == "wasm-tools" else tool), \
                    patch.object(local, "_fixture_presence", return_value=False), \
                    patch.object(local, "run_bounded", side_effect=AssertionError("partial preparation")):
                with self.assertRaisesRegex(local.LocalTestError, "wasm-tools"):
                    local.prepare(ROOT, plan, Path(directory) / "test.jsonl")

    def test_valid_reusable_fixture_does_not_require_its_build_tools(self):
        with tempfile.TemporaryDirectory() as directory:
            inventory = Path(directory) / "test.jsonl"
            inventory.touch()
            plan = local.plan_suite(ROOT, ECHO,
                "invokes_echo_through_the_execution_backend_and_enforces_the_phase_zero_boundary")
            with patch.object(local.shutil, "which", side_effect=lambda tool: None if tool == "wasm-tools" else tool), \
                    patch.object(local, "_fixture_presence", return_value=True), \
                    patch.object(local, "_validate_fixture_recipe") as fixture_validation, \
                    patch.object(local, "_prepare_inventory", return_value=True) as prepared_inventory, \
                    patch.object(local, "validate_prepared") as prepared_validation, \
                    patch.object(local, "run_bounded", side_effect=AssertionError("unexpected preparation")):
                result = local.prepare(ROOT, plan, inventory)
            self.assertTrue(result["reused"])
            self.assertTrue(result["fixtureRecipes"])
            self.assertEqual(fixture_validation.call_count, len(result["fixtureRecipes"]))
            prepared_inventory.assert_called_once()
            prepared_validation.assert_called_once_with(ROOT, plan, inventory)

    def test_large_case_intent_is_bounded_but_never_truncated(self):
        cases = ["case_" + str(i) for i in range(300)]
        run = local.TestRun("synthetic", {"timeoutSeconds": 5}, synthetic=True)
        try:
            run.declare_cases(cases)
            self.assertNotIn("cases", run.reproduction)
            self.assertEqual(run.reproduction["requiredCaseCount"], 300)
            self.assertEqual(run.reproduction["caseSelection"], "registered")
            self.assertEqual(run.reproduction["caseSetDigest"], local.case_digest(cases))
        finally:
            run.temporary.cleanup()

    def test_duplicate_or_partial_case_completion_cannot_pass(self):
        with tempfile.TemporaryDirectory() as directory, redirect_stdout(io.StringIO()):
            run = local.TestRun("synthetic", {"timeoutSeconds": 5},
                                diagnostic_root=Path(directory), synthetic=True)
            with self.assertRaisesRegex(local.ProcessFailure, "required-case-completion-mismatch"):
                with run:
                    run.declare_cases(["first", "second"])
                    run.complete_cases(["first"])
            self.assertEqual(run.record["completedCaseCount"], 1)
            self.assertEqual(run.record["outcome"], "failed")

    def test_strict_failure_record_rejects_malformed_nested_values_and_options(self):
        import copy
        base = FailureRecordTests().record()
        changes = [
            ("cases", [{}]), ("cases", ["duplicate", "duplicate"]), ("requiredCaseCount", True),
            ("recipeIdentity", "sha256:not-a-digest"), ("caseSelection", "registered"),
            ("source", {"revision": "a" * 40, "observed": True, "dirty": "false"}),
            ("fixtures", {"test-manifest": "not-a-digest"}), ("mode", []),
            ("fault", "after-discovery"), ("fixtureOnly", False), ("preflight", True),
            ("command", ["sh", "-c", "exit 0"]), ("environment", {"TOKEN": "do-not-replay"}),
        ]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "failure.json"
            for key, value in changes:
                record = copy.deepcopy(base)
                record["reproduction"][key] = value
                path.write_text(json.dumps(record))
                with self.subTest(key=key), self.assertRaises(local.LocalTestError):
                    local.read_failure(path)
            path.write_text(json.dumps(base).replace('"elapsedMs": 1.0', '"elapsedMs": NaN'))
            with self.assertRaises(local.LocalTestError):
                local.read_failure(path)

    def test_recipe_tamper_is_rejected_before_source_or_executable_query(self):
        record = FailureRecordTests().record()
        record["reproduction"]["recipeIdentity"] = "sha256:" + "0" * 64
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "failure.json"
            path.write_text(json.dumps(record))
            with patch.object(local, "_source", side_effect=AssertionError("source probe before recipe rejection")), \
                    patch.object(local, "validate_prepared", side_effect=AssertionError("executed untrusted fixture")):
                with self.assertRaisesRegex(local.LocalTestError, "registered contract"):
                    local.reproduce(ROOT, path, Path(directory) / "test.jsonl", True)

    def test_diagnostic_summary_must_be_unique(self):
        summary = json.dumps({"suite": "angular-renderer", "outcome": "passed"}).encode()
        self.assertIsNotNone(local._test_run_summary(summary))
        self.assertIsNone(local._test_run_summary(summary + b"\n" + summary))
        self.assertIsNone(local._test_run_summary(b"test result: ok. 0 passed; 0 failed;"))


    def test_recipe_features_profile_and_target_root_are_checked_without_execution(self):
        import os
        with tempfile.TemporaryDirectory() as directory:
            repo, inventory, case = NativeEntrypointTests().fixture(directory)
            plan = local.plan_suite(repo, CORE, case)
            with patch.dict(os.environ, {"CARGO_TARGET_DIR": str(repo / "target")}), \
                    patch.object(local.artifacts, "run_owned", side_effect=AssertionError("unowned discovery")), \
                    patch.object(local, "owned_run", side_effect=AssertionError("unowned discovery")):
                local.validate_prepared(repo, plan, inventory)
                records = [json.loads(line) for line in inventory.read_text().splitlines()]
                for field, bad in (("features", []), ("profile", {"test": True, "opt_level": "3"})):
                    changed = json.loads(json.dumps(records))
                    changed[0][field] = bad
                    inventory.write_text("".join(json.dumps(record) + "\n" for record in changed))
                    with self.subTest(field=field), self.assertRaises(local.LocalTestError):
                        local.validate_prepared(repo, plan, inventory)

    def test_declared_fixture_digest_does_not_authorize_different_echo_bytes(self):
        import os
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "target"
            folder = target / "capsules/echo"
            folder.mkdir(parents=True)
            component = folder / "echo-capsule.wasm"
            component.write_bytes(b"\0asm\x0d\0\x01\0")
            digest = local.file_digest(component, 1024)
            (folder / "capsule.json").write_text(json.dumps({"component": {"digest": digest}}))
            (folder / "build.json").write_text(json.dumps({"contentDigest": digest}))
            recipe = registry.load()["fixtureRecipes"]["echo-capsule"]
            with patch.dict(os.environ, {"CARGO_TARGET_DIR": str(target)}):
                identities = local._validate_fixture_recipe(ROOT, "echo-capsule", recipe)
                self.assertEqual(identities["echo-component"], digest)
                component.write_bytes(b"\0asm\x0d\0\x01\0changed")
                with self.assertRaisesRegex(local.LocalTestError, "disagree"):
                    local._validate_fixture_recipe(ROOT, "echo-capsule", recipe)

    def test_ci_uses_registered_core_and_complete_echo_entrypoints(self):
        workflow = (ROOT / ".github/workflows/ci.yml").read_text()
        contracts = (ROOT / "tools/validate_contracts.sh").read_text()
        for verb in ("prepare", "check", "run"):
            self.assertIn(f"tools/test.py {verb} --suite {CORE} --case digest::tests::canonical_sha256_text_round_trips_in_each_identity_domain", workflow)
            self.assertIn(f"tools/test.py {verb} --suite selection.echo-runtime", contracts)
        self.assertNotIn("cargo test -p latent-wasmtime --test echo_backend --locked -- --ignored", contracts)
        self.assertEqual(local.plan_suite(ROOT, "selection.echo-runtime")["requiredCaseCount"], 4)

    def test_angular_result_cannot_pass_without_a_complete_owned_record(self):
        plan = local.plan_suite(ROOT, local.ANGULAR_PROCESS)
        result = SimpleNamespace(returncode=0, output=b"test result: ok. 0 passed; 0 failed;", cleaned=True)
        with tempfile.TemporaryDirectory() as directory:
            run = SimpleNamespace(root=Path(directory), command=lambda *args, **kwargs: result,
                                  execution_environment=lambda env: env, mark=lambda stage: None)
            with self.assertRaisesRegex(local.ProcessFailure, "angular-owner-result-missing"):
                local._execute_angular_process(run, ROOT, plan, Path("not-read.jsonl"), None)


class NativeEntrypointTests(unittest.TestCase):
    """Real process ownership with synthetic Cargo metadata; not Rust qualification."""

    @classmethod
    def setUpClass(cls):
        import os
        import sys
        if sys.platform != "linux" or not Path(f"/proc/self/task/{os.getpid()}/children").is_file():
            if os.environ.get("LSF_REQUIRE_NATIVE_PROCESS_TESTS") == "1":
                raise AssertionError("required native entrypoint tests unavailable")
            raise unittest.SkipTest("native Linux child accounting unavailable; not qualification")

    def fixture(self, directory):
        import sys
        repo = Path(directory)
        data = registry.load()
        row = next(row for row in data["suites"] if row["id"] == CORE)
        registry_path = repo / "tools/ci/suites.json"
        registry_path.parent.mkdir(parents=True)
        registry_path.write_text(json.dumps(data))
        package = repo / Path(row["manifest"]).parent
        (package / row["source"]).parent.mkdir(parents=True)
        (package / row["source"]).write_text("// synthetic harness\n")
        (repo / row["manifest"]).write_text("[package]\nname='latent-core'\nversion='0.0.0'\n[features]\ntest-support=[]\n")
        binary = repo / "target/debug/deps/synthetic"
        binary.parent.mkdir(parents=True)
        code = (f"#!{sys.executable} -S\nimport os,sys,subprocess\n"
                f"names={row['expectedCases']!r}\n"
                'if "--list" in sys.argv:\n'
                ' selected=[] if "--ignored" in sys.argv else names\n'
                ' for name in selected: print(name+": test")\n'
                ' print(str(len(selected))+" tests, 0 benchmarks")\n'
                'else:\n'
                ' if os.environ.get("SYNTHETIC_BUILD"):\n'
                '  subprocess.run(["cargo","build"],check=False)\n'
                ' if os.environ.get("SYNTHETIC_EXIT"): sys.exit(int(os.environ["SYNTHETIC_EXIT"]))\n'
                ' chosen=[sys.argv[1]] if "--exact" in sys.argv else names\n'
                ' if os.environ.get("SYNTHETIC_EMPTY"): chosen=[]\n'
                ' for name in chosen: print("test "+name+" ... ok")\n'
                ' print("test result: ok. "+str(len(chosen))+" passed; 0 failed; 0 ignored; 0 measured; 0 filtered out; finished in 0.00s")\n')
        binary.write_text(code)
        binary.chmod(0o700)
        inventory = repo / "target/test.jsonl"
        inventory.write_text(json.dumps({
            "reason": "compiler-artifact", "manifest_path": str(repo / row["manifest"]),
            "target": {"kind": [row["kind"]], "name": row["target"], "src_path": str(package / row["source"])},
            "profile": {"test": True, "opt_level": "0"}, "features": ["test-support"], "executable": str(binary)}) + "\n" +
            '{"reason":"build-finished","success":true}\n')
        return repo, inventory, row["expectedCases"][0]

    def run_synthetic(self, directory, variables):
        import os
        repo, inventory, case = self.fixture(directory)
        def source(run):
            run.source = {"revision": "a" * 40, "dirty": False, "observed": True}
        with patch.dict(os.environ, {"CARGO_TARGET_DIR": str(repo / "target"), **variables}), \
                patch.object(local.TestRun, "source_identity", source), \
                patch.object(local.artifacts, "cargo_environment", side_effect=lambda repo, art, env, **kw: dict(env)):
            return invoke(["run", "--suite", CORE, "--case", case, "--inventory", str(inventory)], repo)

    def test_actual_owned_prepared_entrypoint_passes_exactly_one_case(self):
        with tempfile.TemporaryDirectory() as directory:
            code, record = self.run_synthetic(directory, {})
        self.assertEqual(code, 0)
        self.assertEqual(record["requiredCaseCount"], 1)
        self.assertEqual(record["completedCaseCount"], 1)
        self.assertTrue(record["child"]["cleanupAcknowledged"])

    def test_actual_nonzero_and_empty_execution_are_not_success_or_retried(self):
        for variables, expected in (({"SYNTHETIC_EXIT": "101"}, 101), ({"SYNTHETIC_EMPTY": "1"}, 1)):
            with self.subTest(variables=variables), tempfile.TemporaryDirectory() as directory:
                code, record = self.run_synthetic(directory, variables)
            self.assertEqual(code, expected)
            self.assertEqual(record["outcome"], "failed")
            self.assertEqual(record["completedCaseCount"], 0)

    def test_actual_swallowed_build_tool_failure_still_fails_the_run(self):
        with tempfile.TemporaryDirectory() as directory:
            code, record = self.run_synthetic(directory, {"SYNTHETIC_BUILD": "1"})
        self.assertNotEqual(code, 0)
        self.assertEqual(record["reason"], "execution-invoked-build-or-install-tool")
        self.assertEqual(record["outcome"], "failed")



class ReviewRegressionTests(unittest.TestCase):
    def test_contract_handoff_rebuilds_changed_body_on_second_invocation(self):
        """Run the actual shell cleanup/path twice, with a compiler-free build double."""
        import os
        import subprocess

        script = (ROOT / "tools/validate_contracts.sh").read_text()
        # Isolate the script-owned handoff from unrelated WIT/provider builders.
        # Neither its cleanup nor its inventory path is reimplemented here.
        prelude = script.split("python3 tools/validate_repository.py", 1)[0]
        assignment = next(line for line in script.splitlines() if line.startswith("ECHO_INVENTORY="))
        plan = local.plan_suite(ROOT, "selection.echo-runtime")
        for target in (None, "relative-target", "external"):
            with self.subTest(target=target), tempfile.TemporaryDirectory() as directory:
                base = Path(directory)
                repo = base / "repo"
                (repo / "tools").mkdir(parents=True)
                shell = repo / "tools/validate_contracts.sh"
                shell.write_text(prelude + assignment + '\nprintf "%s" "$ECHO_INVENTORY"\n')
                source = repo / "crates/latent-wasmtime/tests/echo_backend.rs"
                source.parent.mkdir(parents=True)
                source.write_text("#[test] fn unchanged_name() { assert!(true); }\n")
                environment = dict(os.environ)
                environment.pop("CARGO_TARGET_DIR", None)
                if target is not None:
                    environment["CARGO_TARGET_DIR"] = str(base / target) if target == "external" else target
                builds = []
                binary = base / "prepared-echo"

                def build(command, cwd, env, timeout, maximum):
                    self.assertEqual(command, plan["preparation"]["buildCommand"])
                    body = source.read_text()
                    builds.append(body)
                    failed = "assert!(false)" in body
                    binary.write_text("#!/bin/sh\nprintf '%s\\n' " +
                                      ("NEW_TEST_BODY_FAILED\nexit 101\n" if failed else
                                       "OLD_TEST_BODY_PASSED\nexit 0\n"))
                    binary.chmod(0o700)
                    return SimpleNamespace(returncode=0, stderr=b"",
                                           stdout=b'{"reason":"build-finished","success":true}\n')

                with patch.dict(os.environ, environment, clear=True), \
                        patch.object(local.shutil, "which", return_value="available"), \
                        patch.object(local, "run_bounded", side_effect=build), \
                        patch.object(local, "_fixtures_for", return_value={}), \
                        patch.object(local, "_validate_generic_inventory"), \
                        patch.object(local, "validate_prepared"):
                    observed = []
                    for body in ("true", "false"):
                        source.write_text(f"#[test] fn unchanged_name() {{ assert!({body}); }}\n")
                        path = subprocess.check_output(["bash", str(shell)], env=environment, timeout=10)
                        inventory = Path(path.decode())
                        prepared = local.prepare(repo, plan, inventory)
                        result = subprocess.run([str(binary)], capture_output=True, timeout=10)
                        observed.append((prepared["reused"], result.returncode, result.stdout))
                self.assertEqual(observed, [(False, 0, b"OLD_TEST_BODY_PASSED\n"),
                                            (False, 101, b"NEW_TEST_BODY_FAILED\n")])
                self.assertEqual(len(builds), 2)
                self.assertIn("assert!(false)", builds[1])


class AngularReviewRegressionTests(unittest.TestCase):
    """Real TestRun publication/cleanup around a controlled child-owner handoff."""
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.repo = Path(self.temp.name)
        self.inventory = self.repo / "inventory.jsonl"
        self.inventory.write_text("synthetic prepared inventory\n")
        self.plan = local.plan_suite(ROOT, local.ANGULAR_PROCESS)
        self.source = {"revision": "a" * 40, "dirty": False, "observed": True}
        self.fixtures = {"test-manifest": local.file_digest(self.inventory, local.MAX_REPORT),
                         "component": "sha256:" + "1" * 64}
        self.private_diagnostics = None

    def child_record(self, *, early=False, passed=False):
        from tools.owned_test_process import Result
        from tools import check_tool_versions as versions
        from tools.tests.test_owned_test_process import policy

        owner = local.TestRun("angular-renderer", policy(), repo=self.repo,
                              reproduction={"suite": "angular-renderer", "preflight": False, "fault": "none"},
                              synthetic=True, secrets=("dummy-redact",),
                              diagnostic_root=self.repo / "child-staging")
        caught = None
        with redirect_stdout(io.StringIO()):
            try:
                with owner:
                    owner.source = dict(self.source)
                    if early:
                        owner.policy["prerequisites"]["versionScopes"] = ["python"]
                        with patch.object(versions.platform, "python_version", return_value="0.0.0"):
                            owner.prerequisites(before_build=True)
                        self.fail("the authoritative Python version check must fail")
                    owner.fixture_ids.update(self.fixtures)
                    owner.declare_cases(self.plan["cases"])
                    owner.reproduction.update(recipe=self.plan["recipe"], mode="process",
                                              recipeIdentity=self.plan["recipeIdentity"])
                    owner.mark("execution")
                    owner.complete_cases(self.plan["cases"] if passed else self.plan["cases"][:1])
                    result = Result(0 if passed else 101,
                                    b"DISTINCTIVE_ANGULAR_ASSERTION: expected 2, got 1\n"
                                    b"token=dummy-redact\n", cleaned=True)
                    owner.observe(result)
                    if not passed:
                        raise local.ProcessFailure("assertion-failure", "child-exit-failure", result)
            except local.ProcessFailure as error:
                caught = error
        self.assertEqual(caught is None, passed)
        self.assertFalse(owner.root.exists())
        return json.loads(owner.record_path.read_text())

    def run_child_record(self, record, *, status=1):
        import os
        from tools import test_run
        from tools.owned_test_process import Result

        def child(command, **kwargs):
            self.assertEqual(command[1], "tools/run_angular_renderer_tests.py")
            folder = Path(command[command.index("--diagnostic-root") + 1])
            folder.mkdir()
            self.private_diagnostics = folder
            name = "angular-renderer-" + record["runId"] + ".json"
            (folder / name).write_text(json.dumps(record))
            summary = {key: record[key] for key in ("suite", "runId", "outcome", "reason")}
            summary["diagnostic"] = name
            return Result(status, json.dumps(summary).encode(), cleaned=True)

        def source(owner):
            owner.source = dict(self.source)

        with patch.dict(os.environ, {"CARGO_TARGET_DIR": str(self.repo / "target")}), \
                patch.object(local, "validate_prepared"), \
                patch.object(local, "_fixture_identities", return_value={"component": self.fixtures["component"]}), \
                patch.object(local, "_validate_angular_inventory", return_value={}), \
                patch.object(local.TestRun, "source_identity", source), \
                patch.object(test_run, "run_owned", side_effect=child), \
                redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            code, result = local.execute(self.repo, self.plan, self.inventory)
        self.assertFalse(self.private_diagnostics.exists())
        permanent = self.repo / "target/test-diagnostics" / (result["suite"] + "-" + result["runId"] + ".json")
        self.assertEqual(json.loads(permanent.read_text()), result)
        return code, result

    def test_partial_angular_failure_survives_private_diagnostic_cleanup(self):
        child = self.child_record()
        code, record = self.run_child_record(child)
        self.assertEqual(code, 101)
        self.assertEqual(record["outcome"], "failed")
        self.assertEqual(record["reason"], "child-exit-failure")
        self.assertIn("DISTINCTIVE_ANGULAR_ASSERTION", record["logTail"])
        self.assertNotIn("dummy-redact", json.dumps(record))
        self.assertEqual(record["requiredCaseCount"], len(self.plan["cases"]))
        self.assertEqual(record["completedCaseCount"], 1)
        self.assertEqual(record["completedCaseDigest"], local.case_digest(self.plan["cases"][:1]))
        self.assertEqual(local.read_failure(next((self.repo / "target/test-diagnostics").glob("*.json"))), record)

    def test_early_python_version_failure_remains_not_run(self):
        child = self.child_record(early=True)
        self.assertEqual(child["fixtures"], {})
        self.assertEqual(child["requiredCaseCount"], 0)
        code, record = self.run_child_record(child)
        self.assertEqual(code, 3)
        self.assertEqual(record["outcome"], "not-run")
        self.assertEqual(record["category"], "unavailable-environment")
        self.assertEqual(record["reason"], "authoritative-tool-version-check-failed")
        self.assertEqual(record["completedCaseCount"], 0)

    def test_early_cancellation_and_timeout_keep_their_categories(self):
        base = self.child_record(early=True)
        for category, reason, expected in (("cancelled", "runner-interrupted", 130),
                                            ("infrastructure-timeout", "total-run-watchdog", 124)):
            child = json.loads(json.dumps(base))
            child.update(outcome="failed", category=category, reason=reason)
            with self.subTest(category=category):
                code, record = self.run_child_record(child)
                self.assertEqual(code, expected)
                self.assertEqual(record["category"], category)
                self.assertEqual(record["reason"], reason)
                self.assertEqual(record["completedCaseCount"], 0)

    def test_child_failure_details_are_bounded_and_redacted_again(self):
        from tools.test_run import MAX_TAIL
        base = self.child_record()
        base["logTail"] = "token=dummy-input\nDISTINCTIVE_ANGULAR_ASSERTION\n"
        code, record = self.run_child_record(base)
        self.assertEqual(code, 101)
        self.assertNotIn("dummy-input", json.dumps(record))
        self.assertIn("DISTINCTIVE_ANGULAR_ASSERTION", record["logTail"])
        self.assertLessEqual(len(record["logTail"]), MAX_TAIL)
        for field, value in (("logTail", "x" * (MAX_TAIL + 1)), ("logTail", []),
                             ("category", []), ("child", {})):
            child = json.loads(json.dumps(base))
            child[field] = value
            with self.subTest(field=field, kind=type(value).__name__):
                code, record = self.run_child_record(child)
                self.assertNotEqual(code, 0)
                self.assertEqual(record["category"], "invalid-fixture")
                self.assertEqual(record["completedCaseCount"], 0)

    def test_early_failure_does_not_accept_conflicting_available_identities(self):
        base = self.child_record(early=True)
        for field in ("source", "fixtures", "recipe", "completed"):
            child = json.loads(json.dumps(base))
            if field == "source":
                child["source"]["revision"] = "b" * 40
                child["reproduction"]["source"] = child["source"]
            elif field == "fixtures":
                child["fixtures"] = {"component": "sha256:" + "9" * 64}
                child["reproduction"]["fixtures"] = child["fixtures"]
            elif field == "recipe":
                child["reproduction"]["recipeIdentity"] = "sha256:" + "9" * 64
            else:
                child["completedCaseCount"] = 1
                child["completedCaseDigest"] = local.case_digest(self.plan["cases"][:1])
            with self.subTest(field=field):
                code, record = self.run_child_record(child)
                self.assertNotEqual(code, 0)
                self.assertEqual(record["category"], "invalid-fixture")
                self.assertEqual(record["completedCaseCount"], 0)

    def test_partial_completion_requires_the_ordered_case_digest(self):
        child = self.child_record()
        child["completedCaseDigest"] = local.case_digest(self.plan["cases"][1:2])
        code, record = self.run_child_record(child)
        self.assertNotEqual(code, 0)
        self.assertEqual(record["completedCaseCount"], 0)

    def test_success_still_requires_complete_identities_and_cleanup(self):
        base = self.child_record(passed=True)
        code, record = self.run_child_record(base, status=0)
        self.assertEqual(code, 0)
        self.assertEqual(record["completedCaseCount"], len(self.plan["cases"]))
        for field in ("fixtures", "recipeIdentity", "cleanup", "count", "exit"):
            child = json.loads(json.dumps(base))
            if field == "fixtures":
                child["fixtures"] = {}
                child["reproduction"]["fixtures"] = {}
            elif field == "recipeIdentity":
                child["reproduction"].pop(field)
            elif field == "cleanup":
                child["child"]["cleanupAcknowledged"] = False
            elif field == "exit":
                child["child"]["exit"] = 101
            else:
                child["completedCaseCount"] -= 1
            with self.subTest(field=field):
                code, record = self.run_child_record(child, status=0)
                self.assertNotEqual(code, 0)
                self.assertEqual(record["outcome"], "failed")


if __name__ == "__main__":
    unittest.main()
