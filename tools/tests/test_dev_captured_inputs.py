"""Captured source transport stays distinct from bounded application snapshots."""
import copy
import base64
import os
from pathlib import Path
import tempfile
import tarfile
import unittest

from tools import application_dependencies as capture
from tools.build_snapshot import canonical
from tools.dev_workflow import assets, build_cache, captured_inputs, common, dependencies, paths, project, snapshot, state
from tools.tests.test_dev_contracts import descriptor


class CapturedInputs(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='captured-domain-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source, self.library = self.root / 'source', self.root / 'outside-library'
        self.source.mkdir()
        self.library.mkdir()
        (self.source / 'src').mkdir()
        (self.source / 'src/main.c').write_bytes(b'int value(void) { return 7; }\n')
        (self.library / 'resource.bin').write_bytes(b'r' * (common.MAX_FILE + 1))
        self.manifest = {'formatVersion': 1, 'language': 'c', 'selection': {}, 'nativeLocks': [],
            'artifacts': [{'id': 'uncatalogued/library/1', 'role': 'application', 'format': 'directory',
                'mount': 'dependencies/selected', 'source': {'path': str(self.library)}, 'dependencies': [],
                'metadata': {'license': 'MIT'}}], 'transformations': []}
        (self.source / capture.MANIFEST).write_bytes(canonical(self.manifest))
        lock = capture.capture(self.source)
        (self.source / capture.LOCK).write_bytes(canonical(lock))
        value = descriptor()
        value['language'] = 'c'
        value['template']['ownerIssue'] = project.LANGUAGES['c']
        (self.source / 'latent.project.json').write_bytes(common.encode(value))
        self.descriptor, _ = project.load(self.source)
        self.record, self.content = snapshot.observe(self.source, self.descriptor['inputRoots'])
        self.library.rename(self.root / 'retained-originals')

    def materialize(self, destination):
        snapshot.materialize(destination, self.record, self.content, commit=False)

    def test_large_objects_use_authenticated_domain_without_changing_controller_limits(self):
        self.assertEqual((common.MAX_FILES, common.MAX_SNAPSHOT, common.MAX_FILE), (2048, 64 * 1024**2, 16 * 1024**2))
        self.assertEqual(self.record['schemaVersion'], 'latent.dev.snapshot.v2')
        self.assertLessEqual(len(self.record['files']), common.MAX_FILES)
        self.assertLessEqual(self.record['bytes'], common.MAX_SNAPSHOT)
        self.assertGreater(self.record['capturedInputs']['objectBytes'], common.MAX_FILE)
        self.assertFalse(any(name.startswith(dependencies.OBJECTS + '/') for name in self.content))
        snapshot.validate(self.record)
        large = next(row for row in captured_inputs.observe(self.source)[1] if row['size'] > common.MAX_FILE)
        with self.assertRaisesRegex(common.DevError, 'file-byte-limit'):
            paths.read(self.source, captured_inputs.object_path(large['digest']))

    def test_pack_restore_and_build_attempt_copy_preserve_real_offline_capture(self):
        packet = self.root / 'packet'
        captured_inputs.pack(self.source, self.record['capturedInputs'], packet)
        destination = self.root / 'restored'
        self.materialize(destination)
        captured_inputs.restore(destination, self.record['capturedInputs'], packet)
        snapshot.commit(destination, self.record)
        dependencies.verify(destination, self.descriptor)
        self.assertEqual(snapshot.observe(destination, self.descriptor['inputRoots'])[0], self.record)
        workspace = self.root / 'workspace'
        workspace.mkdir()
        attempt, copied, receipt = build_cache.allocate(workspace, destination, self.record, self.descriptor,
            common.digest(b'recipe'), 'source-control-host', common.digest(b'packager'))
        self.assertIsNone(receipt)
        self.assertEqual(build_cache.owner(attempt)['state'], 'created')
        self.assertEqual(snapshot.observe(copied, self.descriptor['inputRoots'])[0], self.record)
        self.assertFalse(self.library.exists())

    def test_corrupt_object_data_cannot_complete_restore(self):
        packet = self.root / 'packet'
        captured_inputs.pack(self.source, self.record['capturedInputs'], packet)
        with tarfile.open(packet / captured_inputs.ARCHIVE) as archive:
            offset = next(item.offset_data for item in archive if item.size)
        with (packet / captured_inputs.ARCHIVE).open('r+b') as stream:
            stream.seek(offset)
            original = stream.read(1)
            stream.seek(offset)
            stream.write(bytes([original[0] ^ 1]))
        destination = self.root / 'corrupt-restoration'
        self.materialize(destination)
        with self.assertRaisesRegex(common.DevError, 'captured-input-object-content'):
            captured_inputs.restore(destination, self.record['capturedInputs'], packet)
        self.assertFalse((destination / 'snapshot.json').exists())

    def test_capture_identity_and_expanded_bounds_reject_forged_headers(self):
        header = self.record['capturedInputs']
        for field, maximum in [('objectBytes', capture.MAX_CLOSURE_BYTES), ('closureBytes', capture.MAX_CLOSURE_BYTES),
                               ('closureFiles', capture.MAX_CLOSURE_FILES)]:
            value = {**header, field: maximum + 1}
            value['identity'] = common.digest(common.encode({key: item for key, item in value.items() if key != 'identity'}))
            with self.subTest(field=field), self.assertRaisesRegex(common.DevError, 'captured-input-domain-limit'):
                captured_inputs.validate(value)
        value = copy.deepcopy(self.record)
        value['capturedInputs']['lockDigest'] = common.digest(b'other lock')
        value['capturedInputs']['identity'] = common.digest(common.encode({key: item for key, item in value['capturedInputs'].items() if key != 'identity'}))
        value['identity'] = common.digest(common.encode({key: item for key, item in value.items() if key != 'identity'}))
        with self.assertRaisesRegex(common.DevError, 'captured-input-snapshot-document-binding'):
            snapshot.validate(value)

    def test_object_byte_accounting_is_checked_before_any_payload_is_adopted(self):
        packet = self.root / 'packet'
        captured_inputs.pack(self.source, self.record['capturedInputs'], packet)
        value = dependencies.capture_document((packet / captured_inputs.METADATA).read_bytes())
        expected = {**self.record['capturedInputs'], 'objectBytes': 1}
        expected['identity'] = common.digest(common.encode({key: item for key, item in expected.items() if key != 'identity'}))
        value['capture'] = expected
        (packet / captured_inputs.METADATA).write_bytes(common.encode(value))
        destination = self.root / 'misstated-accounting'
        self.materialize(destination)
        with self.assertRaisesRegex(common.DevError, 'captured-input-object-accounting'):
            captured_inputs.restore(destination, expected, packet)
        self.assertFalse((destination / dependencies.OBJECTS).exists())

    def test_capture_assets_are_data_only_and_cannot_use_installer_cache_namespace(self):
        files = [{'path': name, 'sha256': common.digest(b'bytes'), 'size': 5, 'executable': False}
                 for name in (captured_inputs.METADATA, captured_inputs.ARCHIVE)]
        value = {'schemaVersion': 'latent.dev.inputs.v1', 'domain': captured_inputs.DOMAIN, 'files': files}
        value['identity'] = common.digest(common.encode(value))
        assets.manifest(value)
        self.assertNotEqual(assets.directory(self.root, value['identity']), assets.directory(self.root, value['identity'], captured_inputs.DOMAIN))
        value['files'][0]['executable'] = True
        value['identity'] = common.digest(common.encode({key: item for key, item in value.items() if key != 'identity'}))
        with self.assertRaisesRegex(common.DevError, 'captured-input-transfer-inventory'):
            assets.manifest(value)

    @unittest.skipUnless(os.name == 'posix', 'Actual anchored receiver and helper require Linux')
    def test_real_chunk_receiver_associates_only_verified_capture_and_rejects_later_tamper(self):
        from tools.dev_workflow import helper
        workspace = self.root / 'workspace'
        paths.new_directory(workspace)
        class Receiver:
            def call(inner, operation, arguments, **options):
                self.assertTrue(operation.startswith('capture-'))
                self.assertEqual(arguments['domain'], captured_inputs.DOMAIN)
                return assets.receive(workspace, operation.replace('capture-', 'asset-', 1), arguments)
        sources = captured_inputs.pack(self.source, self.record['capturedInputs'], self.root / 'packet')
        completed = assets.transfer(Receiver(), sources, domain=captured_inputs.DOMAIN)
        arguments = {'snapshot': self.record, 'project': self.descriptor,
            'trustedRecipe': project.trust_identity(self.descriptor), 'captureAsset': completed['identity'],
            'content': {name: base64.b64encode(raw).decode() for name, raw in self.content.items()}}
        observed = helper.sync(workspace, arguments)
        self.assertEqual(observed['snapshot'], self.record['identity'])
        saved = state.load(workspace, 'project.json')
        accepted = Path(saved['source'])
        self.assertFalse((accepted / 'snapshot-intent.json').exists())
        large = next(row for row in captured_inputs.observe(accepted)[1] if row['size'] > common.MAX_FILE)
        blob = accepted / captured_inputs.object_path(large['digest'])
        with blob.open('r+b') as stream:
            stream.write(b'X')
        with self.assertRaisesRegex(ValueError, 'dependency-artifact-integrity'):
            helper.sync(workspace, arguments)
        self.assertEqual(state.load(workspace, 'project.json'), saved)

    @unittest.skipUnless(os.name == 'posix', 'Actual anchored receiver and helper require Linux')
    def test_incomplete_or_wrong_domain_transfer_preserves_last_good_project(self):
        from tools.dev_workflow import helper
        workspace = self.root / 'workspace'
        paths.new_directory(workspace)
        prior = {'snapshot': 'previous-good'}
        state.atomic(workspace, 'project.json', prior)
        arguments = {'snapshot': self.record, 'project': self.descriptor,
            'trustedRecipe': project.trust_identity(self.descriptor), 'captureAsset': common.digest(b'not-transferred'),
            'content': {name: base64.b64encode(raw).decode() for name, raw in self.content.items()}}
        with self.assertRaises((common.DevError, FileNotFoundError)):
            helper.sync(workspace, arguments)
        self.assertEqual(state.load(workspace, 'project.json'), prior)


if __name__ == '__main__':
    unittest.main()
