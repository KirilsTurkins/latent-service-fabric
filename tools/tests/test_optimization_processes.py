"""Failure-path supervision tests; real owned children, no load benchmark."""
import os
from pathlib import Path
import platform
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from optimization_runner.processes import OwnedProcess


@unittest.skipUnless(platform.system() == "Linux", "Linux process ownership protocol")
class ProcessOwnershipTests(unittest.TestCase):
    def test_periodic_exited_probe_preserves_last_observation_but_live_probe_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            child = OwnedProcess([sys.executable, "-c", "raise SystemExit(7)"],
                                 Path(directory) / "exited.log", "test", 5, Path(directory))
            try:
                while not child.exited():
                    time.sleep(0.005)
                previous = child.after
                with patch("optimization_runner.processes.snapshot", side_effect=PermissionError("exited proc")):
                    self.assertIs(child.sample(allow_exited=True), previous)
                    with self.assertRaises(RuntimeError):
                        child.sample()
                with self.assertRaises(RuntimeError):
                    child.wait()
                self.assertEqual(child.receipt["exit_code"], 7)
            finally:
                child.close()
            self.assertTrue(child.receipt["reaped"])

    def test_live_observation_error_is_not_hidden_and_wait_still_cleans_up(self):
        with tempfile.TemporaryDirectory() as directory:
            child = OwnedProcess([sys.executable, "-c", "import time; time.sleep(30)"],
                                 Path(directory) / "live.log", "test", 5, Path(directory))
            child.last_sample_ns -= 100_000_000
            with patch("optimization_runner.processes.snapshot", side_effect=PermissionError("live proc")):
                with self.assertRaises(PermissionError):
                    child.wait()
            self.assertTrue(child.receipt["reaped"])
            self.assertTrue(child.receipt["output_closed"])
            self.assertFalse(Path(f"/proc/{child.child.pid}").exists())

    def test_constructor_rolls_back_started_child_when_identity_capture_fails(self):
        import subprocess
        children = []
        original = subprocess.Popen
        def spawn(*args, **kwargs):
            child = original(*args, **kwargs)
            children.append(child)
            return child
        with tempfile.TemporaryDirectory() as directory:
            with patch("optimization_runner.processes.subprocess.Popen", side_effect=spawn), \
                 patch("optimization_runner.processes.snapshot", side_effect=OSError("injected proc failure")):
                with self.assertRaises(OSError):
                    OwnedProcess([sys.executable, "-c", "import time; time.sleep(30)"],
                                 Path(directory) / "capture.log", "test", 5, Path(directory))
            self.assertEqual(len(children), 1)
            self.assertIsNotNone(children[0].returncode)
            self.assertTrue(children[0].stdout.closed)
            self.assertFalse(Path(f"/proc/{children[0].pid}").exists())

    def test_nonzero_child_keeps_exit_receipt_and_closes_pipes(self):
        with tempfile.TemporaryDirectory() as directory:
            child = OwnedProcess([sys.executable, "-c", "print('retained failure'); raise SystemExit(7)"],
                                 Path(directory) / "failure.log", "test", 5, Path(directory))
            with self.assertRaises(RuntimeError):
                child.wait()
            self.assertEqual(child.receipt["exit_code"], 7)
            self.assertTrue(child.receipt["reaped"])
            self.assertTrue(child.receipt["output_closed"])
            self.assertIn("retained failure", (Path(directory) / "failure.log").read_text())

    def test_timeout_closes_owned_group(self):
        with tempfile.TemporaryDirectory() as directory:
            child = OwnedProcess([sys.executable, "-c", "import time; time.sleep(30)"],
                                 Path(directory) / "timeout.log", "test", 0.2, Path(directory))
            try:
                with self.assertRaises(TimeoutError):
                    child.wait()
            finally:
                child.close()
            self.assertTrue(child.receipt["reaped"])
            self.assertLess(child.receipt["exit_code"], 0)
            self.assertFalse(Path(f"/proc/{child.child.pid}").exists())

    def test_output_bound_fails_with_cleanup(self):
        with tempfile.TemporaryDirectory() as directory:
            child = OwnedProcess([sys.executable, "-c", "import sys; sys.stdout.write('x' * (5 * 1024 * 1024))"],
                                 Path(directory) / "output.log", "test", 5, Path(directory))
            try:
                with self.assertRaises(ValueError):
                    child.wait()
            finally:
                child.close()
            self.assertLessEqual((Path(directory) / "output.log").stat().st_size, 4 * 1024 * 1024)
            self.assertTrue(child.receipt["reaped"])


if __name__ == "__main__":
    unittest.main()
