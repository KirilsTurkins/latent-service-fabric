"""Negative controls for the bounded deterministic-test measurement entrypoint."""
from pathlib import Path
import json
import subprocess
import unittest
from unittest.mock import patch

from tools import measure_deterministic_tests as subject


class DeterministicMeasurementTests(unittest.TestCase):
    def test_exact_nonempty_count_is_required(self):
        self.assertEqual(subject.test_count("test result: ok. 7 passed; 0 failed;", 7), 7)
        for output, expected in [
            ("", 7),
            ("test result: ok. 0 passed; 0 failed;", 0),
            ("test result: ok. 0 passed; 0 failed;", 7),
            ("test result: ok. 6 passed; 0 failed;", 7),
            ("test result: FAILED. 7 passed; 1 failed;", 7),
        ]:
            with self.subTest(output=output, expected=expected), self.assertRaises(ValueError):
                subject.test_count(output, expected)

    def test_failed_process_is_not_retried_or_accepted(self):
        failed = subprocess.CompletedProcess(["fixture"], 1, "7 passed", "failure")
        with patch.object(subject.subprocess, "run", return_value=failed) as run:
            with self.assertRaisesRegex(RuntimeError, "command failed"):
                subject.command(["fixture"], Path("."), timeout=1)
            run.assert_called_once()
            self.assertEqual(run.call_args.kwargs["timeout"], 1)

    def test_process_deadline_is_not_retried(self):
        with patch.object(subject.subprocess, "run", side_effect=subprocess.TimeoutExpired("fixture", 1)) as run:
            with self.assertRaises(subprocess.TimeoutExpired):
                subject.command(["fixture"], Path("."), timeout=1)
            run.assert_called_once()

    def test_compiler_artifact_selection_rejects_empty_and_duplicate_binaries(self):
        artifact = dict(reason="compiler-artifact", executable="/fixture", target=dict(name="latent_admission"), profile=dict(test=True))
        for output in ["", json.dumps(artifact) + "\n" + json.dumps(artifact)]:
            with self.subTest(output=output), patch.object(subject, "command", return_value=output):
                with self.assertRaises(ValueError):
                    subject.executable(Path("."), "latent-admission")
        with patch.object(subject, "command", return_value=json.dumps(artifact)):
            self.assertEqual(subject.executable(Path("."), "latent-admission"), "/fixture")

    def test_discovery_mismatch_fails_before_any_execution_measurement(self):
        report = {"measurements": []}
        with patch.object(subject, "executable", return_value="/fixture"), patch.object(subject, "command", side_effect=["revision", "", "0 tests, 0 benchmarks"]):
            with self.assertRaisesRegex(ValueError, "expected 1 listed tests"):
                subject.measure(Path("."), "after", 5, report)
        self.assertEqual(report["measurements"], [])


if __name__ == "__main__":
    unittest.main()
