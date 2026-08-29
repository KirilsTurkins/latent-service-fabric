from __future__ import annotations

import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
AGGREGATOR = ROOT / "tools" / "aggregate_phase0_calibration.py"
HOT_PROFILE_RUNNER = ROOT / "tools" / "run_phase0_hot_path_profiles.sh"
REFERENCE_RAW = ROOT / "benchmarks" / "phase0" / "raw-results.json"


class Phase0CalibrationAggregateTests(unittest.TestCase):
    def make_archive(
        self, *, fail_run: int | None = None, omit_check_run: int | None = None
    ) -> tuple[tempfile.TemporaryDirectory[str], Path, str, str]:
        temporary = tempfile.TemporaryDirectory()
        archive = Path(temporary.name)
        baseline = json.loads(REFERENCE_RAW.read_text(encoding="utf-8"))
        source_commit = baseline["environment"]["repository_commit"]
        source_tree = "1" * 40
        runs = archive / "runs"
        for index in range(1, 8):
            run = runs / f"run-{index:02d}"
            run.mkdir(parents=True)
            document = copy.deepcopy(baseline)
            document["environment"]["kernel"] = "Linux native-test 1.0 x86_64"
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
                "schema_version": "latent.phase0.calibration.host-observation.v1",
                "source_commit": source_commit,
                "source_identity": {
                    "published_commit": source_commit,
                    "published_tree": source_tree,
                    "execution_commit": source_commit,
                    "execution_tree": source_tree,
                    "tree_identity_verified": True,
                },
                "native_linux_reference": True,
                "virtualization": {"systemd_detect_virt": "none"},
                "cpu_frequency_policy": {"observed": {}},
                "allocator": {"ld_preload": "unset"},
                "background_load": {
                    "load_average": {"one_minute": 0.1 + index / 100.0},
                    "memory_available_bytes": 8_000_000_000 + index,
                },
            }
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
            self.assertEqual(aggregate["run_count"], 7)
            self.assertEqual(aggregate["hard_invariants"]["performance_runs_excluded"], 0)
            cold = aggregate["metrics"]["cold_activation_elapsed_micros"]
            self.assertEqual(cold["samples"]["sample_count"], 84)
            self.assertEqual(cold["run_count"], 7)
            self.assertIsNotNone(cold["comparison"])
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


if __name__ == "__main__":
    unittest.main()
