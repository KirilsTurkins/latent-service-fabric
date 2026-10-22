"""The immutable approved128 origin, without acquisition or product execution."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from tools import host_codec_owned_reply_native_products as fixed
from tools import sdk_native_products_reader as original
from tools.host_codec_owned_reply_native_products_reader import FrozenHostCodecOwnedReplyProducts
from tools.tests.test_host_codec_owned_reply_native_products_reader import model


class HostCodecOwnedReplyNativeProducts(unittest.TestCase):
    def test_frozen128_origin_is_the_independently_verified_complete_native_only_tuple(self):
        self.assertEqual((fixed.SOURCE, fixed.RUN, fixed.JOB),
            ('cb8ceefc5f6343301871dbde1d8a853d3581cc30', 39742557852, 119703099390))
        self.assertEqual(fixed.ARTIFACT, {'id': 12410348071, 'size_in_bytes': 70449703,
            'digest': 'sha256:a4bb2b98e8b338924b5462f338902ae65915625692969b60698fabcd8834a03a'})
        self.assertEqual(fixed.RECEIPTS, {
            'native-products.json': {'sha256': 'sha256:994e2c150e98491b1d263a67f049822c9439690f42d072703e84f080e6842a27', 'bytes': 94912},
            'source-inputs.json': {'sha256': 'sha256:fa47517b986e14009f52be786fef0b3e3e288fd80596f3986de56f0afe1c7d93', 'bytes': 24574}})
        self.assertIs(type(fixed.READER), FrozenHostCodecOwnedReplyProducts)
        self.assertEqual((fixed.READER.control_count, fixed.READER.command_count,
            len(fixed.READER.stages)), (128, 59, 59))
        self.assertEqual(fixed.READER._producer_origin(), ('.github/workflows/host-codec-memory.yml',
            'Original ledger closed context replies and runtime memory ownership diagnostics', 'host-codec-memory-'))
        self.assertEqual((fixed.READER.branch, fixed.READER.event, fixed.READER.include_protocol),
            ('feat/owned-context-replies-memory-20261022', 'push', True))

    def test_fixed_reader_uses_exact_source_contract_and_original_acquisition_methods(self):
        reader, record, snapshot, native, materials = model()
        self.assertEqual((fixed.READER.controls, fixed.READER.recipe, fixed.READER.stages),
            (reader.controls, reader.recipe, reader.stages))
        fixed.READER.validate_record(record, snapshot, native, materials)
        self.assertIs(fixed.prepare.__self__, fixed.READER)
        self.assertIs(fixed.verify_prepared.__self__, fixed.READER)
        self.assertIs(fixed.native_products.__self__, fixed.READER)
        for name in ('prepare', 'verify_prepared', 'extract', 'preflight'):
            self.assertIs(getattr(type(fixed.READER), name), getattr(original.FrozenNativeProducts, name))

    def test_cli_help_outside_checkout_has_no_output_side_effect_or_pythonpath_dependency(self):
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run([sys.executable, '-B', str(Path(fixed.__file__)), '--help'],
                cwd=directory, env={**os.environ, 'PYTHONPATH': ''}, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr.decode())
            self.assertIn(b'--output', result.stdout)
            self.assertEqual(list(Path(directory).iterdir()), [])


if __name__ == '__main__':
    unittest.main()
