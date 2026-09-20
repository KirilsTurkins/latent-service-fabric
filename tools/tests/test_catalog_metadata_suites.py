"""Metadata suite registry, discovery, observation and CI coverage guards; no builds."""

from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
from dataclasses import replace
import copy
import io
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import textwrap
import unittest
from unittest.mock import patch

from tools import ci_rust_artifacts as runner

FAST = runner.SUITES["catalog-metadata-correctness"]
PHYSICAL = runner.SUITES["catalog-metadata-working-set"]
ROOT = Path(__file__).resolve().parents[2]


def listing(suite: runner.Suite) -> bytes:
    return ("\n".join(f"{name}: test" for name in sorted(suite.names))
            + f"\n\n{len(suite.names)} tests, 0 benchmarks\n").encode()


def result(suite: runner.Suite) -> bytes:
    return f"test result: ok. {len(suite.names)} passed; 0 failed; 0 ignored;\n".encode()


def measured(suite: runner.Suite) -> bytes:
    if suite is FAST:
        prefix = "LSF_METADATA_CORRECTNESS "
        value = {"schemaVersion": "latent.catalog.metadata-correctness.v1",
                 "releases": 4, "documentation_bytes_per_release": 8192}
    else:
        prefix = "LSF_METADATA_PHYSICAL "
        value = {"schemaVersion": "latent.catalog.metadata-working-set.v1",
                 "releases": 32, "documentation_bytes_per_release": 3145728,
                 "max_growth_kib": 65536,
                 "phases": [{"mode": mode} for mode in ("publish", "apply", "reopen")]}
    return (prefix + json.dumps(value) + "\n").encode()


class RegistryTests(unittest.TestCase):
    def test_fast_and_physical_are_different_boundaries_with_one_recipe(self) -> None:
        self.assertFalse(FAST.ignored)
        self.assertTrue(PHYSICAL.ignored)
        self.assertTrue(PHYSICAL.exact)
        self.assertEqual(len(FAST.names), 2)
        self.assertEqual(len(PHYSICAL.names), 1)
        self.assertEqual(FAST.recipe, PHYSICAL.recipe)
        self.assertEqual(FAST.expected_features, ("catalog-observation", "default"))
        self.assertEqual(PHYSICAL.resource_class, "exclusive-process")
        self.assertGreater(PHYSICAL.timeout_seconds, 3 * 300)
        self.assertEqual(PHYSICAL.required_job, "catalog")
        self.assertEqual(PHYSICAL.prerequisites, ("linux-proc-vmhwm",))
        self.assertIn("retention-negative-control", FAST.assertions)
        self.assertNotIn("64-mib-physical-growth", FAST.assertions)

    def test_legacy_exact_case_selection_remains_registered(self) -> None:
        expected = {"browser-boundary": 2, "operator-fixture": 1, "publication-fixture": 1,
                    "resource-fixture": 1, "trust-currentness": 4}
        for name, count in expected.items():
            suite = runner.SUITES[name]
            self.assertEqual(len(suite.names), count)
            self.assertTrue(suite.ignored)
            self.assertFalse(suite.nocapture)
            self.assertEqual(suite.timeout_seconds, 300)
            self.assertIsNone(suite.expected_features)

    def test_inventory_rejects_empty_ambiguous_or_malformed_definitions(self) -> None:
        original = json.loads(runner.REGISTRY.read_text())
        mutations = [
            ("names", []), ("names", [PHYSICAL.filter, PHYSICAL.filter]),
            ("names", ["renamed"]), ("exact", 1), ("ignored", "yes"),
            ("timeout_seconds", 0), ("timeout_seconds", True),
            ("prerequisites", ["unregistered"]), ("source", "../outside"),
            ("manifest", "/outside/Cargo.toml"), ("expected_features", "all"),
        ]
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "suites.json"
            for field, value in mutations:
                document = copy.deepcopy(original)
                document["suites"]["catalog-metadata-working-set"][field] = value
                path.write_text(json.dumps(document))
                with self.subTest(field=field, value=value), self.assertRaises(runner.ArtifactError):
                    runner.read_suites(path)
            for raw in ('{"schemaVersion":"unknown","suites":{}}',
                        '{"schemaVersion":"x","schemaVersion":"y"}', '[]'):
                path.write_text(raw)
                with self.assertRaises(runner.ArtifactError):
                    runner.read_suites(path)


class ExecutionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.repo = Path(self.directory.name).resolve()
        self.manifest = self.repo / FAST.manifest
        self.manifest.parent.joinpath("src").mkdir(parents=True)
        self.manifest.write_text("[package]\n")
        self.source = self.manifest.parent / FAST.source
        self.source.write_text("")
        self.exe = self.repo / "target/debug/deps/current-libtest"
        self.exe.parent.mkdir(parents=True)
        self.exe.write_bytes(b"not a native executable; process boundaries are mocked")
        self.inventory = self.repo / "inventory.jsonl"
        self.message = {
            "reason": "compiler-artifact", "manifest_path": str(self.manifest),
            "target": {"kind": ["lib"], "name": FAST.target, "src_path": str(self.source)},
            "profile": {"test": True}, "executable": str(self.exe),
            "features": list(FAST.expected_features),
        }
        self.save()

    def save(self) -> None:
        self.inventory.write_text(json.dumps(self.message) + '\n{"reason":"build-finished","success":true}\n')

    def execute(self, suite: runner.Suite, outputs: list[tuple[int, bytes]], record: dict | None = None):
        with patch.object(runner, "prerequisites"), \
                patch.object(runner, "cargo_environment", return_value={}), \
                patch.object(runner, "run_owned", side_effect=outputs) as run, \
                redirect_stdout(io.StringIO()):
            runner.run_suite(self.repo, self.inventory, suite, {}, record)
        return run

    def test_fast_selection_checks_unexpected_ignores_before_execution(self) -> None:
        record = {}
        run = self.execute(FAST, [(0, listing(FAST)), (0, b"0 tests, 0 benchmarks\n"),
                                  (0, measured(FAST) + result(FAST))], record)
        self.assertEqual(run.call_count, 3)
        self.assertNotIn("--ignored", run.call_args.args[0])
        self.assertIn("--nocapture", run.call_args.args[0])
        self.assertEqual(run.call_args.kwargs["timeout"], FAST.timeout_seconds)
        self.assertEqual(record["passed_cases"], 2)
        self.assertGreaterEqual(record["execution_seconds"], 0)
        for ignored in (listing(FAST), listing(replace(FAST, names=frozenset([next(iter(FAST.names))])))):
            with self.assertRaises(runner.ArtifactError):
                self.execute(FAST, [(0, listing(FAST)), (0, ignored)])

    def test_physical_exact_run_has_room_for_all_three_children(self) -> None:
        run = self.execute(PHYSICAL, [(0, listing(PHYSICAL)),
                                      (0, result(PHYSICAL) * 3 + measured(PHYSICAL) + result(PHYSICAL))])
        self.assertEqual(run.call_count, 2)
        self.assertEqual(run.call_args.args[0], [str(self.exe), PHYSICAL.filter, "--ignored",
                                                "--exact", "--test-threads=1", "--nocapture"])
        self.assertEqual(run.call_args.kwargs["timeout"], 930)

    def test_zero_parent_cases_do_not_inherit_success_from_child_summaries(self) -> None:
        output = result(PHYSICAL) * 3 + measured(PHYSICAL) + b"test result: ok. 0 passed; 0 failed; 0 ignored;\n"
        with self.assertRaises(runner.ArtifactError):
            self.execute(PHYSICAL, [(0, listing(PHYSICAL)), (0, output)])

    def test_feature_recipe_mismatch_or_missing_features_is_rejected(self) -> None:
        for features in ([], ["default"], ["default", "catalog-observation", "extra"], None):
            self.message["features"] = features
            self.save()
            with self.subTest(features=features), self.assertRaises(runner.ArtifactError):
                runner.read_inventory(self.inventory, self.repo, PHYSICAL)

    def test_missing_or_renamed_suite_never_executes(self) -> None:
        for output in (b"0 tests, 0 benchmarks\n", listing(PHYSICAL).replace(b"bounded", b"renamed")):
            with self.assertRaises(runner.ArtifactError):
                self.execute(PHYSICAL, [(0, output)])

    def test_failure_and_timeout_do_not_create_passing_case_counts(self) -> None:
        record = {}
        with self.assertRaises(runner.ArtifactError):
            self.execute(PHYSICAL, [(0, listing(PHYSICAL)), (7, b"failed")], record)
        self.assertTrue(record["execution_started"])
        self.assertEqual(record["exit_code"], 7)
        self.assertNotIn("passed_cases", record)
        record = {}
        with self.assertRaises(runner.ArtifactError), patch.object(runner, "prerequisites"), \
                patch.object(runner, "cargo_environment", return_value={}), \
                patch.object(runner, "run_owned", side_effect=[(0, listing(PHYSICAL)),
                                                              runner.ArtifactError("test-timeout")]):
            runner.run_suite(self.repo, self.inventory, PHYSICAL, {}, record)
        self.assertIn("execution_seconds", record)
        self.assertNotIn("passed_cases", record)

    def test_parent_private_root_is_cleaned_after_failure_or_cancellation(self) -> None:
        for failure in (runner.ArtifactError("test-timeout"), KeyboardInterrupt()):
            roots = []
            def interrupted(_command, **kwargs):
                root = Path(kwargs["env"]["TMPDIR"])
                roots.append(root)
                (root / "partial-fixture").write_text("owned by this invocation")
                raise failure
            with patch.object(runner, "prerequisites"), \
                    patch.object(runner, "cargo_environment", return_value={}), \
                    patch.object(runner, "run_owned") as run:
                run.side_effect = lambda command, **kwargs: ((0, listing(PHYSICAL))
                    if "--list" in command else interrupted(command, **kwargs))
                with self.assertRaises(type(failure)):
                    runner.run_suite(self.repo, self.inventory, PHYSICAL, {})
            self.assertEqual(len(roots), 1)
            self.assertFalse(roots[0].exists())


class PrerequisiteTests(unittest.TestCase):
    def test_missing_denied_or_malformed_proc_data_never_becomes_zero(self) -> None:
        for value in (b"", b"VmRSS: 123 kB\n", b"VmHWM: 0 kB\n", b"VmHWM: 1 MB\n",
                      b"VmHWM: 2 kB\nVmHWM: 2 kB\n"):
            with self.subTest(value=value), patch.object(runner.sys, "platform", "linux"), \
                    patch.object(Path, "open", return_value=io.BytesIO(value)), \
                    self.assertRaises(runner.ArtifactError):
                runner.prerequisites(PHYSICAL, {})
        for error in (FileNotFoundError(), PermissionError()):
            with patch.object(runner.sys, "platform", "linux"), \
                    patch.object(Path, "open", side_effect=error), self.assertRaises(runner.ArtifactError):
                runner.prerequisites(PHYSICAL, {})

    def test_fast_has_no_proc_requirement_and_qualification_rejects_foreign_platform(self) -> None:
        with patch.object(runner.sys, "platform", "linux"), patch.object(Path, "open") as opened:
            runner.prerequisites(FAST, {})
        opened.assert_not_called()
        with patch.object(runner.sys, "platform", "darwin"), self.assertRaises(runner.ArtifactError):
            runner.prerequisites(PHYSICAL, {})

    def test_child_only_environment_cannot_substitute_for_full_parent(self) -> None:
        for key in ("LSF_DEPLOYMENT_MEMORY_MODE", "LSF_DEPLOYMENT_MEMORY_ROOT"):
            with patch.object(runner.sys, "platform", "linux"), self.assertRaises(runner.ArtifactError):
                runner.prerequisites(PHYSICAL, {key: "publish"})

    def test_positive_proc_record_is_accepted_without_a_build(self) -> None:
        with patch.object(runner.sys, "platform", "linux"), \
                patch.object(Path, "open", return_value=io.BytesIO(b"Name: test\nVmHWM: 123 kB\n")):
            runner.prerequisites(PHYSICAL, {})


class ObservationTests(unittest.TestCase):
    def test_correctness_never_emits_the_physical_schema(self) -> None:
        self.assertEqual(runner.observation(measured(FAST), FAST)["releases"], 4)
        with self.assertRaises(runner.ArtifactError):
            runner.observation(measured(FAST), PHYSICAL)
        with self.assertRaises(runner.ArtifactError):
            runner.observation(measured(PHYSICAL), FAST)

    def test_success_without_unique_complete_parent_observation_fails(self) -> None:
        for output in (b"", result(PHYSICAL), measured(PHYSICAL) * 2,
                       measured(PHYSICAL).replace(b'"reopen"', b'"apply"'),
                       measured(PHYSICAL).replace(b'"releases": 32', b'"releases": 4'),
                       measured(PHYSICAL).replace(b'"max_growth_kib": 65536', b'"max_growth_kib": 99999')):
            with self.subTest(output=output), self.assertRaises(runner.ArtifactError):
                runner.observation(output, PHYSICAL)
        self.assertEqual(len(runner.observation(measured(PHYSICAL), PHYSICAL)["phases"]), 3)

    def test_cli_preserves_failure_not_run_and_success_in_separate_records(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "execution.json"
            args = ["--suite", "catalog-metadata-correctness", "--inventory", "missing.jsonl",
                    "--source-commit", "a" * 40, "--record", str(path)]
            def passed(_repo, _inventory, _suite, _env, record):
                record.update(execution_started=True, passed_cases=2)
            def failed(_repo, _inventory, _suite, _env, record):
                record["execution_started"] = True
                raise runner.ArtifactError("test-timeout")
            for operation, expected_code, expected_outcome in (
                    (passed, 0, "passed"), (failed, 1, "failed"),
                    (runner.ArtifactError("missing-inputs"), 1, "not-run"),
                    (KeyboardInterrupt(), 1, "cancelled")):
                with patch.object(runner, "require_source"), \
                        patch.object(runner, "run_suite", side_effect=operation), \
                        redirect_stderr(io.StringIO()):
                    self.assertEqual(runner.main(args), expected_code)
                record = json.loads(path.read_text())
                self.assertEqual(record["outcome"], expected_outcome)
                self.assertEqual(record["source_commit"], "a" * 40)
                self.assertEqual(record["recipe"], list(FAST.recipe))
                self.assertNotIn("environment", record)
                self.assertGreaterEqual(record["total_seconds"], 0)


class RepositoryCoverageTests(unittest.TestCase):
    def test_physical_is_explicit_once_in_the_existing_required_catalog_job(self) -> None:
        workflow = (ROOT / ".github/workflows/ci.yml").read_text()
        catalog = workflow.split("\n  catalog:\n", 1)[1].split("\n  msrv:\n", 1)[0]
        self.assertIn("if: needs.profile.outputs.profile == 'full'", catalog)
        self.assertEqual(workflow.count("--suite catalog-metadata-working-set"), 1)
        self.assertEqual(catalog.count("--suite catalog-metadata-working-set"), 1)
        self.assertIn("--suite catalog-metadata-correctness", catalog)
        self.assertIn('suite = SUITES["catalog-metadata-working-set"]', catalog)
        self.assertIn("subprocess.run(suite.recipe", catalog)
        self.assertIn("--record", catalog)
        self.assertIn("test_catalog_metadata_suites", catalog)
        self.assertNotIn("continue-on-error", catalog)
        self.assertIn("needs: [profile, docs, rust, oci-registry, catalog, msrv, contracts, sdks]", workflow)
        self.assertIn("if: always()", workflow.split("\n  result:\n", 1)[1])
        self.assertIn("if: github.event_name == 'workflow_dispatch' && inputs.run_catalog_scale", catalog)
        self.assertEqual(workflow.count("production_catalog_100k -- --exact --ignored"), 1)

    def test_original_physical_inputs_limits_and_negative_control_are_retained(self) -> None:
        parent = ROOT / "crates/latent-control-store/src/deployments/tests/resources/compilation_memory.rs"
        source = parent.read_text()
        self.assertIn("const RELEASES: usize = 32;", source)
        self.assertIn("const DOCUMENTATION_BYTES: usize = 3 * 1024 * 1024;", source)
        self.assertIn("const MAX_GROWTH_KIB: u64 = 64 * 1024;", source)
        self.assertIn("const MAX_STATE_BYTES: usize = 512 * 1024;", source)
        self.assertRegex(source, r'#\[ignore = "physical qualification:[^\n]+\]\nfn large_release_metadata')
        self.assertIn('for mode in ["publish", "apply", "reopen"]', source)
        small = parent.with_suffix("").joinpath("correctness.rs").read_text()
        self.assertIn('#[should_panic(expected = "compiler metadata ownership accumulated")]', small)
        self.assertIn("fixture(true);", small)
        self.assertNotIn("high_water_kib", small)
        self.assertNotIn("LSF_METADATA_PHYSICAL", small)

    def test_documented_preparation_and_selection_match_inventory(self) -> None:
        document = (ROOT / "docs/development/metadata-working-set.md").read_text()
        self.assertIn(" ".join(FAST.recipe), document)
        for name in ("catalog-metadata-correctness", "catalog-metadata-working-set"):
            self.assertIn(f"--suite {name}", document)
        for assertion in set(FAST.assertions) | set(PHYSICAL.assertions):
            self.assertIn(f"`{assertion}`", document)

    def test_required_catalog_failure_cancellation_and_missing_work_fail_aggregate(self) -> None:
        workflow = (ROOT / ".github/workflows/ci.yml").read_text()
        aggregate = workflow.split("\n  result:\n", 1)[1]
        script = aggregate.split("python3 - <<'PY'\n", 1)[1].rsplit("\n          PY", 1)[0]
        script = textwrap.dedent(script)
        names = ("profile", "docs", "rust", "oci-registry", "catalog", "msrv", "contracts", "sdks")
        for outcome in ("failure", "cancelled", "skipped", None):
            needs = {name: {"result": "success"} for name in names}
            needs["profile"]["outputs"] = {"profile": "full"}
            if outcome is None:
                del needs["catalog"]
            else:
                needs["catalog"]["result"] = outcome
            with self.subTest(outcome=outcome):
                completed = subprocess.run(
                    [sys.executable, "-c", script],
                    env={**os.environ, "CI_JOB_RESULTS": json.dumps(needs)},
                    capture_output=True, text=True, timeout=10, check=False,
                )
                self.assertNotEqual(completed.returncode, 0)


if __name__ == "__main__":
    unittest.main()
