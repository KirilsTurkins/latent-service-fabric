"""The immutable v7 origin is a native-only result, separate from old tuples."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from tools import host_codec_linear_memory_native_products as owner
from tools import host_codec_native_products as previous
from tools.host_codec_linear_memory_native_products_reader import FrozenHostCodecLinearMemoryProducts
from tools.rust_capsule_project import ROOT
from tools.sdk_native_products_reader import PRODUCTS


class HostCodecLinearMemoryNativeProducts(unittest.TestCase):
    def test_fixed_tuple_matches_whole_authenticated_archive_and_its_finite_native_only_scope(self):
        proof = json.loads((ROOT / 'docs/testing/evidence/host-codec-retained-context-native-2026-10-22.json').read_bytes())
        origin = proof['origin']
        self.assertEqual((owner.SOURCE, owner.RUN, owner.JOB),
            (proof['sourceRevision'], origin['run'], origin['job']))
        self.assertEqual(owner.ARTIFACT, {'id': origin['artifact'],
            'size_in_bytes': origin['archiveBytes'], 'digest': origin['archiveSha256']})
        self.assertEqual(owner.RECEIPTS, {
            'native-products.json': {'sha256': origin['receiptSha256'], 'bytes': origin['receiptBytes']},
            'source-inputs.json': {'sha256': origin['sourceInputsSha256'], 'bytes': origin['sourceInputsBytes']}})
        self.assertEqual((origin['archiveMembers'], origin['expandedBytes'], proof['source']['files'],
            proof['source']['bytes'], proof['recipeAndAuxiliaryMaterials'], proof['commandCount'],
            proof['verifiedLogStreamHashes'], proof['controlCount']),
            (111, 325242056, 3622, 31499697, 148, 51, 102, 114))
        self.assertEqual((proof['nativeCohort'], proof['scope']), (owner.READER.cohort, owner.READER.scope))
        self.assertEqual(proof['controlGroups'], {stage: len(cases) for stage, _, _, cases in owner.READER.controls})
        self.assertEqual(set(proof['products']), set(PRODUCTS))
        for name in ('signedQualification', 'guestSourceCompiled', 'historicalReceiptsRewritten'):
            self.assertIs(proof['limitations'][name], False)

    def test_exact_v7_origin_and_complete_old_selector_prefix_preserve_original_v1_pins(self):
        self.assertIs(type(owner.READER), FrozenHostCodecLinearMemoryProducts)
        self.assertEqual((owner.READER.control_count, len(owner.READER.stages)), (114, 51))
        self.assertEqual(owner.READER.controls[:14], previous.READER.controls)
        self.assertEqual(owner.READER.recipe, previous.READER.recipe)
        self.assertEqual(owner.READER.branch, 'feat/linear-memory-notifications-20261022')
        self.assertEqual(owner.READER.event, 'push')
        self.assertEqual(previous.SOURCE, '7b6365ee39dea9770591a931b96711965f8a1aaf')
        self.assertEqual(previous.ARTIFACT['id'], 12386352515)
        self.assertNotEqual(previous.RECEIPTS, owner.RECEIPTS)
        self.assertIs(owner.READER.include_protocol, True)

    def test_cli_help_outside_checkout_creates_no_output_or_pythonpath_requirement(self):
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run([sys.executable, '-B', str(Path(owner.__file__)), '--help'],
                cwd=directory, env={**os.environ, 'PYTHONPATH': ''}, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr.decode())
            self.assertIn(b'--output', result.stdout)
            self.assertEqual(list(Path(directory).iterdir()), [])


if __name__ == '__main__':
    unittest.main()
