"""Immutable selected producer pins; no binary or guest execution."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from tools import c_thread_native_products as native
from tools import release_preparation_cli_native_products as historical
from tools.rust_capsule_project import ROOT


class CThreadNativeProducts(unittest.TestCase):
    def test_exact_tuple_agrees_with_whole_archive_git_and_real_control_observation(self):
        evidence = json.loads((ROOT / 'docs/testing/evidence/c-thread-native-2026-10-21.json').read_bytes())
        self.assertEqual((native.SOURCE, native.RUN, native.JOB),
                         (evidence['source'], evidence['run'], evidence['job']))
        self.assertEqual(native.ARTIFACT, evidence['artifact'])
        self.assertEqual(native.RECEIPTS, evidence['receipts'])
        self.assertEqual((evidence['members'], evidence['nativeSource']['files'], evidence['auxiliaryGitRows']),
                         (73, 3324, 134))
        self.assertEqual((evidence['originalRustPassed'], evidence['selectedRustPassed'], evidence['pythonPassed']),
                         (50, 66, 15))
        self.assertIs(evidence['signedGuestQualification'], False)
        self.assertIs(evidence['cLifecycleGuestQualified'], False)

    def test_exact_thirty_three_stages_leave_original_twenty_one_tuple_immutable(self):
        self.assertEqual(native.STAGES[:21], historical.STAGES)
        self.assertEqual(native.STAGES[21:], ('c-original-and-final-proof-controls',
                         *(f'c-profile-{index}' for index in range(1, 12))))
        self.assertEqual(len(native.STAGES), 33)
        self.assertEqual(native.READER.branch, 'feat/c-thread-native-profile-20261021')
        self.assertEqual(native.READER.event, 'workflow_dispatch')
        self.assertIs(native.READER.include_protocol, True)
        self.assertIs(type(native.READER), type(historical.READER))
        self.assertEqual(historical.SOURCE, '6fd19eab2c224fc31481d03de5008de4d3e4429e')
        self.assertNotEqual(native.RECEIPTS, historical.RECEIPTS)

    def test_cli_help_is_available_without_checkout_or_pythonpath_or_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            result = subprocess.run([sys.executable, '-B', str(Path(native.__file__)), '--help'],
                cwd=temporary, env={**os.environ, 'PYTHONPATH': ''}, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr.decode())
            self.assertIn(b'--output', result.stdout)
            self.assertEqual(list(Path(temporary).iterdir()), [])


if __name__ == '__main__':
    unittest.main()
