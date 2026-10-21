"""Freeze a new current tuple without changing the historical CLI producer."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from tools import rust_http_installed_native_products as native
from tools import release_preparation_cli_native_products as historical
from tools.rust_capsule_project import ROOT


class InstalledHttpNativeProducts(unittest.TestCase):
    def test_exact_tuple_matches_whole_archive_and_git_review(self):
        evidence = json.loads((ROOT/'docs/testing/evidence/rust-http-installed-native-2026-10-21.json').read_bytes())
        self.assertEqual((native.SOURCE, native.RUN, native.JOB),
            (evidence['source'], evidence['run'], evidence['job']))
        self.assertEqual(native.ARTIFACT, evidence['artifact'])
        self.assertEqual(native.RECEIPTS, evidence['receipts'])
        self.assertEqual((evidence['members'], evidence['compiledNativeSource']['files'], evidence['auxiliaryGitRows']),
            (49, 3318, 134))
        self.assertEqual((evidence['rustPassed'], evidence['pythonPassed']), (50, 15))
        self.assertIs(evidence['signedRuntimeQualification'], False)

    def test_same_closed_algorithm_and_scope_leave_six_fd_tuple_immutable(self):
        self.assertEqual(native.STAGES, historical.STAGES)
        self.assertEqual(len(native.STAGES), 21)
        self.assertIs(native.READER.include_protocol, True)
        self.assertEqual(native.READER.event, 'workflow_dispatch')
        self.assertEqual(native.READER.branch, 'diag/sdk-native-installed-http-20261021')
        self.assertIs(type(native.READER), type(historical.READER))
        self.assertEqual(historical.SOURCE, '6fd19eab2c224fc31481d03de5008de4d3e4429e')
        self.assertNotEqual(native.READER.receipts, historical.READER.receipts)
        self.assertNotEqual(native.ARTIFACT, historical.ARTIFACT)

    def test_cli_bootstraps_without_checkout_or_pythonpath(self):
        with tempfile.TemporaryDirectory() as temporary:
            result = subprocess.run([sys.executable, '-B', str(Path(native.__file__)), '--help'],
                cwd=temporary, env={**os.environ, 'PYTHONPATH': ''}, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr.decode())
            self.assertIn(b'--output', result.stdout)
            self.assertEqual(list(Path(temporary).iterdir()), [])


if __name__ == '__main__':
    unittest.main()
