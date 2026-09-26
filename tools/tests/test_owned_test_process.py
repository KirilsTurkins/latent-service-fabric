"""Deterministic ownership tests; synthetic children are NOT LSF qualification."""
from __future__ import annotations

import asyncio
from contextlib import redirect_stdout
import io
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch

from tools import owned_process_worker as worker
from tools.owned_test_process import ProcessFailure, Result, run_owned, run_owned_async
from tools.test_run import Ready, TestRun, digest, redact

ROOT = Path(__file__).resolve().parents[2]


def policy(**updates):
    value = {"platforms": ["linux-x86_64"], "timeoutSeconds": 10,
             "prerequisites": {"tools": [], "services": [], "filesystem": ["private-mode", "atomic-replace", "fsync", "file-lock"],
                               "accounting": [], "artifacts": [], "versionScopes": []}}
    value.update(updates)
    return value


class ContractTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.addCleanup(self.temp.cleanup)

    def run_context(self, **kwargs):
        return TestRun("synthetic", policy(), repo=ROOT, synthetic=True,
                       diagnostic_root=self.root, **kwargs)

    def test_missing_tool_fails_before_expensive_execution(self):
        run = self.run_context()
        run.policy["prerequisites"]["tools"] = ["no-such-compiler"]
        with redirect_stdout(io.StringIO()), patch("tools.test_run.shutil.which", return_value=None), \
                patch.object(run, "command") as command:
            with self.assertRaises(ProcessFailure) as caught, run:
                run.prerequisites()
            command.assert_not_called()
        self.assertEqual(caught.exception.category, "unavailable-environment")
        self.assertEqual(run.record["outcome"], "not-run")
        self.assertFalse(run.root.exists())

    def test_invalid_fixture_is_not_unavailable_environment(self):
        run = self.run_context()
        run.policy["prerequisites"]["artifacts"] = ["component"]
        with redirect_stdout(io.StringIO()), self.assertRaises(ProcessFailure) as error, run:
            run.prerequisites()
        self.assertEqual(error.exception.category, "invalid-fixture")
        self.assertEqual(run.record["outcome"], "failed")

    def test_build_preflight_does_not_require_or_prepare_artifacts(self):
        run = self.run_context()
        run.policy["prerequisites"]["artifacts"] = ["component"]
        with redirect_stdout(io.StringIO()), patch.object(run, "command") as command, run:
            run.prerequisites(before_build=True)
            command.assert_not_called()
        self.assertEqual(run.record["outcome"], "passed")

    def test_unsupported_platform_is_not_successful_coverage(self):
        run = self.run_context()
        with redirect_stdout(io.StringIO()), patch("tools.test_run.sys.platform", "win32"), \
                self.assertRaises(ProcessFailure), run:
            run.prerequisites()
        self.assertEqual(run.record["outcome"], "not-run")

    def test_denied_owned_accounting_is_never_zero(self):
        run = self.run_context()
        run.policy["prerequisites"]["accounting"] = ["owned-io"]
        with redirect_stdout(io.StringIO()), patch.object(run, "command", side_effect=ProcessFailure("assertion-failure", "denied")), \
                self.assertRaises(ProcessFailure), run:
            run.prerequisites()
        self.assertEqual(run.record["reason"], "owned-io-accounting-denied")
        self.assertNotIn("readBytes", run.record)

    def test_accounting_timeout_retains_infrastructure_classification(self):
        run = self.run_context()
        run.policy["prerequisites"]["accounting"] = ["owned-io"]
        with redirect_stdout(io.StringIO()), patch.object(run, "command", side_effect=ProcessFailure("infrastructure-timeout", "timeout")), \
                self.assertRaises(ProcessFailure), run:
            run.prerequisites()
        self.assertEqual(run.record["category"], "infrastructure-timeout")

    def test_missing_child_list_prevents_any_scenario_spawn(self):
        read_fd, write_fd = os.pipe()
        spec = json.dumps({"deadline": time.monotonic() + 5, "workDeadline": time.monotonic() + 3,
                           "command": ["not-executed"], "cwd": ".", "env": {}}).encode() + b"\n"
        with patch.object(sys, "argv", ["worker", str(write_fd), "nonce"]), \
                patch.object(worker.select, "select", return_value=([0], [], [])), \
                patch.object(worker.os, "read", return_value=spec), \
                patch.object(worker, "children", side_effect=PermissionError()), \
                patch.object(worker.os, "waitpid", side_effect=ChildProcessError()), \
                patch.object(worker.ctypes, "CDLL", return_value=Mock(prctl=Mock(return_value=0))), \
                patch.object(worker.subprocess, "Popen") as popen:
            old_term, old_int = signal.getsignal(signal.SIGTERM), signal.getsignal(signal.SIGINT)
            try:
                self.assertEqual(worker.main(), 0)
            finally:
                signal.signal(signal.SIGTERM, old_term)
                signal.signal(signal.SIGINT, old_int)
            popen.assert_not_called()
        record = json.loads(os.read(read_fd, 4096))
        os.close(read_fd)
        self.assertEqual(record["reason"], "accounting-or-execution-denied")
        self.assertIsNone(record["returncode"])
        self.assertEqual(record["reaped"], 0)  # no child launched; NOT an I/O measurement

    def test_private_root_and_atomic_filesystem_probe_are_removed(self):
        run = self.run_context()
        with redirect_stdout(io.StringIO()), run:
            run.prerequisites()
            self.assertEqual(run.root.stat().st_mode & 0o777, 0o700)
            self.assertEqual(list(run.root.iterdir()), [])
        self.assertFalse(run.root.exists())
        self.assertEqual(run.record_path.stat().st_mode & 0o777, 0o600)

    def test_artifact_symlink_missing_and_oversized_rejected(self):
        good = self.root / "good"
        good.write_bytes(b"123")
        linked = self.root / "link"
        linked.symlink_to(good)
        for path, maximum in ((linked, 10), (self.root / "absent", 10), (good, 1)):
            run = self.run_context()
            with redirect_stdout(io.StringIO()), self.assertRaises(ProcessFailure), run:
                run.artifact("component", path, maximum)

    def test_digest_hashes_actual_fixture(self):
        path = self.root / "fixture"
        path.write_bytes(b"abc")
        self.assertEqual(digest(path, 3), "sha256:ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad")

    def test_false_stale_or_wrong_endpoint_readiness_fails_without_retry(self):
        for field, wrong in (("owner", "old-child"), ("run", "old-run"), ("endpoint", "https://127.0.0.1:2"), ("protocol", "wrong")):
            run = self.run_context()
            expected = Ready("child", run.run_id, "https://127.0.0.1:1", "http-v2")
            values = dict(expected.__dict__, **{field: wrong})
            probe = Mock(return_value=Ready(**values))
            with redirect_stdout(io.StringIO()), self.assertRaises(ProcessFailure), run:
                run.ready(expected, lambda: True, probe)
            self.assertEqual(probe.call_count, 1)
            self.assertEqual(run.record["reason"], "false-or-stale-readiness")

    def test_readiness_rechecks_current_liveness(self):
        run = self.run_context()
        ready = Ready("child", run.run_id, "tls-loopback", "v2")
        with redirect_stdout(io.StringIO()), self.assertRaises(ProcessFailure), run:
            run.ready(ready, Mock(side_effect=[True, False]), lambda: ready)
        self.assertEqual(run.record["reason"], "readiness-owner-exited")

    def test_dead_owner_never_polls_endpoint(self):
        run = self.run_context()
        probe = Mock()
        with redirect_stdout(io.StringIO()), self.assertRaises(ProcessFailure), run:
            run.ready(Ready("c", run.run_id, "loopback", "v2"), lambda: False, probe)
        probe.assert_not_called()

    def test_stalled_readiness_has_finite_watchdog(self):
        run = self.run_context()
        with redirect_stdout(io.StringIO()), self.assertRaises(ProcessFailure), run:
            run.ready(Ready("c", run.run_id, "loopback", "v2"), lambda: True, lambda: None, timeout=0.01)
        self.assertEqual(run.record["reason"], "readiness-timeout")

    def test_successful_identity_bound_readiness(self):
        run = self.run_context()
        expected = Ready("child", run.run_id, "https://127.0.0.1:1", "http-v2")
        with redirect_stdout(io.StringIO()), run:
            run.ready(expected, lambda: True, lambda: expected)
        self.assertEqual(run.record["outcome"], "passed")
        self.assertEqual(run.record["evidenceKind"], "synthetic-process-contract")

    def test_failure_record_retains_child_signal_despite_successful_teardown(self):
        run = self.run_context(secrets=("do-not-publish",))
        child = Result(-signal.SIGABRT, b"token=do-not-publish\nfixture /private/home/secret\n", 10, 9, 2, 3, 2, True)
        with redirect_stdout(io.StringIO()), self.assertRaises(ProcessFailure), run:
            run.mark("execution")
            run.observe(child)
            run.cleanup.append(lambda: run.observe(Result(0, b"cleanup done", cleaned=True)))
            raise ProcessFailure("assertion-failure", "child-crash", child)
        record = json.loads(run.record_path.read_text())
        self.assertEqual(record["child"]["signal"], signal.SIGABRT)
        self.assertIsNone(record["child"]["exit"])
        self.assertEqual(record["stage"], "execution")
        self.assertNotIn("do-not-publish", json.dumps(record))
        self.assertNotIn("/private", json.dumps(record))
        self.assertLessEqual(len(record["logTail"]), 4096)
        self.assertEqual(record["startupMs"], 2)
        self.assertEqual(record["teardownMs"], 3)
        self.assertIn("teardown", [part["stage"] for part in record["timings"]])

    def test_cleanup_failure_cannot_pass(self):
        run = self.run_context()
        called = []
        def fail():
            raise RuntimeError("private detail")
        with redirect_stdout(io.StringIO()), self.assertRaises(ProcessFailure), run:
            run.cleanup.extend([lambda: called.append(True), fail])
        self.assertEqual(called, [True])
        self.assertEqual(run.record["outcome"], "failed")
        self.assertEqual(run.record["reason"], "fixture-cleanup-unconfirmed")
        self.assertNotIn("private detail", run.record_path.read_text())

    def test_arbitrary_commands_cannot_be_reproduction_selections(self):
        for reproduction in ({"command": "rm -rf"}, {"suite": "a;sh"}, {"cases": ["/private/path"]}, {"token": "secret"}):
            with self.assertRaises(ProcessFailure):
                self.run_context(reproduction=reproduction)

    def test_redaction_before_tail_protects_credentials_and_paths(self):
        content = 'Authorization: Bearer abc\nCookie: foo=xyz\npassword="many words"\nsecret=shh\n' \
                  'https://user:secret@127.0.0.1:443/private\nC:\\Users\\private\\key\n/home/private/key\n' \
                  '-----BEGIN PRIVATE KEY-----\nabc\n-----END PRIVATE KEY-----\n'
        safe = redact(content)
        for forbidden in ("abc", "xyz", "many words", "shh", "user:secret", "Users", "home/private"):
            self.assertNotIn(forbidden, safe)

    def test_parallel_roots_and_diagnostics_do_not_delete_each_other(self):
        a, b = self.run_context(), self.run_context()
        sentinel = b.root / "keep"
        sentinel.write_text("owned by b")
        with redirect_stdout(io.StringIO()), a:
            pass
        self.assertTrue(sentinel.exists())
        with redirect_stdout(io.StringIO()), b:
            pass
        self.assertNotEqual(a.record_path, b.record_path)
        self.assertTrue(a.record_path.exists())

    def test_total_watchdog_interrupts_stalled_python_stage(self):
        run = TestRun("synthetic-watchdog", policy(timeoutSeconds=0.2), synthetic=True, diagnostic_root=self.root)
        with redirect_stdout(io.StringIO()), self.assertRaises(ProcessFailure), run:
            run.mark("readiness")
            threading.Event().wait(2)
        self.assertEqual(run.record["reason"], "total-run-watchdog")
        self.assertLess(run.record["elapsedMs"], 1000)

    def test_invalid_limits_and_unsupported_owner(self):
        for timeout in (0, -1, float("inf"), float("nan")):
            with self.assertRaises(ValueError):
                run_owned(["unused"], cwd=ROOT, timeout=timeout)
        with patch("tools.owned_test_process.sys.platform", "darwin"), self.assertRaises(ProcessFailure) as error:
            run_owned(["unused"], cwd=ROOT)
        self.assertEqual(error.exception.category, "unavailable-environment")


class NativeOwnershipTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        available = sys.platform == "linux" and Path(f"/proc/self/task/{os.getpid()}/children").is_file()
        if not available:
            if os.environ.get("LSF_REQUIRE_NATIVE_PROCESS_TESTS") == "1":
                raise AssertionError("required native descendant accounting unavailable; no qualification ran")
            raise unittest.SkipTest("native descendant accounting unavailable; not passing ownership coverage")

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.addCleanup(self.temp.cleanup)

    def execute(self, code, **kwargs):
        return run_owned([sys.executable, "-I", "-c", code], cwd=self.root, timeout=kwargs.pop("timeout", 5), **kwargs)

    def assert_retired(self, pid):
        with self.assertRaises(ProcessLookupError):
            os.kill(pid, 0)

    def checkpoint(self, path, future):
        deadline = time.monotonic() + 4
        while time.monotonic() < deadline:
            if path.exists():
                value = json.loads(path.read_text())
                self.assertEqual(value["nonce"], self.root.name)
                return value
            if future.done():
                future.result()
                self.fail("owner returned without fresh readiness")
            time.sleep(0.005)
        self.fail("synthetic child never published readiness")

    def test_success_reaps_process(self):
        result = self.execute("print('hello')")
        self.assertEqual(result.output, b"hello\n")
        self.assertEqual(result.returncode, 0)
        self.assertTrue(result.cleaned)
        self.assert_retired(result.pid)

    def test_child_crash_is_not_timeout(self):
        result = self.execute("import resource,os; resource.setrlimit(resource.RLIMIT_CORE,(0,0)); os.abort()")
        self.assertEqual(result.returncode, -signal.SIGABRT)
        self.assertTrue(result.cleaned)
        self.assert_retired(result.pid)

    def test_inherited_pipe_writers_and_session_escape_are_reaped(self):
        for escape in (False, True):
            code = f"""import os,time
pid=os.fork()
if pid == 0:
    if {escape!r}: os.setsid()
    time.sleep(60)
else:
    print(pid, flush=True)
"""
            result = self.execute(code)
            self.assertEqual(result.returncode, 0)
            self.assertTrue(result.cleaned)
            self.assertGreaterEqual(result.reaped, 1)
            self.assert_retired(int(result.output))

    def test_double_forked_session_escape_is_adopted_and_reaped(self):
        result = self.execute("""import os,time
first=os.fork()
if first == 0:
    os.setsid()
    grandchild=os.fork()
    if grandchild == 0:
        print(os.getpid(),flush=True)
        time.sleep(60)
    else:
        os._exit(0)
else:
    os.waitpid(first,0)
    time.sleep(.05)
""")
        self.assertTrue(result.cleaned)
        self.assertGreaterEqual(result.reaped,1)
        self.assert_retired(int(result.output))

    def test_closed_stdout_does_not_cancel_lifetime_watchdog(self):
        with self.assertRaises(ProcessFailure) as error:
            self.execute("import os,time; os.close(1); os.close(2); time.sleep(60)", timeout=2)
        self.assertEqual(error.exception.category, "infrastructure-timeout")
        self.assertTrue(error.exception.result.cleaned)
        self.assert_retired(error.exception.result.pid)

    def test_output_overflow_is_bounded_and_reaped(self):
        with self.assertRaises(ProcessFailure) as error:
            self.execute("import os;\nwhile True: os.write(1,b'x'*65536)", maximum=1024)
        self.assertEqual(error.exception.category, "output-overflow")
        self.assertEqual(len(error.exception.result.output), 1024)
        self.assertTrue(error.exception.result.cleaned)
        self.assert_retired(error.exception.result.pid)

    def test_missing_executable_cannot_pass(self):
        with self.assertRaises(ProcessFailure) as error:
            run_owned([str(self.root / "missing")], cwd=self.root, timeout=5)
        self.assertEqual(error.exception.category, "unavailable-environment")
        self.assertIsNone(error.exception.result.returncode)

    def test_event_cancelled_waiter_retires_owned_children_only(self):
        import concurrent.futures
        signal_file = self.root / "ready.json"
        code = f"import os,json,time; from pathlib import Path; p=Path({str(signal_file)!r}); t=p.with_suffix('.tmp'); t.write_text(json.dumps(dict(pid=os.getpid(),nonce={self.root.name!r}))); t.replace(p); time.sleep(60)"
        other = subprocess.Popen([sys.executable, "-I", "-c", "import time; time.sleep(60)"])
        self.addCleanup(other.wait)
        self.addCleanup(other.kill)
        cancel = threading.Event()
        with concurrent.futures.ThreadPoolExecutor() as pool:
            future = pool.submit(self.execute, code, cancel=cancel)
            record = self.checkpoint(signal_file, future)
            cancel.set()
            with self.assertRaises(ProcessFailure) as error:
                future.result(timeout=5)
        self.assertEqual(error.exception.category, "cancelled")
        self.assertTrue(error.exception.result.cleaned)
        self.assert_retired(record["pid"])
        self.assertIsNone(other.poll())

    def test_async_waiter_cancellation_joins_cleanup(self):
        signal_file = self.root / "ready.json"
        code = f"import os,json,time; from pathlib import Path; p=Path({str(signal_file)!r}); t=p.with_suffix('.tmp'); t.write_text(json.dumps(dict(pid=os.getpid(),nonce={self.root.name!r}))); t.replace(p); time.sleep(60)"
        async def scenario():
            task = asyncio.create_task(run_owned_async([sys.executable, "-I", "-c", code], cwd=self.root, timeout=5))
            deadline = time.monotonic() + 4
            while not signal_file.exists():
                if task.done():
                    await task
                    self.fail("missing child readiness")
                self.assertLess(time.monotonic(), deadline)
                await asyncio.sleep(0.005)
            pid = json.loads(signal_file.read_text())["pid"]
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
            self.assert_retired(pid)
        asyncio.run(scenario())


if __name__ == "__main__":
    unittest.main()
