"""A disappearing proc entry cannot become a partial or unbounded observation."""
import hashlib
import os
from pathlib import Path
import selectors
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from tools.phase2_gate_resource_os import Probe
from tools.phase2_operator_process import WorkflowError


class ProcSnapshotTests(unittest.TestCase):
    @unittest.skipUnless(sys.platform == "linux", "requires an owned Linux proc process")
    def test_fd_closing_during_enumeration_requires_a_new_complete_snapshot(self):
        program = ("import sys\n"
                   "stream=open('/proc/pressure/cpu','rb')\n"
                   "print(stream.fileno(),flush=True)\n"
                   "sys.stdin.buffer.readline()\n"
                   "stream.close()\n"
                   "print('closed',flush=True)\n"
                   "sys.stdin.buffer.readline()\n")
        child = subprocess.Popen([sys.executable, "-c", program], stdin=subprocess.PIPE,
                                 stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                 start_new_session=True, bufsize=0)

        def line():
            with selectors.DefaultSelector() as selector:
                selector.register(child.stdout, selectors.EVENT_READ)
                self.assertTrue(selector.select(2), "owned child rendezvous deadline")
                value = child.stdout.readline(32)
            self.assertTrue(value.endswith(b"\n"))
            return value.strip()

        try:
            descriptor = int(line())
            executable = Path(sys.executable).resolve()
            with executable.open("rb") as stream:
                digest = "sha256:" + hashlib.file_digest(stream, "sha256").hexdigest()
            process = SimpleNamespace(owner=SimpleNamespace(
                process=child, exited=lambda: child.poll() is not None), cancellation=None)
            with tempfile.TemporaryDirectory() as directory:
                probe = Probe(process, executable, digest, time.monotonic() + 5, Path(directory))
                before = probe.sample()
                self.assertEqual(before["loadSamplerFdCount"], 1)
                target = f"/proc/{child.pid}/fd/{descriptor}"
                readlink = os.readlink
                closed = False

                def close_then_read(path, *args, **kwargs):
                    nonlocal closed
                    if os.fspath(path) == target and not closed:
                        child.stdin.write(b"close\n")
                        self.assertEqual(line(), b"closed")
                        closed = True
                    return readlink(path, *args, **kwargs)

                with patch("tools.phase2_gate_resource_os.os.readlink", side_effect=close_then_read):
                    after = probe.sample()
                self.assertTrue(closed)
                self.assertEqual(after["processId"], before["processId"])
                self.assertEqual(after["startTimeTicks"], before["startTimeTicks"])
                self.assertEqual(after["fdCount"], before["fdCount"] - 1)
                self.assertEqual(after["loadSamplerFdCount"], 0)
                self.assertLessEqual(after["procBytesRead"], 4 * 1024 * 1024)
        finally:
            if child.poll() is None:
                child.terminate()
            try:
                child.wait(timeout=2)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait(timeout=2)
            child.stdin.close()
            child.stdout.close()

    def probe(self):
        probe = object.__new__(Probe)
        probe.pid = 42
        probe.current = Mock()
        return probe

    def test_continuous_disappearance_has_a_finite_attempt_bound(self):
        probe = self.probe()
        with patch.object(Probe, "_snapshot", side_effect=FileNotFoundError) as snapshot:
            with self.assertRaisesRegex(WorkflowError, "proc-snapshot-unsettled"):
                probe.sample()
        self.assertEqual(snapshot.call_count, 3)

    def test_disappearance_does_not_refresh_the_original_deadline(self):
        probe = self.probe()
        with patch.object(Probe, "_snapshot", side_effect=FileNotFoundError) as snapshot, \
                patch("tools.phase2_gate_resource_os.time.monotonic", side_effect=[0, 0, 3]):
            with self.assertRaisesRegex(WorkflowError, "proc-sample-deadline"):
                probe.sample()
        self.assertEqual(snapshot.call_count, 1)

    def test_owner_exit_is_not_treated_as_a_transient_entry(self):
        probe = self.probe()
        probe.current.side_effect = [None, WorkflowError("node-unexpected-exit")]
        with patch.object(Probe, "_snapshot", side_effect=FileNotFoundError) as snapshot:
            with self.assertRaisesRegex(WorkflowError, "node-unexpected-exit"):
                probe.sample()
        self.assertEqual(snapshot.call_count, 1)

    def test_disappearance_does_not_reset_aggregate_read_bytes(self):
        probe = self.probe()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bounded-input"
            path.write_bytes(b"x" * 65536)

            def consume_then_disappear(root, read, deadline, limits):
                for _ in range(40):
                    read(path)
                raise FileNotFoundError

            with patch.object(Probe, "_snapshot", side_effect=consume_then_disappear) as snapshot:
                with self.assertRaisesRegex(WorkflowError, "proc-read-bound"):
                    probe.sample()
            self.assertEqual(snapshot.call_count, 2)

    def test_other_io_failures_remain_visible(self):
        probe = self.probe()
        with patch.object(Probe, "_snapshot", side_effect=PermissionError) as snapshot:
            with self.assertRaises(PermissionError):
                probe.sample()
        self.assertEqual(snapshot.call_count, 1)


if __name__ == "__main__":
    unittest.main()
