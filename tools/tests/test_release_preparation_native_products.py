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
        evidence = json.loads((ROOT/'docs/testing/evidence/release-preparation-cli-native-2026-10-21.json').read_bytes())
        self.assertEqual((native.SOURCE, native.RUN, native.JOB),
            (evidence['sourceRevision'], evidence['run'], evidence['job']))
        self.assertEqual(native.ARTIFACT, {'id': evidence['artifact']['id'],
            'size_in_bytes': evidence['artifact']['bytes'], 'digest': evidence['artifact']['sha256']})
        self.assertEqual(native.RECEIPTS, evidence['receipts'])
        self.assertEqual(evidence['rustControlsPassed'], 50)
        self.assertEqual(evidence['pythonControlsPassed'], 15)
        self.assertIs(evidence['signedGuestQualification'], False)

    def test_protocol_selection_and_twenty_stages_do_not_change_historical_tuple(self):
        self.assertIs(native.READER.include_protocol, True)
        self.assertEqual(native.READER.event, 'workflow_dispatch')
        self.assertEqual(native.STAGES[:12], historical.STAGES)
        self.assertEqual(len(native.STAGES), 21)
        self.assertEqual(native.STAGES[19], 'release-preparation-command-name-controls')
        self.assertEqual(native.STAGES[20], 'release-preparation-dispatch-controls')
        self.assertIs(historical.READER.include_protocol, False)
        self.assertEqual(historical.SOURCE, 'fc9b44a6b8dce9effd6b490f1a169a7ad8edbf12')
        self.assertNotEqual(native.READER.receipts, historical.READER.receipts)

    def test_original_successful_producer_and_failed_consumer_are_not_relabelled(self):
        original = json.loads((ROOT/'docs/testing/evidence/release-preparation-native-2026-10-21.json').read_bytes())
        current = json.loads((ROOT/'docs/testing/evidence/release-preparation-cli-native-2026-10-21.json').read_bytes())
        self.assertEqual(original['sourceRevision'], '21b2c84c74881701149115dd8511063c85800b47')
        self.assertEqual(original['rustControlsPassed'], 49)
        self.assertEqual(current['priorSuccessfulNativeSource'], original['sourceRevision'])
        self.assertEqual(current['priorSuccessfulNativeRun'], original['run'])
        self.assertEqual(current['priorFailedConsumerRun'], 39514296963)
        self.assertEqual(current['priorFailedConsumerJob'], 118942636746)
        self.assertEqual(current['priorFailedConsumerArtifact']['id'], 12307672432)
        self.assertNotEqual(native.READER.source, original['sourceRevision'])
        self.assertIs(current['signedGuestQualification'], False)

    def test_direct_cli_bootstraps_without_pythonpath_or_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            result = subprocess.run([sys.executable, '-B', str(Path(native.__file__)), '--help'],
                cwd=temporary, env={**os.environ, 'PYTHONPATH': ''}, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr.decode())
            self.assertIn(b'--output', result.stdout)
            self.assertEqual(list(Path(temporary).iterdir()), [])
