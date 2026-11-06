"""Verify the sealed C input uses the existing bounded process owner."""
from pathlib import Path
import hashlib
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

from tools import build_process


class JavaOwnedCInput(unittest.TestCase):
    def environment(self):
        result = {'PATH': os.defpath}
        if os.name == 'nt':
            for name in ('SystemRoot', 'WINDIR', 'TEMP', 'TMP'):
                if name in os.environ:
                    result[name] = os.environ[name]
        return result

    def run_input(self, code, payload, *, timeout=30, maximum=4096, input_limit=16 * 1024 * 1024):
        return build_process.run_bounded_input_result(
            [sys.executable, '-B', '-c', code], Path.cwd(), self.environment(), timeout,
            maximum, payload, max_input_bytes=input_limit)

    def test_exact_binary_input_is_rewound_and_handle_closed(self):
        payload = bytes(range(256)) * 4096
        opened = []
        original = tempfile.TemporaryFile

        def tracked(*args, **kwargs):
            result = original(*args, **kwargs)
            opened.append(result)
            return result

        with patch.object(build_process.tempfile, 'TemporaryFile', side_effect=tracked):
            result = self.run_input('import sys,hashlib; b=sys.stdin.buffer.read(); '
                                    'print(str(len(b))+":"+hashlib.sha256(b).hexdigest())', payload)
        self.assertEqual(result.stdout.decode().strip(), f'{len(payload)}:{hashlib.sha256(payload).hexdigest()}')
        self.assertEqual(len(opened), 1)
        self.assertTrue(opened[0].closed)

    def test_oversize_is_refused_before_spawn(self):
        with patch.object(build_process, '_new_owner', side_effect=AssertionError('spawned')):
            with self.assertRaisesRegex(build_process.BuildProcessError, 'command-input-limit'):
                self.run_input('pass', b'x' * 33, input_limit=32)

    def test_timeout_closes_input_and_cleans_up(self):
        opened = []
        original = tempfile.TemporaryFile

        def tracked(*args, **kwargs):
            result = original(*args, **kwargs)
            opened.append(result)
            return result

        with patch.object(build_process.tempfile, 'TemporaryFile', side_effect=tracked):
            with self.assertRaisesRegex(build_process.BuildProcessError, 'command-deadline'):
                self.run_input('import time; time.sleep(20)', b'payload', timeout=.25)
        self.assertEqual(len(opened), 1)
        self.assertTrue(opened[0].closed)


if __name__ == '__main__':
    unittest.main()
