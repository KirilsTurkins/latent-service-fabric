"""The new immutable source tuple leaves every historical tuple intact."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from tools import activation_stack_native_products as native
from tools import c_thread_native_products as historical
from tools.rust_capsule_project import ROOT


class ActivationStackNativeProducts(unittest.TestCase):
    def test_exact_tuple_matches_the_authenticated_whole_archive_and_real_controls(self):
        proof = json.loads((ROOT / 'docs/testing/evidence/activation-stack-native-2026-10-21.json').read_bytes())
        self.assertEqual((native.SOURCE, native.RUN, native.JOB),
                         (proof['source'], proof['run'], proof['job']))
        self.assertEqual(native.ARTIFACT, proof['artifact'])
        self.assertEqual(native.RECEIPTS, proof['receipts'])
        self.assertEqual((proof['members'], proof['nativeSource']['files'], proof['auxiliaryGitRows']),
                         (75, 3325, 134))
        self.assertEqual((proof['originalRustPassed'], proof['cThreadingRustPassed'],
                          proof['cExactRustPassed'], proof['ordinaryWorkerRustPassed'], proof['pythonPassed']),
                         (50, 60, 11, 11, 16))
        self.assertEqual(proof['totalRustPassed'], 132)
        self.assertTrue(proof['wholeArchiveDigestVerified'])
        self.assertTrue(proof['allMemberCrcAndShaVerified'])
        for key in ('signedGuestQualification', 'cLifecycleGuestQualified',
                    'typescriptRootOnlyGuestQualified', 'rustHttpGuestQualified', 'historicalF0Repinned'):
            with self.subTest(key=key):
                self.assertIs(proof[key], False)

    def test_thirty_four_stages_preserve_the_original_f0_tuple_and_exact_order(self):
        self.assertEqual(native.STAGES, historical.STAGES + ('ordinary-async-worker-owner-controls',))
        self.assertEqual(len(native.STAGES), 34)
        self.assertEqual(native.READER.branch, 'diag/activation-stack-native-products-20261021')
        self.assertEqual(native.READER.event, 'workflow_dispatch')
        self.assertIs(native.READER.include_protocol, True)
        self.assertIs(type(native.READER), type(historical.READER))
        self.assertEqual(historical.SOURCE, 'f0d36b38d39a837cef7f6242b4b4a99aa36b8b75')
        self.assertEqual(historical.ARTIFACT['id'], 12338580939)
        self.assertNotEqual(native.RECEIPTS, historical.RECEIPTS)

    def test_cli_help_works_outside_the_checkout_without_output_or_pythonpath(self):
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run([sys.executable, '-B', str(Path(native.__file__)), '--help'],
                cwd=directory, env={**os.environ, 'PYTHONPATH': ''}, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr.decode())
            self.assertIn(b'--output', result.stdout)
            self.assertEqual(list(Path(directory).iterdir()), [])


if __name__ == '__main__':
    unittest.main()
