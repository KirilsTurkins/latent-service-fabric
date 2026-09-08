"""Small supervisor failures must terminate and retain bounded diagnostics."""
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import run_phase1_conformance as runner


@unittest.skipUnless(sys.platform == "linux", "Linux process-group supervisor")
class RunnerTests(unittest.TestCase):
    def test_timeout_cannot_wait_for_an_inherited_pipe_forever(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "timeout.log"
            started = time.monotonic()
            code = ("import subprocess,sys; "
                    "subprocess.Popen([sys.executable,'-c','import time; time.sleep(10)']); "
                    "print('parent finished',flush=True)")
            with self.assertRaisesRegex(RuntimeError, "deadline"):
                runner.bounded_run([sys.executable, "-c", code], path, 0.2, os.environ.copy())
            self.assertLess(time.monotonic() - started, 3)
            self.assertIn(b"parent finished", path.read_bytes())

    def test_overflow_is_failure_with_capped_file(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(runner, "MAX_LOG", 1024):
            path = Path(directory) / "overflow.log"
            with self.assertRaisesRegex(RuntimeError, "output exceeded"):
                runner.bounded_run([sys.executable, "-c", "import os; os.write(1,b'x'*16384)"],
                                   path, 2, os.environ.copy())
            self.assertLessEqual(path.stat().st_size, 1024)

    def test_nonzero_exit_cannot_be_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(RuntimeError, "exited 7"):
                runner.bounded_run([sys.executable, "-c", "raise SystemExit(7)"],
                                   Path(directory) / "failed.log", 2, os.environ.copy())

    def test_missing_fixture_fails_before_any_execution(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(OSError):
                runner.digest(Path(directory) / "absent.wasm")


if __name__ == "__main__":
    unittest.main()
