"""The opt-in runner must not silently weaken a full measurement profile."""
import json
import os
import subprocess
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import phase1_measurement_environment as environment
import run_phase1_measurements as runner


class MeasurementRunnerTests(unittest.TestCase):
    @unittest.skipUnless(sys.platform == "linux", "actual Linux process-group ownership")
    def test_group_cleanup_precedes_reaping_even_after_success(self):
        events = []
        original_wait, original_kill = subprocess.Popen.wait, os.killpg

        def wait(child, *args, **kwargs):
            events.append("wait")
            return original_wait(child, *args, **kwargs)

        def kill(group, signal):
            events.append("kill")
            self.assertTrue(Path(f"/proc/{group}/stat").is_file())
            return original_kill(group, signal)

        with (tempfile.TemporaryDirectory() as directory,
              patch.object(subprocess.Popen, "wait", wait), patch.object(os, "killpg", kill)):
            runner.bounded_run([sys.executable, "-c", "print('done')"],
                               Path(directory) / "child.log", 2, os.environ.copy())
        self.assertEqual(events, ["kill", "wait"])

    @unittest.skipUnless(sys.platform == "linux", "actual Linux child identity")
    def test_parent_receipt_binds_actual_child_and_records_reap(self):
        with tempfile.TemporaryDirectory() as directory:
            receipt = {}
            output = runner.bounded_run([sys.executable, "-c", "import os; print(os.getpid())"],
                                        Path(directory) / "child.log", 2, os.environ.copy(), receipt)
            self.assertEqual(receipt["process_id"], int(output))
            self.assertTrue(receipt["start_time_ticks"].isdigit())
            self.assertTrue(receipt["reaped"])
            self.assertTrue(receipt["output_closed"])
            self.assertEqual(receipt["exit_code"], 0)

    def test_full_cannot_be_shortened_into_smoke(self):
        for kind, minimum in runner.FULL_REPETITIONS.items():
            self.assertEqual(runner.repetitions("full", (kind,), None), {kind: minimum})
            if minimum > 1:
                with self.assertRaisesRegex(ValueError, "minimum"):
                    runner.repetitions("full", (kind,), minimum - 1)
        with self.assertRaises(ValueError):
            runner.repetitions("full", runner.KINDS, 22)
        self.assertEqual(runner.repetitions("smoke", runner.KINDS, None),
                         {kind: 1 for kind in runner.KINDS})

    def test_missing_fixture_prevents_build_and_execution(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(runner, "build") as build:
            root = Path(directory)
            with self.assertRaises(OSError):
                runner.run("full", ("scale",), {"scale": 1}, root, root / "missing")
            build.assert_not_called()

    def test_empty_or_escaping_artifact_cannot_be_referenced(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            nested = root / "run"
            nested.mkdir()
            path = root / "artifact"
            path.write_bytes(b"retained")
            with self.assertRaises(ValueError):
                runner.reference(path, nested)
            path.write_bytes(b"")
            with self.assertRaises(ValueError):
                runner.reference(path, root)

    def test_evidence_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "report.json"
            runner.write_json(path, {"status": "failed"})
            with self.assertRaises(FileExistsError):
                runner.write_json(path, {"status": "passed"})
            self.assertIn("failed", path.read_text())

    def test_failed_collector_attempt_is_retained_in_suite(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "target"
            output = root / "evidence"
            output.mkdir()
            for name in ("echo", "generic", "capabilities"):
                path = target / f"capsules/{name}/{name}-capsule.wasm"
                path.parent.mkdir(parents=True)
                path.write_bytes(b"fixture")
            for name in ("build.log", "build-policy.log"):
                (output / name).write_text("build passed\n")
            with (patch.object(runner, "build", return_value=target / "collector"),
                  patch.object(runner, "capture", return_value={"source": {"dirty": True}}),
                  patch.object(runner, "host", return_value={"os": "Linux"}),
                  patch.object(runner, "bounded_run", side_effect=RuntimeError("driver exited 7"))):
                with self.assertRaisesRegex(RuntimeError, "exited 7"):
                    runner.run("smoke", ("scale",), {"scale": 1}, output, target)
            suite = json.loads((output / "suite.json").read_text())
            self.assertEqual(suite["runs"], [{"kind": "scale", "repetition": 1,
                "status": "failed", "reason": "collector-failed", "report": None}])
            self.assertTrue(any(row["path"] == "scale-01/plan.json" for row in suite["artifacts"]))

    def test_unavailable_host_observation_is_not_zero(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "missing"
            self.assertIsNone(environment.optional_text(path))
            path.write_bytes(b"a" * 16)
            self.assertIsNone(environment.optional_text(path, limit=15))


if __name__ == "__main__":
    unittest.main()
