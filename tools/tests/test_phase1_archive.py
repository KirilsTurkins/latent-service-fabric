import gzip
import hashlib
import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import patch

from tools import package_phase1_evidence as package
from tools import validate_phase1_archive as verify


class ArchiveTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='phase1-archive-test-')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.source = self.root / 'source'
        self.source.mkdir()
        for name in ('aggregate.json', 'comparison.json'):
            (self.source / name).write_bytes(b'{}\n')
        (self.source / 'collector').write_bytes(b'bounded binary bytes\x00')
        self.policy = self.root / 'policy.json'
        self.policy.write_bytes(b'{}\n')
        self.output = self.root / 'package'
        self.output.mkdir()
        package.create_archive(self.source, self.output, self.policy)

    def rehash_archive(self, raw):
        (self.output / verify.ARCHIVE).write_bytes(raw)
        path = self.output / verify.MANIFEST
        manifest = json.loads(path.read_text())
        manifest['archive'] = verify.file_reference(self.output / verify.ARCHIVE, self.output)
        path.write_text(json.dumps(manifest))
        (self.output / (verify.ARCHIVE + '.sha256')).write_text(
            hashlib.sha256(raw).hexdigest() + '  ' + verify.ARCHIVE + '\n')

    def members(self, kind=tarfile.REGTYPE, name='collector', duplicate=False):
        stream = io.BytesIO()
        with tarfile.open(fileobj=stream, mode='w', format=tarfile.USTAR_FORMAT) as archive:
            for row in json.loads((self.output / verify.MANIFEST).read_text())['files']:
                data = self.policy.read_bytes() if row['path'] == 'measurement-policy.json' else (self.source / row['path']).read_bytes()
                info = tarfile.TarInfo(name if row['path'] == 'collector' else row['path'])
                info.type = kind if row['path'] == 'collector' else tarfile.REGTYPE
                info.size = len(data) if info.isfile() else 0
                info.linkname = 'aggregate.json' if info.islnk() or info.issym() else ''
                archive.addfile(info, io.BytesIO(data) if info.isfile() else None)
                if duplicate and row['path'] == 'collector':
                    archive.addfile(info, io.BytesIO(data))
        return gzip.compress(stream.getvalue(), mtime=0)

    def test_round_trip_preserves_every_byte_and_does_not_edit_source(self):
        before = {p.name: p.read_bytes() for p in self.source.iterdir()}
        manifest = verify.verify_package(self.output, replay=False)
        self.assertEqual(len(manifest['files']), 4)
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.source.iterdir()})

    def test_archive_is_reproducible_without_source_mtime(self):
        second = self.root / 'second'
        second.mkdir()
        package.create_archive(self.source, second, self.policy)
        self.assertEqual((self.output / verify.ARCHIVE).read_bytes(), (second / verify.ARCHIVE).read_bytes())

    def test_rejects_tampered_archive_checksum(self):
        with (self.output / verify.ARCHIVE).open('ab') as stream:
            stream.write(b'changed')
        with self.assertRaises(ValueError):
            verify.verify_package(self.output, replay=False)

    def test_rejects_outer_copy_diverging_from_archived_bytes(self):
        (self.output / 'aggregate.json').write_bytes(b'{"forged":true}')
        with self.assertRaises(ValueError):
            verify.verify_package(self.output, replay=False)

    def test_rejects_links_devices_and_traversal_before_extraction(self):
        for kind, name in ((tarfile.SYMTYPE, 'collector'), (tarfile.LNKTYPE, 'collector'),
                           (tarfile.FIFOTYPE, 'collector'), (tarfile.REGTYPE, '../escape'),
                           (tarfile.REGTYPE, 'C:/escape')):
            with self.subTest(kind=kind, name=name):
                self.rehash_archive(self.members(kind, name))
                with self.assertRaises(ValueError):
                    verify.verify_package(self.output, replay=False)
        self.assertFalse((self.root / 'escape').exists())

    def test_rejects_duplicate_members(self):
        self.rehash_archive(self.members(duplicate=True))
        with self.assertRaises(ValueError):
            verify.verify_package(self.output, replay=False)

    def test_rejects_rehashed_payload_corruption(self):
        raw = gzip.decompress((self.output / verify.ARCHIVE).read_bytes()).replace(b'bounded binary bytes', b'corrupt binary bytes')
        self.rehash_archive(gzip.compress(raw))
        with self.assertRaises(ValueError):
            verify.verify_package(self.output, replay=False)

    def test_rejects_data_after_tar_end_and_truncated_gzip(self):
        original = (self.output / verify.ARCHIVE).read_bytes()
        self.rehash_archive(gzip.compress(gzip.decompress(original) + b'X' * 512))
        with self.assertRaises(ValueError):
            verify.verify_package(self.output, replay=False)
        self.rehash_archive(original[:-4])
        with self.assertRaises((ValueError, EOFError, OSError)):
            verify.verify_package(self.output, replay=False)

    def test_rejects_large_pax_header_without_reading_its_body(self):
        header = tarfile.TarInfo('collector')
        header.type = tarfile.XHDTYPE
        header.size = 1024 * 1024 * 1024
        self.rehash_archive(gzip.compress(header.tobuf(format=tarfile.USTAR_FORMAT) + b'\0' * 1024))
        with self.assertRaises(ValueError):
            verify.verify_package(self.output, replay=False)

    def test_manifest_capacity_and_duplicate_fields_fail(self):
        with patch.object(verify, 'MAX_EXPANDED', 8):
            with self.assertRaises(ValueError):
                verify.verify_package(self.output, replay=False)
        manifest = self.output / verify.MANIFEST
        manifest.write_text('{"schema":"first","schema":"second"}')
        with self.assertRaises(ValueError):
            verify.verify_package(self.output, replay=False)

    def test_failed_replay_never_publishes_package(self):
        destination = self.root / 'unpublished'
        with patch.object(package, 'verify_package', side_effect=ValueError('invalid evidence')):
            with self.assertRaises(ValueError):
                package.package(self.source, destination, self.policy)
        self.assertFalse(destination.exists())
        self.assertEqual((self.source / 'collector').read_bytes(), b'bounded binary bytes\x00')

    def test_policy_checks_recorded_document_and_canonical_digest(self):
        policy = {'version': 1, 'allowance': '64', 'label': 'μs'}
        encoded = json.dumps(policy, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()
        aggregate = {'policy': {'document': policy, 'sha256': 'sha256:' + hashlib.sha256(encoded).hexdigest()}}
        verify.verify_policy(policy, aggregate)
        with self.assertRaises(ValueError):
            verify.verify_policy({'version': 1, 'allowance': '65'}, aggregate)
        aggregate['policy']['sha256'] = 'sha256:' + '0' * 64
        with self.assertRaises(ValueError):
            verify.verify_policy(policy, aggregate)


if __name__ == '__main__':
    unittest.main()
