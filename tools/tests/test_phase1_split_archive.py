import hashlib
import json
import unittest
from unittest.mock import patch

from tools import package_phase1_evidence as package
from tools import validate_phase1_archive as verify
from tools.tests import test_phase1_archive as fixtures


class SplitArchiveTests(unittest.TestCase):
    def setUp(self):
        fixtures.ArchiveTests.setUp(self)
        self.original = (self.output / verify.ARCHIVE).read_bytes()
        self.manifest = json.loads((self.output / verify.MANIFEST).read_bytes())
        package.write_split_archive(self.output, self.manifest['archive'])

    def parts(self):
        return json.loads((self.output / verify.PARTS_MANIFEST).read_bytes())

    def save_parts(self, value):
        (self.output / verify.PARTS_MANIFEST).write_text(json.dumps(value), encoding='utf-8')

    def test_round_trip_preserves_logical_archive_manifest_and_exact_gzip_bytes(self):
        self.assertFalse((self.output / verify.ARCHIVE).exists())
        parts = self.parts()
        self.assertEqual(len(parts['parts']), 2)
        self.assertEqual(parts['archive'], self.manifest['archive'])
        self.assertEqual(b''.join((self.output / row['path']).read_bytes() for row in parts['parts']),
                         self.original)
        self.assertEqual(verify.verify_package(self.output, replay=False), self.manifest)
        self.assertEqual((self.output / (verify.ARCHIVE + '.sha256')).read_text(),
                         hashlib.sha256(self.original).hexdigest() + '  ' + verify.ARCHIVE + '\n')

    def test_layout_has_fixed_upper_and_lower_bounds(self):
        for total, count in ((20, 2), (99_000_000, 2), (100_000_001, 3), (198_000_000, 4)):
            with self.subTest(total=total):
                layout = verify.split_layout(total)
                self.assertEqual(len(layout), count)
                self.assertEqual(sum(size for _, size in layout), total)
                self.assertTrue(all(0 < size <= 50_000_000 for _, size in layout))
        for total in (0, 19, 198_000_001):
            with self.assertRaises(ValueError):
                verify.split_layout(total)

    def test_three_and_four_part_streams_replay_with_scaled_test_chunk_limit(self):
        for count in (3, 4):
            destination = self.root / f'parts-{count}'
            destination.mkdir()
            with patch.object(verify, 'MAX_PART_BYTES', (len(self.original) + count - 1) // count):
                manifest = package.create_archive(self.source, destination, self.policy, split_archive=True)
                parts = json.loads((destination / verify.PARTS_MANIFEST).read_bytes())
                self.assertEqual(len(parts['parts']), count)
                self.assertEqual(verify.verify_package(destination, replay=False), manifest)

    def test_monolithic_cap_is_not_raised_by_split_transport(self):
        destination = self.root / 'monolithic'
        destination.mkdir()
        package.create_archive(self.source, destination, self.policy)
        with patch.object(verify, 'MAX_COMPRESSED', len(self.original) - 1):
            with self.assertRaisesRegex(ValueError, 'exceeds bound'):
                verify.verify_package(destination, replay=False)
            self.assertEqual(verify.verify_package(self.output, replay=False), self.manifest)

    def test_missing_extra_and_ambiguous_transport_files_fail(self):
        part = self.output / self.parts()['parts'][0]['path']
        raw = part.read_bytes()
        part.unlink()
        with self.assertRaises((ValueError, OSError)):
            verify.verify_package(self.output, replay=False)
        part.write_bytes(raw)
        for name in (verify.ARCHIVE, verify.ARCHIVE + '.part-0003',
                     verify.ARCHIVE.upper() + '.part-9999', verify.PARTS_MANIFEST + '.extra'):
            with self.subTest(name=name):
                path = self.output / name
                path.write_bytes(b'extra')
                try:
                    with self.assertRaisesRegex(ValueError, 'unexpected or ambiguous'):
                        verify.verify_package(self.output, replay=False)
                finally:
                    path.unlink()

    def test_split_parts_cannot_fall_back_to_monolithic_without_manifest(self):
        (self.output / verify.PARTS_MANIFEST).unlink()
        (self.output / verify.ARCHIVE).write_bytes(self.original)
        with self.assertRaisesRegex(ValueError, 'unexpected or ambiguous'):
            verify.verify_package(self.output, replay=False)

    def test_actual_case_alias_and_nonregular_part_are_rejected(self):
        path = self.output / self.parts()['parts'][0]['path']
        alias = path.with_name(path.name.upper())
        path.rename(alias)
        try:
            with self.assertRaisesRegex(ValueError, 'unexpected or ambiguous'):
                verify.verify_package(self.output, replay=False)
        finally:
            alias.rename(path)
        raw = path.read_bytes()
        path.unlink()
        path.mkdir()
        with self.assertRaises(ValueError):
            verify.verify_package(self.output, replay=False)
        path.rmdir()
        path.write_bytes(raw)

    def test_manifest_rejects_reordering_duplicates_paths_sizes_schema_and_count(self):
        original = self.parts()
        mutations = [
            lambda value: value['parts'].reverse(),
            lambda value: value['parts'].__setitem__(1, value['parts'][0]),
            lambda value: value['parts'][0].__setitem__('path', '../outside'),
            lambda value: value['parts'][0].__setitem__('bytes', '0'),
            lambda value: value['parts'][0].__setitem__('bytes', '99000001'),
            lambda value: value.__setitem__('schema', 'latent.phase1.archive-parts.v2'),
            lambda value: value['parts'].pop(),
            lambda value: value['parts'].extend(value['parts'] * 2),
        ]
        for mutate in mutations:
            value = json.loads(json.dumps(original))
            mutate(value)
            self.save_parts(value)
            with self.assertRaises(ValueError):
                verify.verify_package(self.output, replay=False)
        self.save_parts(original)
        with (self.output / verify.PARTS_MANIFEST).open('w') as stream:
            stream.write('{"schema":"first","schema":"second"}')
        with self.assertRaisesRegex(ValueError, 'duplicate'):
            verify.verify_package(self.output, replay=False)

    def test_split_total_bound_is_checked_before_reading_parts(self):
        for total in ('0', '19', '198000001'):
            value = self.parts()
            manifest = dict(self.manifest)
            manifest['archive'] = {**manifest['archive'], 'bytes': total}
            value['archive'] = manifest['archive']
            self.save_parts(value)
            (self.output / verify.MANIFEST).write_text(json.dumps(manifest))
            with self.assertRaisesRegex(ValueError, 'split archive compressed byte bound'):
                verify.verify_package(self.output, replay=False)

    def test_oversized_transport_manifest_is_rejected_before_json_parsing(self):
        (self.output / verify.PARTS_MANIFEST).write_bytes(b' ' * 8193)
        with self.assertRaisesRegex(ValueError, 'split manifest exceeds bound'):
            verify.verify_package(self.output, replay=False)

    def test_part_corruption_rehash_still_requires_whole_stream_identity(self):
        value = self.parts()
        path = self.output / value['parts'][0]['path']
        raw = bytearray(path.read_bytes())
        raw[0] ^= 1
        path.write_bytes(raw)
        with self.assertRaisesRegex(ValueError, 'split part checksum'):
            verify.verify_package(self.output, replay=False)
        value['parts'][0] = verify.file_reference(path, self.output)
        self.save_parts(value)
        with self.assertRaisesRegex(ValueError, 'split whole archive checksum'):
            verify.verify_package(self.output, replay=False)

    def test_symlink_part_is_rejected_even_when_target_bytes_match(self):
        path = self.output / self.parts()['parts'][0]['path']
        target = self.root / 'symlink-target'
        target.write_bytes(path.read_bytes())
        path.unlink()
        try:
            path.symlink_to(target)
        except OSError as error:
            self.skipTest(f'symlink creation unavailable: {error}')
        with self.assertRaises(ValueError):
            verify.verify_package(self.output, replay=False)

    def test_dangling_manifest_part_and_monolithic_symlinks_are_rejected(self):
        for name in (verify.PARTS_MANIFEST, self.parts()['parts'][0]['path'], verify.ARCHIVE):
            with self.subTest(name=name):
                path = self.output / name
                original = path.read_bytes() if path.exists() else None
                if original is not None:
                    path.unlink()
                try:
                    path.symlink_to(self.root / 'missing-target')
                except OSError as error:
                    if original is not None:
                        path.write_bytes(original)
                    self.skipTest(f'symlink creation unavailable: {error}')
                try:
                    with self.assertRaises(ValueError):
                        verify.verify_package(self.output, replay=False)
                finally:
                    path.unlink()
                    if original is not None:
                        path.write_bytes(original)


class SplitPairedReplayTests(unittest.TestCase):
    def setUp(self):
        fixtures.PairedArchiveTests.setUp(self)

    def test_split_publication_requires_full_replay_and_preserves_source_bytes(self):
        before = {path.relative_to(self.source): path.read_bytes()
                  for path in self.source.rglob('*') if path.is_file()}
        manifest = package.package(self.source, self.output, self.unneeded_policy,
                                   compression_level=9, split_archive=True)
        self.assertEqual(verify.verify_package(self.output), manifest)
        self.assertFalse((self.output / verify.ARCHIVE).exists())
        self.assertEqual(before, {path.relative_to(self.source): path.read_bytes()
                                 for path in self.source.rglob('*') if path.is_file()})

    def test_fully_rehashed_parts_and_raw_association_still_fail_semantic_replay(self):
        from tools.phase1_evidence.common import canonical, reference
        from tools.tests.phase1_paired_fixtures import refresh
        path = self.source / 'pair-01/candidate/candidate.json'
        value = json.loads(path.read_bytes())
        value['samples'][0]['receipt']['release_digest'] = 'sha256:' + '0' * 64
        path.write_bytes(canonical(value))
        refresh(self.suite_path)
        aggregate_path = self.source / 'aggregate.json'
        value = json.loads(aggregate_path.read_bytes())
        value['source'] = reference(self.suite_path, self.source)
        aggregate_path.write_bytes(canonical(value))
        self.output.mkdir()
        package.create_archive(self.source, self.output, self.unneeded_policy,
                               compression_level=9, split_archive=True)
        # Every part, logical gzip, raw file and suite reference has a valid new
        # checksum. Only the actual retained response association is wrong.
        verify.verify_package(self.output, replay=False)
        with self.assertRaisesRegex(ValueError, 'terminal-pin'):
            verify.verify_package(self.output)


if __name__ == '__main__':
    unittest.main()
