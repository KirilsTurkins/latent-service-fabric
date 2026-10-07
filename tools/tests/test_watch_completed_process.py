"""Real child completion/drain does not reenter an active source observer."""
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from tools import build_process
from tools.dev_workflow import process
from tools.dev_workflow.common import DevError


@unittest.skipUnless(sys.platform == 'linux', 'actual Linux process-group retirement')
class CompletedProcessObservation(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.owners = []
        factory = build_process._new_owner
        def capture_owner():
            value = factory()
            self.owners.append(value)
            return value
        self.factory = patch.object(build_process, '_new_owner', side_effect=capture_owner)
        self.factory.start()
        self.addCleanup(self.factory.stop)

    def invoke(self, *, check=None):
        return process.run([sys.executable, '-c', 'import sys; sys.stdout.write("cached-result")'],
                           self.root, timeout=3, maximum=4096, check=check, graceful=12)

    def assert_reaped(self):
        self.assertTrue(self.owners[0].finished)
        with self.assertRaises(ChildProcessError):
            os.waitpid(self.owners[0].process.pid, os.WNOHANG)

    def test_active_source_observer_is_not_called_during_already_reaped_output_drain(self):
        gate = self.root / 'released'
        checks = []
        def check():
            owner = self.owners[0]
            checks.append(owner.finished)
            if owner.finished:
                raise DevError('guest-build-superseded')
            gate.touch()
            deadline = time.monotonic() + 1
            while not owner.exited():
                self.assertLess(time.monotonic(), deadline)
                time.sleep(.001)
        child = 'import pathlib,sys,time; p=pathlib.Path(sys.argv[1]);\nwhile not p.exists(): time.sleep(.001)\nsys.stdout.write("cached-result"); sys.stdout.flush()\n'
        result = process.run([sys.executable, '-c', child, str(gate)], self.root,
                             timeout=3, maximum=4096, check=check, graceful=12)
        self.assertEqual((result.returncode, result.stdout), (0, b'cached-result'))
        self.assertEqual(checks, [False])
        self.assert_reaped()

    def test_running_source_failure_keeps_its_code_after_real_child_cleanup(self):
        def failed():
            raise DevError('guest-build-superseded')
        with self.assertRaises(DevError) as raised:
            self.invoke(check=failed)
        self.assertEqual(raised.exception.code, 'guest-build-superseded')
        self.assertFalse(raised.exception.uncertain)
        self.assert_reaped()

    def test_post_reap_failure_keeps_original_code_without_rechecking_reserved_pid(self):
        capture = build_process._capture
        def failed(owner, *args):
            capture(owner, *args)
            self.assertTrue(owner.finished)
            raise DevError('guest-build-superseded')
        with patch.object(build_process, '_capture', side_effect=failed):
            with self.assertRaises(DevError) as raised:
                self.invoke()
        self.assertEqual(raised.exception.code, 'guest-build-superseded')
        self.assertFalse(raised.exception.uncertain)
        self.assert_reaped()

    def test_post_reap_cancellation_stays_cancellation_without_cleanup_uncertainty(self):
        capture = build_process._capture
        def interrupted(owner, *args):
            capture(owner, *args)
            self.assertTrue(owner.finished)
            raise KeyboardInterrupt()
        with patch.object(build_process, '_capture', side_effect=interrupted):
            with self.assertRaises(KeyboardInterrupt):
                self.invoke()
        self.assert_reaped()
