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
REFERENCE_RAW = ROOT / "benchmarks" / "phase0" / "raw-results.json"


class Phase0CalibrationAggregateTests(unittest.TestCase):
    def make_archive(self, *, fail_run: int | None = None) -> tuple[tempfile.TemporaryDirectory[str], Path, str]:
        temporary = tempfile.TemporaryDirectory()
        archive = Path(temporary.name)
        baseline = json.loads(REFERENCE_RAW.read_text(encoding="utf-8"))
        source_commit = baseline["environment"]["repository_commit"]
        runs = archive / "runs"
        for index in range(1, 8):
            run = runs / f"run-{index:02d}"
            run.mkdir(parents=True)
            document = copy.deepcopy(baseline)
            document["environment"]["kernel"] = "Linux native-test 1.0 x86_64"
            if index == fail_run:
                document["checks"][0]["passed"] = False
            (run / "raw-results.json").write_text(
                json.dumps(document),
                encoding="utf-8",
            )
            (run / "BASELINE.md").write_text("# retained test report\n", encoding="utf-8")
            observation = {
                "schema_version": "latent.phase0.calibration.host-observation.v1",
                "source_commit": source_commit,
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
                        "exit_code": 0,
                    }
                ),
                encoding="utf-8",
            )
        return temporary, archive, source_commit

    def aggregate(self, archive: Path, source_commit: str) -> subprocess.CompletedProcess[str]:
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
            ],
            check=False,
            text=True,
            capture_output=True,
        )

    def test_aggregates_seven_full_profiles_without_dropping_samples(self) -> None:
        temporary, archive, source_commit = self.make_archive()
        with temporary:
            completed = self.aggregate(archive, source_commit)
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
            self.assertIn("Raw run archive", report)

    def test_rejects_a_failed_invariant_instead_of_dropping_the_run(self) -> None:
        temporary, archive, source_commit = self.make_archive(fail_run=7)
        with temporary:
            completed = self.aggregate(archive, source_commit)
            self.assertEqual(completed.returncode, 2)
            self.assertIn("failed hard invariants", completed.stderr)
            self.assertFalse((archive / "aggregate.json").exists())


if __name__ == "__main__":
    unittest.main()
