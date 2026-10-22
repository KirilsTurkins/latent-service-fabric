"""The new immutable source tuple leaves every historical tuple intact."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from tools import c_thread_package_native_products as native
from tools import activation_stack_native_products as historical
from tools.rust_capsule_project import ROOT


class CThreadPackageNativeProducts(unittest.TestCase):
    def test_exact_tuple_matches_the_authenticated_whole_archive_and_real_controls(self):
        proof = json.loads((ROOT / 'docs/testing/evidence/c-thread-package-native-2026-10-21.json').read_bytes())
        self.assertEqual((native.SOURCE, native.RUN, native.JOB),
                         (proof['source'], proof['run'], proof['job']))
        self.assertEqual(native.ARTIFACT, proof['artifact'])
        self.assertEqual(native.RECEIPTS, proof['receipts'])
        self.assertEqual((proof['members'], proof['nativeSource']['files'], proof['auxiliaryGitRows']),
                         (77, 3325, 134))
        self.assertEqual((proof['commands'], proof['rustPassed'], proof['pythonPassed']), (35, 134, 16))
        self.assertEqual(proof['rustCommandCounts']['descriptive-native-thread-proof-controls'], 2)
        self.assertTrue(proof['wholeArchiveDigestVerified'])
        self.assertTrue(proof['allMemberCrcAndShaVerified'])
        for key in ('signedGuestQualification', 'cLifecycleGuestQualified', 'oldC713Repinned'):
            with self.subTest(key=key):
                self.assertIs(proof[key], False)

    def test_thirty_five_stages_preserve_the_original_c713_tuple_and_exact_order(self):
        self.assertEqual(native.STAGES, historical.STAGES[:6] + ('descriptive-native-thread-proof-controls',) + historical.STAGES[6:])
        self.assertEqual(len(native.STAGES), 35)
        self.assertEqual(native.READER.branch, 'diag/c-thread-package-native-products-20261021')
        self.assertEqual(native.READER.event, 'workflow_dispatch')
        self.assertIs(native.READER.include_protocol, True)
        self.assertIs(type(native.READER), type(historical.READER))
        self.assertEqual(historical.SOURCE, 'c7134289f446cb3171eb0ffd800a94afc2a5209f')
        self.assertEqual(historical.ARTIFACT['id'], 12345773653)
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
