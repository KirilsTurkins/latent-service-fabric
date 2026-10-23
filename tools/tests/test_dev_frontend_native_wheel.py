"""Pinned native-wheel attribution controls; metadata records are explicit doubles."""
import base64
import hashlib
from importlib.metadata import PackagePath
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from tools import dev_frontend_linux as frontend
from tools.dev_workflow.common import DevError


class NativeWheelOwner(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.source = Path(temporary.name).resolve() / 'extension.so'
        self.raw = b'PUBLIC-NATIVE-WHEEL-CONTROL'
        self.source.write_bytes(self.raw)
        self.checksum = 'sha256:' + hashlib.sha256(self.raw).hexdigest()
        self.entry = PackagePath('fixture/extension.so')
        self.entry.hash = SimpleNamespace(mode='sha256', value=base64.urlsafe_b64encode(
            hashlib.sha256(self.raw).digest()).rstrip(b'=').decode('ascii'))
        self.entry.size = len(self.raw)
        self.distribution = SimpleNamespace(version='1.2.3', files=[self.entry],
                                            locate_file=lambda entry: self.source)
        self.packages = [{'name': 'fixture-wheel', 'version': '1.2.3',
                          'wheelSha256': 'a' * 64, 'licenses': ['licenses/fixture/0-LICENSE']}]

    def owner(self):
        with patch('tools.dev_frontend_linux.importlib.metadata.distribution', return_value=self.distribution):
            return frontend.wheel_owner(self.source, self.checksum, self.packages)

    def test_exact_existing_inventory_record_attributes_original_native_bytes_and_version(self):
        self.assertEqual(self.owner(), 'fixture-wheel==1.2.3')
        self.assertEqual(self.source.read_bytes(), self.raw)

    def test_unknown_native_file_and_foreign_record_never_gain_directory_based_ownership(self):
        self.distribution.locate_file = lambda entry: self.source.parent / 'other.so'
        self.assertIsNone(self.owner())
        self.distribution.files = []
        self.assertIsNone(self.owner())

    def test_missing_changed_size_or_wrong_digest_record_refuses_without_general_fallback(self):
        original_hash = self.entry.hash
        for marker, size, expected in ((None, len(self.raw), 'record-required'),
                                     (original_hash, len(self.raw) + 1, 'record-required'),
                                     (SimpleNamespace(mode='sha512', value='a'), len(self.raw), 'record-required'),
                                     (SimpleNamespace(mode='sha256', value='a'), len(self.raw), 'record-digest-mismatch')):
            self.entry.hash, self.entry.size = marker, size
            with self.assertRaisesRegex(DevError, expected):
                self.owner()

    def test_changed_package_version_missing_license_and_ambiguous_record_refuse(self):
        self.distribution.version = '9.9.9'
        with self.assertRaisesRegex(DevError, 'version-changed'):
            self.owner()
        self.distribution.version = '1.2.3'
        self.packages[0]['licenses'] = []
        with self.assertRaisesRegex(DevError, 'inventory-required'):
            self.owner()
        self.packages[0]['licenses'] = ['licenses/fixture/0-LICENSE']
        self.packages.append(dict(self.packages[0]))
        with self.assertRaisesRegex(DevError, 'ambiguous-wheel-library-owner'):
            self.owner()


if __name__ == '__main__':
    unittest.main()
