from __future__ import annotations

import copy
import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tools import aggregate_phase0_calibration as calibration_aggregate
from tools.phase0_collector_identity import (
    COLLECTOR_SCHEMA,
    EXPECTED_RELEASE_BUILD_CONFIGURATION,
)


ROOT = Path(__file__).resolve().parents[2]
AGGREGATOR = ROOT / "tools" / "aggregate_phase0_calibration.py"
HOT_PROFILE_RUNNER = ROOT / "tools" / "run_phase0_hot_path_profiles.sh"
CALIBRATION_RUNNER = ROOT / "tools" / "run_phase0_calibration.sh"
BUILD_ENVIRONMENT = ROOT / "tools" / "phase0_build_environment.sh"
REFERENCE_RAW = ROOT / "benchmarks" / "phase0" / "raw-results.json"


class Phase0CalibrationAggregateTests(unittest.TestCase):
    @staticmethod
    def write_executable(path: Path, contents: str) -> None:
        path.write_text(contents, encoding="utf-8")
        path.chmod(path.stat().st_mode | stat.S_IXUSR)

    def make_archive(
        self,
        *,
        fail_run: int | None = None,
        omit_check_run: int | None = None,
        legacy_provenance: bool = False,
    ) -> tuple[tempfile.TemporaryDirectory[str], Path, str, str]:
        temporary = tempfile.TemporaryDirectory()
        archive = Path(temporary.name)
        baseline = json.loads(REFERENCE_RAW.read_text(encoding="utf-8"))
        source_commit = baseline["environment"]["repository_commit"]
        source_tree = "1" * 40
        collector_bytes = b"phase0-baseline retained collector fixture\n"
        collector_identity = {
            "schema_version": COLLECTOR_SCHEMA,
            "collector": "phase0-baseline",
            "executable_digest": f"sha256:{hashlib.sha256(collector_bytes).hexdigest()}",
            "executable_bytes": len(collector_bytes),
            "build_configuration": dict(EXPECTED_RELEASE_BUILD_CONFIGURATION),
        }
        if not legacy_provenance:
            collector_directory = archive / "collector"
            collector_directory.mkdir()
            collector_path = collector_directory / "phase0-baseline"
            collector_path.write_bytes(collector_bytes)
            collector_path.chmod(collector_path.stat().st_mode | stat.S_IXUSR)
        runs = archive / "runs"
        for index in range(1, 8):
            run = runs / f"run-{index:02d}"
            run.mkdir(parents=True)
            document = copy.deepcopy(baseline)
            document["environment"]["kernel"] = "Linux native-test 1.0 x86_64"
            if legacy_provenance:
                document["artifact"].pop("collector", None)
            else:
                document["artifact"]["collector"] = copy.deepcopy(
                    collector_identity
                )
            if index == fail_run:
                document["checks"][0]["passed"] = False
            if index == omit_check_run:
                document["checks"].pop()
            (run / "raw-results.json").write_text(
                json.dumps(document),
                encoding="utf-8",
            )
            (run / "BASELINE.md").write_text("# retained test report\n", encoding="utf-8")
            observation = {
                "schema_version": (
                    "latent.phase0.calibration.host-observation.v1"
                    if legacy_provenance
                    else "latent.phase0.calibration.host-observation.v2"
                ),
                "source_commit": source_commit,
                "source_identity": {
                    "published_commit": source_commit,
                    "published_tree": source_tree,
                    "execution_commit": source_commit,
                    "execution_tree": source_tree,
                    "tree_identity_verified": True,
                },
                "native_linux_reference": True,
                "virtualization": {
                    "systemd_detect_virt": "none",
                    "systemd_detect_virt_container": "none",
                    "systemd_detect_virt_vm": "none",
                    "wsl_detected": False,
                },
                "cpu_frequency_policy": {
                    "cpus_with_cpufreq_sysfs": 0,
                    "observed": {},
                },
                "allocator": {
                    "source_global_allocator_lookup": "completed",
                    "source_global_allocator_matches": [],
                    "ld_preload": "unset",
                    "malloc_conf": "unset",
                    "observation": "standard allocator",
                },
                "background_load": {
                    "load_average": {"one_minute": 0.1 + index / 100.0},
                    "memory_available_bytes": 8_000_000_000 + index,
                },
            }
            if not legacy_provenance:
                observation["source_identity"].update(
                    {
                        "published_source_ref": "fix/phase0-gate-validation",
                        "published_source_ref_head": source_commit,
                        "published_commit_reachable_from_ref": True,
                        "execution_commit_matches_published": True,
                    }
                )
            for phase in ("before", "after"):
                (run / f"host-{phase}.json").write_text(
                    json.dumps(observation),
                    encoding="utf-8",
                )
            (run / "execution-status.json").write_text(
                json.dumps(
                    {
                        "schema_version": (
                            "latent.phase0.calibration.execution-status.v1"
                            if legacy_provenance
                            else "latent.phase0.calibration.execution-status.v2"
                        ),
                        "source_commit": source_commit,
                        "source_tree": source_tree,
                        "execution_commit": source_commit,
                        "execution_tree": source_tree,
                        "exit_code": 0,
                    }
                ),
                encoding="utf-8",
            )
            if not legacy_provenance:
                execution_path = run / "execution-status.json"
                execution = json.loads(execution_path.read_text(encoding="utf-8"))
                execution.update(
                    {
                        "published_source_ref": "fix/phase0-gate-validation",
                        "published_source_ref_head": source_commit,
                        "published_commit_reachable_from_ref": True,
                        "execution_commit_matches_published": True,
                    }
                )
                execution_path.write_text(json.dumps(execution), encoding="utf-8")
        return temporary, archive, source_commit, source_tree

    def aggregate(
        self, archive: Path, source_commit: str, source_tree: str
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                sys.executable,
                str(AGGREGATOR),
                "aggregate",
                "--runs-directory",
                str(archive / "runs"),
                "--output-json",
                str(archive / "aggregate.json"),
                "--output-report",
                str(archive / "CALIBRATION.md"),
                "--source-commit",
                source_commit,
                "--source-tree",
                source_tree,
            ],
            check=False,
            text=True,
            capture_output=True,
        )

    def verify(
        self, archive: Path, source_commit: str, source_tree: str
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                sys.executable,
                str(AGGREGATOR),
                "verify",
                "--aggregate",
                str(archive / "aggregate.json"),
                "--source-commit",
                source_commit,
                "--source-tree",
                source_tree,
            ],
            check=False,
            text=True,
            capture_output=True,
        )

    def test_aggregates_seven_full_profiles_without_dropping_samples(self) -> None:
        temporary, archive, source_commit, source_tree = self.make_archive()
        with temporary:
            completed = self.aggregate(archive, source_commit, source_tree)
            self.assertEqual(completed.returncode, 0, completed.stderr)
            aggregate = json.loads((archive / "aggregate.json").read_text(encoding="utf-8"))
            self.assertEqual(aggregate["status"], "pass")
            self.assertNotIn("inconclusive", json.dumps(aggregate))
            self.assertEqual(aggregate["run_count"], 7)
            self.assertEqual(
                aggregate["reference_identity"]["collector"]["collector"],
                "phase0-baseline",
            )
            self.assertTrue(
                all(
                    run["collector_identity"]
                    == aggregate["reference_identity"]["collector"]
                    for run in aggregate["raw_runs"]
                )
            )
            self.assertEqual(aggregate["hard_invariants"]["performance_runs_excluded"], 0)
            cold = aggregate["metrics"]["cold_activation_elapsed_micros"]
            self.assertEqual(cold["samples"]["sample_count"], 84)
            self.assertEqual(cold["run_count"], 7)
            self.assertIsNotNone(cold["comparison"])
            self.assertIn("rerun_required_rule", cold["comparison"])
            report = (archive / "CALIBRATION.md").read_text(encoding="utf-8")
            self.assertIn("Phase 1 advisory comparison bands", report)
            self.assertIn("no detectable regression", report)
            self.assertIn("Raw run archive", report)

    def test_rejects_a_failed_invariant_instead_of_dropping_the_run(self) -> None:
        temporary, archive, source_commit, source_tree = self.make_archive(fail_run=7)
        with temporary:
            completed = self.aggregate(archive, source_commit, source_tree)
            self.assertEqual(completed.returncode, 2)
            self.assertIn("failed hard invariants", completed.stderr)
            self.assertFalse((archive / "aggregate.json").exists())

    def test_rejects_a_run_that_omits_a_hard_invariant(self) -> None:
        temporary, archive, source_commit, source_tree = self.make_archive(omit_check_run=7)
        with temporary:
            completed = self.aggregate(archive, source_commit, source_tree)
            self.assertEqual(completed.returncode, 2)
            self.assertIn("hard invariant set differs", completed.stderr)
            self.assertIn("missing:", completed.stderr)
            self.assertFalse((archive / "aggregate.json").exists())

    def test_rejects_a_non_meaningful_cpu_model_identity(self) -> None:
        temporary, archive, source_commit, source_tree = self.make_archive()
        with temporary:
            raw_path = archive / "runs/run-01/raw-results.json"
            original = json.loads(raw_path.read_text(encoding="utf-8"))
            for cpu_model in ("unknown", "unavailable"):
                with self.subTest(cpu_model=cpu_model):
                    document = copy.deepcopy(original)
                    document["environment"]["cpu_model"] = cpu_model
                    raw_path.write_text(json.dumps(document), encoding="utf-8")
                    completed = self.aggregate(archive, source_commit, source_tree)
                    self.assertEqual(completed.returncode, 2)
                    self.assertIn(
                        "baseline identity environment cpu_model is not meaningful",
                        completed.stderr,
                    )

    def test_rejects_an_incomplete_host_comparability_identity(self) -> None:
        temporary, archive, source_commit, source_tree = self.make_archive()
        with temporary:
            host_path = archive / "runs/run-01/host-before.json"
            host = json.loads(host_path.read_text(encoding="utf-8"))
            host["allocator"] = {}
            host_path.write_text(json.dumps(host), encoding="utf-8")
            completed = self.aggregate(archive, source_commit, source_tree)
            self.assertEqual(completed.returncode, 2)
            self.assertIn("host observation allocator source lookup is not complete", completed.stderr)

    def test_rejects_a_run_whose_host_identity_changes_after_execution(self) -> None:
        temporary, archive, source_commit, source_tree = self.make_archive()
        with temporary:
            host_path = archive / "runs/run-01/host-after.json"
            host = json.loads(host_path.read_text(encoding="utf-8"))
            host["allocator"]["observation"] = "different host allocator state"
            host_path.write_text(json.dumps(host), encoding="utf-8")
            completed = self.aggregate(archive, source_commit, source_tree)
            self.assertEqual(completed.returncode, 2)
            self.assertIn(
                "run-01 changed static host comparability identity during its full-profile process",
                completed.stderr,
            )

    def test_rejects_missing_durable_ref_provenance(self) -> None:
        temporary, archive, source_commit, source_tree = self.make_archive()
        with temporary:
            host_path = archive / "runs/run-01/host-before.json"
            host = json.loads(host_path.read_text(encoding="utf-8"))
            del host["source_identity"]["published_source_ref_head"]
            host_path.write_text(json.dumps(host), encoding="utf-8")
            completed = self.aggregate(archive, source_commit, source_tree)
            self.assertEqual(completed.returncode, 2)
            self.assertIn("lacks durable published-source provenance", completed.stderr)

    def test_rejects_execution_status_with_a_different_durable_ref_head(self) -> None:
        temporary, archive, source_commit, source_tree = self.make_archive()
        with temporary:
            status_path = archive / "runs/run-01/execution-status.json"
            status = json.loads(status_path.read_text(encoding="utf-8"))
            status["published_source_ref_head"] = "f" * 40
            status_path.write_text(json.dumps(status), encoding="utf-8")
            completed = self.aggregate(archive, source_commit, source_tree)
            self.assertEqual(completed.returncode, 2)
            self.assertIn(
                "execution status does not match durable host source provenance",
                completed.stderr,
            )

    def test_rejects_native_collector_identity_drift_between_runs(self) -> None:
        temporary, archive, source_commit, source_tree = self.make_archive()
        with temporary:
            raw_path = archive / "runs/run-07/raw-results.json"
            document = json.loads(raw_path.read_text(encoding="utf-8"))
            document["artifact"]["collector"]["executable_digest"] = (
                "sha256:" + "f" * 64
            )
            raw_path.write_text(json.dumps(document), encoding="utf-8")

            completed = self.aggregate(archive, source_commit, source_tree)

            self.assertEqual(completed.returncode, 2)
            self.assertIn("inconsistent: run-07", completed.stderr)

    def test_rejects_a_tampered_retained_native_collector(self) -> None:
        temporary, archive, source_commit, source_tree = self.make_archive()
        with temporary:
            collector = archive / "collector/phase0-baseline"
            contents = collector.read_bytes()
            collector.write_bytes(bytes([contents[0] ^ 0xFF]) + contents[1:])

            completed = self.aggregate(archive, source_commit, source_tree)

            self.assertEqual(completed.returncode, 2)
            self.assertIn("retained executable digest does not match", completed.stderr)

    def test_current_verifier_refuses_a_legacy_calibration_schema(self) -> None:
        temporary, archive, source_commit, source_tree = self.make_archive(
            legacy_provenance=True
        )
        with temporary:
            self.assertFalse((archive / "collector").exists())
            historical = calibration_aggregate.build_aggregate(
                archive / "runs",
                source_commit,
                source_tree,
                7,
                allow_historical_legacy_provenance=True,
            )
            (archive / "aggregate.json").write_text(
                json.dumps(historical), encoding="utf-8"
            )
            completed = self.verify(archive, source_commit, source_tree)
            self.assertEqual(completed.returncode, 2)
            self.assertIn("unexpected schema", completed.stderr)

    def test_verifies_a_fresh_aggregate_against_its_raw_runs(self) -> None:
        temporary, archive, source_commit, source_tree = self.make_archive()
        with temporary:
            self.assertEqual(
                self.aggregate(archive, source_commit, source_tree).returncode,
                0,
            )
            completed = self.verify(archive, source_commit, source_tree)
            self.assertEqual(completed.returncode, 0, completed.stderr)
            summary = json.loads(completed.stdout)
            self.assertEqual(summary["status"], "pass")
            self.assertEqual(summary["run_count"], 7)

    def test_verifier_rejects_an_aggregate_relabelled_to_another_source(self) -> None:
        temporary, archive, source_commit, source_tree = self.make_archive()
        with temporary:
            self.assertEqual(
                self.aggregate(archive, source_commit, source_tree).returncode,
                0,
            )
            completed = self.verify(archive, "f" * 40, source_tree)
            self.assertEqual(completed.returncode, 2)
            self.assertIn("source commit does not match", completed.stderr)

    def test_verifier_rejects_a_manually_altered_aggregate(self) -> None:
        temporary, archive, source_commit, source_tree = self.make_archive()
        with temporary:
            self.assertEqual(
                self.aggregate(archive, source_commit, source_tree).returncode,
                0,
            )
            aggregate_path = archive / "aggregate.json"
            aggregate = json.loads(aggregate_path.read_text(encoding="utf-8"))
            aggregate["status"] = "blocked"
            aggregate_path.write_text(json.dumps(aggregate), encoding="utf-8")
            completed = self.verify(archive, source_commit, source_tree)
            self.assertEqual(completed.returncode, 2)
            self.assertIn("does not match the retained raw runs", completed.stderr)

    def test_verifier_rejects_a_missing_raw_run_artifact(self) -> None:
        temporary, archive, source_commit, source_tree = self.make_archive()
        with temporary:
            self.assertEqual(
                self.aggregate(archive, source_commit, source_tree).returncode,
                0,
            )
            (archive / "runs/run-07/execution-status.json").unlink()
            completed = self.verify(archive, source_commit, source_tree)
            self.assertEqual(completed.returncode, 2)
            self.assertIn("cannot read JSON", completed.stderr)

    def test_hot_profile_runner_requires_a_fresh_calibration_path(self) -> None:
        completed = subprocess.run(
            [
                str(HOT_PROFILE_RUNNER),
                "--published-source-commit",
                "a" * 40,
                "--published-source-tree",
                "b" * 40,
                "--published-source-ref",
                "example-source",
            ],
            check=False,
            text=True,
            capture_output=True,
        )
        self.assertEqual(completed.returncode, 2)
        self.assertIn("--calibration-aggregate is required", completed.stderr)

    def test_hot_profile_runner_rejects_a_missing_calibration_path_before_tool_checks(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            missing = Path(directory) / "missing-aggregate.json"
            completed = subprocess.run(
                [
                    str(HOT_PROFILE_RUNNER),
                    "--published-source-commit",
                    "a" * 40,
                    "--published-source-tree",
                    "b" * 40,
                    "--published-source-ref",
                    "example-source",
                    "--calibration-aggregate",
                    str(missing),
                ],
                check=False,
                text=True,
                capture_output=True,
            )
        self.assertEqual(completed.returncode, 2)
        self.assertIn("must be an existing regular file", completed.stderr)

    def test_calibration_runner_requires_durable_ref_and_external_output(self) -> None:
        missing_ref = subprocess.run(
            [
                str(CALIBRATION_RUNNER),
                "--published-source-commit",
                "a" * 40,
                "--published-source-tree",
                "b" * 40,
            ],
            check=False,
            text=True,
            capture_output=True,
        )
        self.assertEqual(missing_ref.returncode, 2)
        self.assertIn("durable published source commit, tree, and branch or tag ref", missing_ref.stderr)

        relative_output = subprocess.run(
            [
                str(CALIBRATION_RUNNER),
                "--published-source-commit",
                "a" * 40,
                "--published-source-tree",
                "b" * 40,
                "--published-source-ref",
                "development",
                "benchmarks/phase0/calibration/test-output",
            ],
            check=False,
            text=True,
            capture_output=True,
        )
        self.assertEqual(relative_output.returncode, 2)
        self.assertIn("must be an absolute path outside the source tree", relative_output.stderr)

        source_tree_output = subprocess.run(
            [
                str(CALIBRATION_RUNNER),
                "--published-source-commit",
                "a" * 40,
                "--published-source-tree",
                "b" * 40,
                "--published-source-ref",
                "development",
                str(ROOT / "target" / "phase0-calibration-test-output"),
            ],
            check=False,
            text=True,
            capture_output=True,
        )
        self.assertEqual(source_tree_output.returncode, 2)
        self.assertIn("must be outside the source tree", source_tree_output.stderr)

        with tempfile.TemporaryDirectory() as directory:
            environment = dict(os.environ)
            environment["LSF_CALIBRATION_TARGET_DIR"] = str(
                ROOT / "target" / "phase0-calibration-test-build"
            )
            source_tree_build = subprocess.run(
                [
                    str(CALIBRATION_RUNNER),
                    "--published-source-commit",
                    "a" * 40,
                    "--published-source-tree",
                    "b" * 40,
                    "--published-source-ref",
                    "development",
                    str(Path(directory) / "evidence"),
                ],
                check=False,
                text=True,
                capture_output=True,
                env=environment,
            )
        self.assertEqual(source_tree_build.returncode, 2)
        self.assertIn("calibration build output must be outside the source tree", source_tree_build.stderr)

        with tempfile.TemporaryDirectory() as directory:
            environment = dict(os.environ)
            environment["LSF_CALIBRATION_TARGET_DIR"] = directory
            reused_build = subprocess.run(
                [
                    str(CALIBRATION_RUNNER),
                    "--published-source-commit",
                    "a" * 40,
                    "--published-source-tree",
                    "b" * 40,
                    "--published-source-ref",
                    "development",
                    str(Path(directory) / "evidence"),
                ],
                check=False,
                text=True,
                capture_output=True,
                env=environment,
            )
        self.assertEqual(reused_build.returncode, 2)
        self.assertIn("build output directory must not already exist", reused_build.stderr)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            environment = dict(os.environ)
            environment["LSF_CALIBRATION_TARGET_DIR"] = str(root / "evidence" / "build")
            overlapping_build = subprocess.run(
                [
                    str(CALIBRATION_RUNNER),
                    "--published-source-commit",
                    "a" * 40,
                    "--published-source-tree",
                    "b" * 40,
                    "--published-source-ref",
                    "development",
                    str(root / "evidence"),
                ],
                check=False,
                text=True,
                capture_output=True,
                env=environment,
            )
        self.assertEqual(overlapping_build.returncode, 2)
        self.assertIn("calibration output and build paths must not overlap", overlapping_build.stderr)

    def test_calibration_runner_rejects_a_local_tag_when_origin_fetch_fails(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            tools = source / "tools"
            tools.mkdir(parents=True)
            shutil.copy2(CALIBRATION_RUNNER, tools / CALIBRATION_RUNNER.name)
            shutil.copy2(BUILD_ENVIRONMENT, tools / BUILD_ENVIRONMENT.name)
            bin_directory = root / "bin"
            bin_directory.mkdir()
            self.write_executable(
                bin_directory / "git",
                "#!/usr/bin/env bash\n"
                "set -eu\n"
                "case \"${1:-}\" in\n"
                "  status|check-ref-format|show-ref|cat-file|merge-base) exit 0 ;;\n"
                "  fetch) exit 1 ;;\n"
                "  rev-parse)\n"
                "    case \"${2:-}\" in\n"
                f"      HEAD) printf '%s\\n' '{'a' * 40}' ;;\n"
                f"      'HEAD^{{tree}}'|*'^{{tree}}') printf '%s\\n' '{'b' * 40}' ;;\n"
                f"      *) printf '%s\\n' '{'a' * 40}' ;;\n"
                "    esac\n"
                "    ;;\n"
                "  *) exit 98 ;;\n"
                "esac\n",
            )
            for command in ("cargo",):
                self.write_executable(
                    bin_directory / command, "#!/usr/bin/env bash\nexit 0\n"
                )
            self.write_executable(
                bin_directory / "uname", "#!/usr/bin/env bash\nprintf '%s\\n' Linux\n"
            )
            self.write_executable(
                bin_directory / "systemd-detect-virt",
                "#!/usr/bin/env bash\nprintf '%s\\n' none\n",
            )
            environment = dict(os.environ)
            environment["PATH"] = f"{bin_directory}:{environment['PATH']}"
            environment["PYTHON"] = sys.executable
            output = root / "evidence"

            completed = subprocess.run(
                [
                    str(tools / CALIBRATION_RUNNER.name),
                    "--published-source-commit",
                    "a" * 40,
                    "--published-source-tree",
                    "b" * 40,
                    "--published-source-ref",
                    "refs/tags/local-only",
                    str(output),
                ],
                check=False,
                text=True,
                capture_output=True,
                cwd=source,
                env=environment,
            )

            self.assertEqual(completed.returncode, 2)
            self.assertIn(
                "cannot fetch durable published source tag from origin",
                completed.stderr,
            )
            self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
