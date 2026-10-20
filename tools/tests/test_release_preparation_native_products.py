"""Pin selection and CLI bootstrap controls; the shared reader owns its adversarial controls."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from tools import release_preparation_native_products as native
from tools import wasmtime_48_0_7_native_products as historical
from tools.rust_capsule_project import ROOT


class ReleasePreparationNativeProducts(unittest.TestCase):
    def test_frozen_tuple_agrees_with_independently_verified_public_evidence(self):
        evidence = json.loads((ROOT/'docs/testing/evidence/release-preparation-native-2026-10-21.json').read_bytes())
        self.assertEqual((native.SOURCE, native.RUN, native.JOB),
            (evidence['sourceRevision'], evidence['run'], evidence['job']))
        self.assertEqual(native.ARTIFACT, {'id': evidence['artifact']['id'],
            'size_in_bytes': evidence['artifact']['bytes'], 'digest': evidence['artifact']['sha256']})
        self.assertEqual(native.RECEIPTS, evidence['receipts'])
        self.assertEqual(evidence['rustControlsPassed'], 49)
        self.assertEqual(evidence['pythonControlsPassed'], 15)
        self.assertIs(evidence['signedGuestQualification'], False)

    def test_protocol_selection_and_twenty_stages_do_not_change_historical_tuple(self):
        self.assertIs(native.READER.include_protocol, True)
        self.assertEqual(native.READER.event, 'workflow_dispatch')
        self.assertEqual(native.STAGES[:12], historical.STAGES)
        self.assertEqual(len(native.STAGES), 20)
        self.assertEqual(native.STAGES[-1], 'release-preparation-command-name-controls')
        self.assertIs(historical.READER.include_protocol, False)
        self.assertEqual(historical.SOURCE, 'fc9b44a6b8dce9effd6b490f1a169a7ad8edbf12')
        self.assertNotEqual(native.READER.receipts, historical.READER.receipts)

    def test_direct_cli_bootstraps_without_pythonpath_or_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            result = subprocess.run([sys.executable, '-B', str(Path(native.__file__)), '--help'],
                cwd=temporary, env={**os.environ, 'PYTHONPATH': ''}, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr.decode())
            self.assertIn(b'--output', result.stdout)
            self.assertEqual(list(Path(temporary).iterdir()), [])
