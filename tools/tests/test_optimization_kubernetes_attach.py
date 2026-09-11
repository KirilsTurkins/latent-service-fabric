"""Real small Linux pipe/process tests; no Docker, Kubernetes, or guest work."""
from __future__ import annotations

import hashlib
import ctypes
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest

from tools.optimization_evidence.common import EvidenceError
from tools.optimization_kubernetes.attach import Attach


@unittest.skipUnless(sys.platform == "linux", "the owned kubectl pipe helper is Linux-only")
class KubernetesAttach(unittest.TestCase):
    def subreaper(self):
        libc = ctypes.CDLL(None, use_errno=True)
        libc.prctl.argtypes = [ctypes.c_int, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_ulong]
        value = ctypes.c_int()
        self.assertEqual(libc.prctl(37, ctypes.addressof(value), 0, 0, 0), 0)
        return value.value

    def open(self, directory, source):
        return Attach([sys.executable, "-u", "-c", source], Path(directory))

    def dispose(self, owner):
        if not owner.closed:
            owner.close(force=True)

    def test_consumed_protocol_lines_and_eof_produce_actual_reaped_receipt(self):
        source = "import sys\nprint('ready', flush=True)\nassert sys.stdin.readline() == 'quit\\n'\nprint('done', flush=True)\n"
        with tempfile.TemporaryDirectory() as directory:
            previous = self.subreaper()
            owner = self.open(directory, source)
            try:
                self.assertEqual(self.subreaper(), 1)
                self.assertEqual(os.getpgid(owner.child.pid), owner.child.pid)
                self.assertEqual(owner.next_line(timeout=2), b"ready\n")
                owner.send_line(b"quit\n")
                self.assertEqual(owner.next_line(timeout=2), b"done\n")
                receipt = owner.close()
                self.assertTrue(receipt["reaped"])
                self.assertTrue(receipt["output_closed"])
                self.assertFalse(receipt["forced_kill"])
                self.assertIsNone(receipt["failure"])
                self.assertEqual(receipt["exit_code"], 0)
                self.assertEqual(receipt["subreaper"], {"previous": previous, "enabled": True, "restored": True})
                self.assertEqual(self.subreaper(), previous)
                self.assertTrue(receipt["process_group_gone"])
                self.assertEqual(receipt["descendant_reaps"], [])
                self.assertEqual(receipt["process_id"], owner.child.pid)
                self.assertGreater(int(receipt["start_time_ticks"]), 0)
                for role, data in (("stdout", b"ready\ndone\n"), ("stderr", b""), ("stdin", b"quit\n")):
                    self.assertEqual(receipt["streams"][role], {"bytes": str(len(data)),
                        "sha256": "sha256:" + hashlib.sha256(data).hexdigest()})
                self.assertEqual((Path(directory) / "attach-stdout.ndjson").read_bytes(), b"ready\ndone\n")
                self.assertIs(owner.close(), receipt)
            finally:
                self.dispose(owner)

    def test_pipe_eof_before_waitable_exit_uses_remaining_grace(self):
        source = ("import os,sys,time\nprint('ready', flush=True)\nsys.stdin.readline()\n"
                  "os.close(1)\nos.close(2)\ntime.sleep(0.15)\nos._exit(0)\n")
        with tempfile.TemporaryDirectory() as directory:
            owner = self.open(directory, source)
            try:
                self.assertEqual(owner.next_line(timeout=2), b"ready\n")
                owner.send_line(b"quit\n")
                receipt = owner.close()
                self.assertEqual(receipt["exit_code"], 0)
                self.assertFalse(receipt["forced_kill"])
                self.assertTrue(receipt["reaped"])
            finally:
                self.dispose(owner)

    def test_failed_spawn_restores_original_subreaper_state(self):
        with tempfile.TemporaryDirectory() as directory:
            previous = self.subreaper()
            with self.assertRaises(FileNotFoundError):
                Attach([str(Path(directory) / "absent-executable")], Path(directory))
            self.assertEqual(self.subreaper(), previous)

    def test_read_deadline_then_explicit_force_reaps_original_helper(self):
        source = "import sys,time\nprint('ready', flush=True)\ntime.sleep(60)\n"
        with tempfile.TemporaryDirectory() as directory:
            owner = self.open(directory, source)
            try:
                self.assertEqual(owner.next_line(timeout=2), b"ready\n")
                started = time.monotonic()
                with self.assertRaisesRegex(EvidenceError, "read-deadline"):
                    owner.next_line(timeout=0.05)
                self.assertLess(time.monotonic() - started, 2)
                receipt = owner.close(force=True)
                self.assertTrue(receipt["forced_kill"])
                self.assertTrue(receipt["reaped"])
                self.assertEqual(receipt["exit_code"], -9)
                self.assertIsNotNone(owner.child.returncode)
            finally:
                self.dispose(owner)

    def test_unconsumed_partial_or_complete_tail_cannot_claim_clean_close(self):
        for tail in ("partial", "extra\\n"):
            with self.subTest(tail=tail), tempfile.TemporaryDirectory() as directory:
                source = ("import sys\nprint('ready', flush=True)\nsys.stdin.readline()\n"
                          "sys.stdout.write('" + tail + "')\nsys.stdout.flush()\n")
                owner = self.open(directory, source)
                try:
                    self.assertEqual(owner.next_line(timeout=2), b"ready\n")
                    owner.send_line(b"quit\n")
                    with self.assertRaises(EvidenceError):
                        owner.close()
                    self.assertTrue(owner.receipt["reaped"])
                    self.assertIsNotNone(owner.receipt["failure"])
                    retained = (Path(directory) / "attach-stdout.ndjson").read_bytes()
                    self.assertEqual(retained, b"ready\n" + (b"partial" if tail == "partial" else b"extra\n"))
                    self.assertEqual(owner.receipt["streams"]["stdout"]["bytes"], str(len(retained)))
                finally:
                    self.dispose(owner)

    def test_forced_cleanup_kills_descendant_holding_output_pipe(self):
        source = ("import json,os,subprocess,sys,time\n"
                  "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])\n"
                  "print(json.dumps({'parent': os.getpid(), 'child': child.pid}), flush=True)\n"
                  "time.sleep(60)\n")
        with tempfile.TemporaryDirectory() as directory:
            owner = self.open(directory, source)
            unrelated = None
            try:
                identities = json.loads(owner.next_line(timeout=2))
                self.assertEqual(identities["parent"], owner.child.pid)
                self.assertEqual(os.getpgid(identities["child"]), owner.child.pid)
                unrelated = subprocess.Popen([sys.executable, "-c", "pass"], start_new_session=True,
                                             stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                until = time.monotonic() + 2
                while os.waitid(os.P_PID, unrelated.pid, os.WEXITED | os.WNOHANG | os.WNOWAIT) is None:
                    self.assertLess(time.monotonic(), until)
                    time.sleep(0.01)
                receipt = owner.close(force=True)
                self.assertTrue(receipt["reaped"])
                self.assertTrue(receipt["forced_kill"])
                self.assertTrue(receipt["output_closed"])
                path = Path("/proc") / str(identities["child"]) / "stat"
                self.assertFalse(path.exists())
                self.assertTrue(receipt["process_group_gone"])
                self.assertEqual([row["process_id"] for row in receipt["descendant_reaps"]], [identities["child"]])
                self.assertEqual(receipt["descendant_reaps"][0]["exit_code"], -9)
                self.assertTrue(receipt["subreaper"]["restored"])
                # A wait on the collector's unrelated child must remain ours.
                self.assertIsNotNone(os.waitid(os.P_PID, unrelated.pid, os.WEXITED | os.WNOHANG | os.WNOWAIT))
            finally:
                self.dispose(owner)
                if unrelated is not None:
                    unrelated.wait(timeout=5)


if __name__ == "__main__":
    unittest.main()
