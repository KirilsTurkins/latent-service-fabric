"""Tiny real subprocess regressions; no compilation, network or durable output."""
from __future__ import annotations

import ctypes
import os
from pathlib import Path
import subprocess
import sys
import signal
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from tools import build_process
from tools.build_process import BuildProcessError, run_bounded


def _alive(pid):
    if os.name == "nt":
        from ctypes import wintypes
        api = ctypes.WinDLL("kernel32", use_last_error=True)
        api.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        api.OpenProcess.restype = wintypes.HANDLE
        api.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        api.WaitForSingleObject.restype = wintypes.DWORD
        api.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = api.OpenProcess(0x00100000, False, pid)
        if not handle:
            return False
        try:
            return api.WaitForSingleObject(handle, 0) == 258
        finally:
            api.CloseHandle(handle)
    try:
        fields = Path(f"/proc/{pid}/stat").read_bytes().rpartition(b") ")[2].split()
    except FileNotFoundError:
        return False
    return fields[0] not in (b"Z", b"X")


def _resource_count():
    if os.name == "nt":
        from ctypes import wintypes
        api = ctypes.WinDLL("kernel32", use_last_error=True)
        api.GetCurrentProcess.restype = wintypes.HANDLE
        api.GetProcessHandleCount.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        count = wintypes.DWORD()
        if not api.GetProcessHandleCount(api.GetCurrentProcess(), ctypes.byref(count)):
            raise AssertionError("handle accounting failed")
        return count.value
    return len(list(Path("/proc/self/fd").iterdir()))


@unittest.skipUnless(os.name == "nt" or sys.platform == "linux", "supported process platform")
class BuildProcessTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="latent-process-test-")
        self.root = Path(self.directory.name)
        self.addCleanup(self.directory.cleanup)

    def run_python(self, source, *, maximum=4096, timeout=3):
        return run_bounded([sys.executable, "-c", source], self.root, dict(os.environ),
                           timeout_seconds=timeout, max_output_bytes=maximum)

    def assert_gone(self, pid):
        deadline = time.monotonic() + 1
        while _alive(pid) and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertFalse(_alive(pid), "owned child remains active")

    def test_binary_output_exact_combined_limit_and_overflow(self):
        command = "import os; os.write(1,b'\\0\\xffab'); os.write(2,b'cd')"
        result = self.run_python(command, maximum=6)
        self.assertIsInstance(result, subprocess.CompletedProcess)
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, b"\0\xffab", b"cd"))
        with self.assertRaisesRegex(BuildProcessError, "^command-output-limit$"):
            self.run_python(command, maximum=5)

    def test_nonzero_output_and_spawn_error_are_redacted(self):
        with self.assertRaises(BuildProcessError) as failed:
            self.run_python("import os; os.write(2,b'PRIVATE TOKEN'); raise SystemExit(7)")
        self.assertEqual(str(failed.exception), "command-exit")
        self.assertNotIn("PRIVATE", repr(failed.exception))
        with self.assertRaisesRegex(BuildProcessError, "^command-failed$"):
            run_bounded([str(self.root / "PRIVATE-nonexistent.exe")], self.root, dict(os.environ), 1, 32)

    def test_limits_reject_before_spawning(self):
        cases = [(0, 32), (True, 32), (float("nan"), 32), (float("inf"), 32),
                 (10 ** 1000, 32), (3601, 32), (1, 0), (1, True),
                 (1, build_process.MAX_OUTPUT_BYTES + 1)]
        with patch.object(build_process, "_new_owner") as spawn:
            for timeout, maximum in cases:
                with self.subTest(timeout=repr(timeout)[:20], maximum=maximum):
                    with self.assertRaises(BuildProcessError):
                        self.run_python("pass", timeout=timeout, maximum=maximum)
            spawn.assert_not_called()

    def test_silent_deadline_reaps_leader(self):
        owners = []
        factory = build_process._new_owner

        def record():
            owner = factory()
            owners.append(owner)
            return owner

        started = time.monotonic()
        with patch.object(build_process, "_new_owner", record):
            with self.assertRaisesRegex(BuildProcessError, "^command-deadline$"):
                self.run_python("import time; time.sleep(30)", timeout=0.5)
        self.assertLess(time.monotonic() - started, 6)
        self.assertIsNotNone(owners[0].process.returncode)
        self.assert_gone(owners[0].process.pid)

    def test_flood_is_bounded_and_creates_no_reader_threads(self):
        before = threading.active_count()
        with self.assertRaisesRegex(BuildProcessError, "^command-output-limit$"):
            self.run_python("import os\nwhile True: os.write(2,b'x'*4096)", maximum=8192)
        self.assertEqual(threading.active_count(), before)

    def descendant_source(self, *, exit_parent):
        tail = "" if exit_parent else "\nimport time; time.sleep(30)"
        return ("import subprocess,sys,pathlib\n"
                "p=subprocess.Popen([sys.executable,'-c','import time; time.sleep(30)'])\n"
                "pathlib.Path('child.pid').write_text(str(p.pid))\n"
                "print('ready',flush=True)" + tail)

    def test_successful_early_parent_exit_cleans_inherited_pipe_descendant(self):
        result = self.run_python(self.descendant_source(exit_parent=True))
        self.assertEqual(result.stdout.splitlines(), [b"ready"])
        self.assert_gone(int((self.root / "child.pid").read_text()))

    def test_deadline_cleans_descendant_and_preserves_unrelated_process(self):
        kwargs = {"creationflags": 0x08000000} if os.name == "nt" else {}
        unrelated = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"], **kwargs)
        try:
            with self.assertRaisesRegex(BuildProcessError, "^command-deadline$"):
                self.run_python(self.descendant_source(exit_parent=False), timeout=0.7)
            self.assert_gone(int((self.root / "child.pid").read_text()))
            self.assertIsNone(unrelated.poll())
        finally:
            unrelated.kill()
            unrelated.wait(timeout=3)

    def test_cancellation_cleans_descendant_before_propagating(self):
        def interrupt(owner, deadline, maximum, cancellation):
            marker = self.root / "child.pid"
            while not marker.exists() and time.monotonic() < deadline:
                time.sleep(0.01)
            self.assertTrue(marker.exists())
            raise KeyboardInterrupt()

        with patch.object(build_process, "_capture", interrupt):
            with self.assertRaises(KeyboardInterrupt):
                self.run_python(self.descendant_source(exit_parent=False))
        self.assert_gone(int((self.root / "child.pid").read_text()))

    def test_second_cancellation_during_cleanup_cannot_skip_termination(self):
        owners = []
        factory = build_process._new_owner

        def record():
            owner = factory()
            finish = owner.finish
            close = owner.close

            def interrupted_finish(deadline):
                signal.raise_signal(signal.SIGINT)
                finish(deadline)

            def interrupted_close():
                signal.raise_signal(signal.SIGINT)
                close()

            owner.finish = interrupted_finish
            owner.close = interrupted_close
            owners.append(owner)
            return owner

        with patch.object(build_process, "_new_owner", record):
            with patch.object(build_process, "_capture", side_effect=KeyboardInterrupt()):
                with self.assertRaises(KeyboardInterrupt):
                    self.run_python("import time; time.sleep(30)")
        self.assertTrue(owners[0].finished)
        self.assertIsNotNone(owners[0].process.returncode)
        self.assert_gone(owners[0].process.pid)

    def test_signal_before_cleanup_context_entry_cannot_abandon_owner(self):
        owners = []
        factory = build_process._new_owner

        def record():
            owner = factory()
            owners.append(owner)
            return owner

        def interrupt(owner, deadline, maximum, cancellation):
            defer = cancellation.defer

            def before_entry():
                # Fires before defer's generator enters and increments depth.
                signal.raise_signal(signal.SIGINT)
                return defer()

            cancellation.defer = before_entry
            raise KeyboardInterrupt()

        with patch.object(build_process, "_new_owner", record):
            with patch.object(build_process, "_capture", interrupt):
                with self.assertRaises(KeyboardInterrupt):
                    self.run_python("import time; time.sleep(30)")
        self.assertTrue(owners[0].finished)
        self.assert_gone(owners[0].process.pid)

    def test_sigterm_during_capture_runs_cleanup_before_exit(self):
        owners = []
        factory = build_process._new_owner
        previous = signal.getsignal(signal.SIGTERM)

        def record():
            owner = factory()
            owners.append(owner)
            return owner

        def terminate(*_args):
            signal.raise_signal(signal.SIGTERM)

        with patch.object(build_process, "_new_owner", record):
            with patch.object(build_process, "_capture", terminate):
                with self.assertRaises(SystemExit) as exit_signal:
                    self.run_python("import time; time.sleep(30)")
        self.assertEqual(exit_signal.exception.code, 128 + signal.SIGTERM)
        self.assertEqual(signal.getsignal(signal.SIGTERM), previous)
        self.assertTrue(owners[0].finished)
        self.assert_gone(owners[0].process.pid)

    def test_signal_during_constructor_is_deferred_until_child_is_owned(self):
        created = []
        factory = subprocess.Popen
        previous = signal.getsignal(signal.SIGINT)

        def interrupt(*args, **kwargs):
            process = factory(*args, **kwargs)
            created.append(process)
            # This is the dangerous constructor window: the OS child exists,
            # but the platform owner's assignment has not happened yet.
            signal.raise_signal(signal.SIGINT)
            return process

        with patch.object(subprocess, "Popen", interrupt):
            with self.assertRaises(KeyboardInterrupt):
                self.run_python("import time; time.sleep(30)")
        self.assertEqual(signal.getsignal(signal.SIGINT), previous)
        self.assertIsNotNone(created[0].returncode)
        self.assert_gone(created[0].pid)

    def test_repeated_success_and_failure_do_not_retain_handles_or_threads(self):
        self.run_python("pass")  # Load platform DLL/module before the baseline.
        before = _resource_count()
        threads = threading.active_count()
        for _ in range(4):
            self.run_python("print('ok')")
            with self.assertRaises(BuildProcessError):
                self.run_python("raise SystemExit(1)")
        self.assertLessEqual(_resource_count(), before + 1)
        self.assertEqual(threading.active_count(), threads)

    @unittest.skipUnless(os.name == "nt", "Windows suspended-start ownership")
    def test_failed_job_assignment_never_runs_recipe(self):
        from tools import build_process_windows
        owners = []
        factory = build_process._new_owner

        def record():
            owner = factory()
            owners.append(owner)
            return owner

        with patch.object(build_process, "_new_owner", record):
            with patch.object(build_process_windows._Job, "assign_and_resume", side_effect=OSError("PRIVATE")):
                with self.assertRaisesRegex(BuildProcessError, "^command-failed$"):
                    self.run_python("from pathlib import Path; Path('executed').write_text('bad')")
        self.assertFalse((self.root / "executed").exists())
        self.assertIsNotNone(owners[0].process.returncode)
        self.assert_gone(owners[0].process.pid)

    @unittest.skipUnless(sys.platform == "linux", "Linux exclusive reaper ownership")
    def test_competing_reaper_never_signals_unreserved_group(self):
        from tools import build_process_linux
        owner = build_process_linux.OwnedProcess()
        owner.process = unittest.mock.Mock(pid=12345)
        with patch.object(os, "waitid", side_effect=ChildProcessError()):
            with patch.object(os, "killpg") as signal_group:
                with self.assertRaisesRegex(BuildProcessError, "^process-ownership$"):
                    owner.finish(time.monotonic() + 1)
                signal_group.assert_not_called()


if __name__ == "__main__":
    unittest.main()
