"""Bounded owned fixture cleanup; no native capsule qualification is inferred."""
from __future__ import annotations

from contextlib import contextmanager
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import Mock, patch

from tools import run_dev_http_portable as runner


def sharing_violation():
    failure = PermissionError("owned fixture is still mapped")
    failure.winerror = 32
    return failure


class NativeTemporaryCleanup(unittest.TestCase):
    def test_foreign_or_relative_root_refuses_before_any_recursive_cleanup(self):
        with tempfile.TemporaryDirectory() as parent, tempfile.TemporaryDirectory() as foreign:
            for root in (Path(foreign), Path("relative-fixture"), Path(parent) / "unrelated-fixture"):
                temporary = SimpleNamespace(name=foreign, cleanup=Mock())
                with self.subTest(root=root), self.assertRaises(runner.DevError):
                    runner.retire_temporary(temporary, root, Path(parent).resolve())
                temporary.cleanup.assert_not_called()
            self.assertTrue(Path(foreign).exists())

    def test_transient_sharing_violations_retry_only_owned_cleanup(self):
        with tempfile.TemporaryDirectory() as parent:
            temporary = tempfile.TemporaryDirectory(dir=parent)
            root = Path(temporary.name)
            (root / "fixture").write_bytes(b"private fixture")
            cleanup = temporary.cleanup
            attempts = Mock(side_effect=[sharing_violation(), sharing_violation(), None])
            def retire():
                attempts()
                cleanup()
            with patch.object(temporary, "cleanup", side_effect=retire), \
                    patch.object(runner, "os", SimpleNamespace(name="nt")), patch.object(runner.time, "sleep") as sleep:
                runner.retire_temporary(temporary, root, Path(parent).resolve())
            self.assertEqual(attempts.call_count, 3)
            self.assertEqual(sleep.call_count, 2)
            self.assertFalse(root.exists())

    def test_unrelated_permission_failure_and_non_windows_fail_without_retry(self):
        for name, failure in (("nt", PermissionError("access denied")), ("posix", sharing_violation())):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as parent, \
                    tempfile.TemporaryDirectory(dir=parent) as root:
                temporary = SimpleNamespace(name=root, cleanup=Mock(side_effect=failure))
                with patch.object(runner, "os", SimpleNamespace(name=name)), \
                        patch.object(runner.time, "sleep") as sleep, self.assertRaises(PermissionError):
                    runner.retire_temporary(temporary, Path(root), Path(parent).resolve())
                self.assertEqual(temporary.cleanup.call_count, 1)
                sleep.assert_not_called()

    def test_persistent_lock_has_fixed_attempt_bound_and_original_cutoff(self):
        for samples, expected in (([0.0] * 9, 8), ([0.0, 0.1, 1.01], 2)):
            with self.subTest(expected=expected), tempfile.TemporaryDirectory() as parent, \
                    tempfile.TemporaryDirectory(dir=parent) as root:
                temporary = SimpleNamespace(name=root, cleanup=Mock(side_effect=sharing_violation()))
                clock = SimpleNamespace(monotonic=Mock(side_effect=samples), sleep=Mock())
                with patch.object(runner, "os", SimpleNamespace(name="nt")), \
                        patch.object(runner, "time", clock), self.assertRaises(PermissionError):
                    runner.retire_temporary(temporary, Path(root), Path(parent).resolve())
                self.assertEqual(temporary.cleanup.call_count, expected)
                self.assertEqual(clock.sleep.call_count, expected - 1)
                self.assertTrue(all(0 < call.args[0] <= 0.05 for call in clock.sleep.call_args_list))

    def test_successful_file_removal_after_original_cutoff_is_non_success(self):
        with tempfile.TemporaryDirectory() as parent, tempfile.TemporaryDirectory(dir=parent) as root:
            temporary = SimpleNamespace(name=root, cleanup=Mock())
            clock = SimpleNamespace(monotonic=Mock(side_effect=[0.0, 1.01]), sleep=Mock())
            with patch.object(runner, "time", clock), self.assertRaisesRegex(runner.DevError, "cleanup-deadline"):
                runner.retire_temporary(temporary, Path(root), Path(parent).resolve())
            temporary.cleanup.assert_called_once()
            clock.sleep.assert_not_called()

    def test_comparison_success_does_not_publish_success_before_fixture_retirement(self):
        for confirmed in (False, True):
            with self.subTest(confirmed=confirmed), tempfile.TemporaryDirectory() as parent, \
                    tempfile.TemporaryDirectory(prefix="lsf-http-native-") as root:
                root = Path(root)
                source = Path(parent) / "native-host-input"
                source.write_bytes(b"source-only test input, not an executable")
                inputs = Path(parent) / "inputs"
                inputs.mkdir()
                (inputs / "project").mkdir()
                output = Path(parent) / "receipt.json"
                @contextmanager
                def owned():
                    yield root
                    self.assertFalse(output.exists())
                    if not confirmed:
                        raise sharing_violation()
                native = {"identity": {"runtime": {"runs": [{"httpFixtureRequests": 4}]}}}
                with patch.object(runner, "os", SimpleNamespace(name="nt")), \
                        patch.object(runner, "native_temporary", owned), \
                        patch.object(runner.paths, "digest_file", return_value=("sha256:source-only", 1)), \
                        patch.object(runner.paths, "read", return_value=b'{"selection": []}'), \
                        patch.object(runner.project, "load", return_value=({}, None)), \
                        patch.object(runner.portable, "execute", return_value=native) as execute, \
                        patch.object(runner, "compare", return_value={"passed": True}):
                    if confirmed:
                        runner.run(source, inputs, output)
                    else:
                        with self.assertRaises(PermissionError):
                            runner.run(source, inputs, output)
                execute.assert_called_once()
                report = json.loads(output.read_bytes())
                self.assertIs(report["passed"], confirmed)
                self.assertFalse(report["qualificationComplete"])
                self.assertEqual(report["cleanup"], "owned-native-host-and-peer-reaped" if confirmed else "unconfirmed")
                if not confirmed:
                    self.assertEqual(report["failure"], "PermissionError")

    @unittest.skipUnless(os.name == "nt", "actual Windows sharing violation required")
    def test_actual_windows_file_mapping_is_released_before_owned_directory_retirement(self):
        api = ctypes.WinDLL("kernel32", use_last_error=True)
        api.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
                                   wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
        api.CreateFileW.restype = wintypes.HANDLE
        api.CloseHandle.argtypes, api.CloseHandle.restype = [wintypes.HANDLE], wintypes.BOOL
        with tempfile.TemporaryDirectory() as parent:
            temporary = tempfile.TemporaryDirectory(dir=parent)
            root = Path(temporary.name)
            owned = root / "private-fixture.bin"
            owned.write_bytes(b"original bounded fixture")
            handle = api.CreateFileW(str(owned), 0x80000000, 1, None, 3, 0x80, None)
            self.assertNotIn(handle, (None, ctypes.c_void_p(-1).value))
            cleanup, observed = temporary.cleanup, []
            def retire():
                nonlocal handle
                try:
                    cleanup()
                except PermissionError as failure:
                    observed.append(failure.winerror)
                    self.assertTrue(api.CloseHandle(handle))
                    handle = None
                    raise
            try:
                with patch.object(temporary, "cleanup", side_effect=retire):
                    runner.retire_temporary(temporary, root, Path(parent).resolve())
                self.assertEqual(observed, [32])
                self.assertFalse(root.exists())
            finally:
                if handle is not None:
                    self.assertTrue(api.CloseHandle(handle))
                cleanup()


if __name__ == "__main__":
    unittest.main()
