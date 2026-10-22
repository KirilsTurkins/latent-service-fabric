"""The v2 fixed tuple is separate from the immutable v1 origin."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from tools import host_codec_native_products as previous
from tools import host_codec_table_store_native_products as owner
from tools.host_codec_table_store_native_products_reader import FrozenHostCodecTableStoreProducts
from tools.rust_capsule_project import ROOT


class HostCodecTableStoreNativeProducts(unittest.TestCase):
    def test_fixed_tuple_matches_whole_authenticated_archive_without_guest_claim(self):
        proof = json.loads((ROOT / 'docs/testing/evidence/host-codec-table-store-native-2026-10-22.json').read_bytes())
        origin = proof['origin']
        self.assertEqual((owner.SOURCE, owner.RUN, owner.JOB),
            (proof['sourceRevision'], origin['run'], origin['job']))
        self.assertEqual(owner.ARTIFACT, {'id': origin['artifact'],
            'size_in_bytes': origin['archiveBytes'], 'digest': origin['archiveSha256']})
        self.assertEqual(owner.RECEIPTS['native-products.json'],
            {'sha256': origin['receiptSha256'], 'bytes': origin['receiptBytes']})
        self.assertEqual(owner.RECEIPTS['source-inputs.json'],
            {'sha256': 'sha256:29151dda7d155cd1cc0db1de9820b179f2a94f248c24791b6f0ab0f91079c6af', 'bytes': 24573})
        self.assertEqual((origin['archiveMembers'], proof['source']['files'], proof['recipeAndAuxiliaryMaterials'],
            proof['commandCount'], proof['verifiedLogStreamHashes'], proof['controlCount']), (83, 3603, 148, 37, 74, 81))
        for name in ('signedQualification', 'guestSourceCompiled', 'historicalReceiptRewritten'):
            self.assertIs(proof[name], False)

    def test_exact_v2_origin_retains_complete_v1_control_prefix_and_all_old_pins(self):
        self.assertIs(type(owner.READER), FrozenHostCodecTableStoreProducts)
        self.assertEqual((owner.READER.control_count, len(owner.READER.stages)), (81, 37))
        self.assertEqual(owner.READER.controls[:14], previous.READER.controls)
        self.assertEqual(owner.READER.recipe, previous.READER.recipe)
        self.assertEqual(owner.READER.branch, 'feat/typescript-table-memory-20261022')
        self.assertEqual(owner.READER.event, 'push')
        self.assertEqual(previous.SOURCE, '7b6365ee39dea9770591a931b96711965f8a1aaf')
        self.assertEqual(previous.ARTIFACT['id'], 12386352515)
        self.assertNotEqual(previous.RECEIPTS, owner.RECEIPTS)
        self.assertIs(owner.READER.include_protocol, True)

    def test_cli_help_outside_checkout_does_not_create_output_or_need_pythonpath(self):
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run([sys.executable, '-B', str(Path(owner.__file__)), '--help'],
                cwd=directory, env={**os.environ, 'PYTHONPATH': ''}, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr.decode())
            self.assertIn(b'--output', result.stdout)
            self.assertEqual(list(Path(directory).iterdir()), [])


if __name__ == '__main__':
    unittest.main()
