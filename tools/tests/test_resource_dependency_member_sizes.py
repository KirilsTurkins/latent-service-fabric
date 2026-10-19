"""Captured dependency membership requires an actual integer byte count."""
import copy
import unittest

from tools import guest_resources as resources
from tools.dev_workflow.common import digest, encode
from tools.rust_capsule_project import inventory


class DependencyMemberSizes(unittest.TestCase):
    def fixture(self, payload, size):
        owner = 'outside-owner/resource-size/1'
        lock = {'artifacts': [{'id': owner, 'files': [
            {'path': 'data.bin', 'digest': digest(payload), 'size': size}]}]}
        files = {'dependencies/data.bin': payload, 'latent.dependencies.lock.json': encode(lock)}
        row = {'path': 'data.bin', 'source': 'dependencies/data.bin', 'mediaType': 'application/octet-stream',
               'owner': owner, 'digest': digest(payload)}
        return files, row, lock

    def capture(self, files, row):
        return resources.capture(files, b'component', inventory(files), additional_resources=[row])

    def verify(self, packaged, files):
        return resources.verify(encode(packaged.index), packaged.objects,
            source_digest=packaged.index['sourceDigest'], component_digest=digest(b'component'),
            dependency_lock_digest=digest(files['latent.dependencies.lock.json']),
            dependency_lock=files['latent.dependencies.lock.json'])

    def assert_denied(self, callback):
        with self.assertRaises(resources.ResourceError) as raised:
            callback()
        self.assertEqual((raised.exception.category, raised.exception.code),
                         ('denied', 'resource-dependency-bytes-not-captured'))

    def test_capture_refuses_boolean_metadata_matching_empty_and_one_byte_payloads(self):
        for payload, size in ((b'', False), (b'x', True)):
            files, row, _ = self.fixture(payload, size)
            before = copy.deepcopy(files)
            with self.subTest(payload=payload, size=size):
                self.assert_denied(lambda: self.capture(files, row))
                self.assertEqual(files, before)

    def test_capture_refuses_floating_point_metadata_equal_to_actual_byte_counts(self):
        for payload, size in ((b'', 0.0), (b'x', 1.0)):
            files, row, _ = self.fixture(payload, size)
            with self.subTest(payload=payload, size=size):
                self.assert_denied(lambda: self.capture(files, row))

    def test_rehashed_lock_and_index_cannot_adopt_boolean_or_float_member_sizes(self):
        for payload, size in ((b'', False), (b'x', True), (b'', 0.0), (b'x', 1.0)):
            files, row, lock = self.fixture(payload, len(payload))
            packaged = self.capture(files, row)
            self.verify(packaged, files)
            lock['artifacts'][0]['files'][0]['size'] = size
            files['latent.dependencies.lock.json'] = encode(lock)
            index = copy.deepcopy(packaged.index)
            index['dependencyLockDigest'] = digest(files['latent.dependencies.lock.json'])
            index['identity'] = digest(encode({key: value for key, value in index.items() if key != 'identity'}))
            changed = resources.PackagedResources(index, packaged.objects)
            with self.subTest(payload=payload, size=size):
                self.assert_denied(lambda: self.verify(changed, files))

    def test_integer_zero_one_binary_and_shared_bytes_keep_exact_inventory(self):
        for payload in (b'', b'x', b'\x00\xff\n'):
            files, row, _ = self.fixture(payload, len(payload))
            packaged = resources.capture(files, b'component', inventory(files),
                additional_resources=[row, {**row, 'path': 'copy.bin'}])
            value = self.verify(packaged, files)
            with self.subTest(payload=payload):
                self.assertEqual(value['count'], 2)
                self.assertEqual(value['bytes'], 2 * len(payload))
                self.assertEqual(list(packaged.objects.values()), [payload])
                self.assertEqual([item['size'] for item in value['resources']], [len(payload)] * 2)

    def test_unselected_malformed_records_do_not_shadow_a_valid_captured_member(self):
        files, row, lock = self.fixture(b'x', 1)
        lock['artifacts'][0]['files'][:0] = [
            {'path': 'unselected.bin', 'digest': digest(b'other'), 'size': False},
            {'path': 'data-alias.bin', 'digest': digest(b'x'), 'size': 1.0}]
        files['latent.dependencies.lock.json'] = encode(lock)
        packaged = self.capture(files, row)
        self.assertEqual(self.verify(packaged, files)['resources'][0]['size'], 1)
        self.assertEqual(list(packaged.objects.values()), [b'x'])

    def test_other_noninteger_and_wrong_size_records_keep_existing_denial(self):
        for size in (None, '1', [], {}, -1, 2):
            files, row, _ = self.fixture(b'x', size)
            with self.subTest(size=size):
                self.assert_denied(lambda: self.capture(files, row))
        files, row, lock = self.fixture(b'x', 1)
        del lock['artifacts'][0]['files'][0]['size']
        files['latent.dependencies.lock.json'] = encode(lock)
        self.assert_denied(lambda: self.capture(files, row))


if __name__ == '__main__':
    unittest.main()
