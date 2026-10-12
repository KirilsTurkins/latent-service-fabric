"""Captured dependency documents use their maintained profile, not control limits."""
import copy
import itertools
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools import application_dependencies as capture, rust_application_dependencies as cargo
from tools.application_dependency_store import tree_identity
from tools.build_snapshot import canonical, digest
from tools.dev_workflow import common, dependencies


class CapturedDependencyDocuments(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        temporary = tempfile.TemporaryDirectory(prefix='captured-native-document-')
        cls.addClassCleanup(temporary.cleanup)
        cls.root = Path(temporary.name)
        cls.application, cls.library = cls.root / 'app', cls.root / 'outside-library'
        cls.application.mkdir()
        cls.library.mkdir()
        (cls.application / 'Cargo.toml').write_bytes(b'[package]\nname="app"\nversion="1.0.0"\n')
        (cls.application / 'Cargo.lock').write_bytes(b'version = 4\n[[package]]\nname="app"\nversion="1.0.0"\n')
        # Cargo permits all-features selection independently of the controller's
        # control-document item limit. Keep real source files and metadata within
        # the existing capture byte/count limits without thousands of disk files.
        features = [''.join(value) for value in itertools.islice(itertools.product('abcdefghijklmnopqrstuvwxyz', repeat=4), 32768)]
        (cls.library / 'Cargo.toml').write_bytes(b'[package]\nname="outside-library"\nversion="1.0.0"\n[features]\n'
                                               + ''.join(name + '=[]\n' for name in features).encode())
        native = {'version': 1, 'packages': [
            {'id': name, 'name': name, 'version': '1.0.0', 'source': None,
             'manifest_path': str(directory / 'Cargo.toml'), 'targets': [{'kind': ['lib']}],
             'license': 'MIT', 'license_file': None}
            for name, directory in [('app', cls.application), ('outside-library', cls.library)]],
            'resolve': {'root': 'app', 'nodes': [
                {'id': 'app', 'features': [], 'deps': [{'pkg': 'outside-library'}]},
                {'id': 'outside-library', 'features': features, 'deps': []}]}}
        artifacts, graph = cargo.analyze(native, cls.application, cls.root, {'version': 'fixture-native-graph'})
        (cls.application / 'cargo-resolved.lock.json').write_bytes(canonical(graph))
        cls.manifest = {'formatVersion': 1, 'language': 'rust',
            'selection': {'target': 'wasm32-unknown-unknown', 'allFeatures': True},
            'nativeLocks': ['Cargo.lock', 'cargo-resolved.lock.json'],
            'artifacts': artifacts, 'transformations': []}
        (cls.application / capture.MANIFEST).write_bytes(canonical(cls.manifest))
        cls.lock = capture.capture(cls.application)
        cls.lock_bytes = canonical(cls.lock)
        (cls.application / capture.LOCK).write_bytes(cls.lock_bytes)
        assert len(cls.lock_bytes) < capture.MAX_LOCK
        assert len(cls.lock['artifacts']) < capture.MAX_ARTIFACTS
        assert sum(len(row['files']) for row in cls.lock['artifacts']) < capture.MAX_CLOSURE_FILES
        cls.library.rename(cls.root / 'retained-originals')

    def test_native_rust_capture_above_control_item_limit_binds_and_verifies_offline(self):
        with self.assertRaisesRegex(common.DevError, 'document-complexity-limit'):
            common.decode(self.lock_bytes, capture.MAX_LOCK)
        self.assertFalse(self.library.exists())
        binding, roots = dependencies.selected(self.application, 'rust')
        self.assertEqual(binding['applicationLock'], digest(self.lock_bytes))
        self.assertEqual(binding['applicationManifest'], digest(canonical(self.manifest)))
        descriptor = {'language': 'rust', 'dependencyInputs': binding, 'inputRoots': roots, 'exclude': []}
        with patch.object(capture, 'fetch', side_effect=AssertionError('offline binding fetched inputs')):
            dependencies.verify(self.application, descriptor)

    def test_capture_byte_package_and_closure_limits_remain_enforced(self):
        self.assertEqual((capture.MAX_LOCK, capture.MAX_ARTIFACTS, capture.MAX_CLOSURE_FILES, capture.MAX_CLOSURE_BYTES),
                         (8 * 1024**2, 1024, 32768, 512 * 1024**2))
        with tempfile.TemporaryDirectory(dir=self.root) as temporary:
            root = Path(temporary)
            manifest = copy.deepcopy(self.manifest)
            manifest['artifacts'] = [{**manifest['artifacts'][0], 'metadata': {}}] * (capture.MAX_ARTIFACTS + 1)
            (root / capture.MANIFEST).write_bytes(canonical(manifest))
            (root / capture.LOCK).write_bytes(self.lock_bytes)
            with self.assertRaisesRegex(common.DevError, 'dependency-manifest-count'):
                dependencies.selected(root, 'rust')
            (root / capture.MANIFEST).write_bytes(canonical(self.manifest))
            (root / capture.LOCK).write_bytes(b' ' * (capture.MAX_LOCK + 1))
            with self.assertRaises(common.DevError):
                dependencies.selected(root, 'rust')
            for name in self.manifest['nativeLocks']:
                (root / name).write_bytes((self.application / name).read_bytes())
            for dimension in ('files', 'bytes'):
                lock = copy.deepcopy(self.lock)
                row = lock['artifacts'][0]
                if dimension == 'files':
                    row['files'] = [{'path': f'item-{index:05}.rs', 'digest': digest(b'17\n'), 'size': 3}
                                    for index in range(capture.MAX_CLOSURE_FILES + 1)]
                else:
                    row['files'][0]['size'] = capture.MAX_CLOSURE_BYTES + 1
                row['treeDigest'] = tree_identity(row['files'])
                (root / capture.LOCK).write_bytes(canonical(lock))
                with self.subTest(dimension=dimension), self.assertRaisesRegex(ValueError, 'dependency-closure-limit'):
                    capture.verify_inputs(root, 'rust', cache=self.application / dependencies.OBJECTS)

    def test_malformed_duplicate_nonfinite_and_over_nested_capture_documents_are_rejected(self):
        invalid = [b'{', b'{"x":1,"x":2}', b'{"x":NaN}', b'{"x":Infinity}', b'[]',
                   b'{"x":' + b'[' * 64 + b'0' + b']' * 64 + b'}']
        with tempfile.TemporaryDirectory(dir=self.root) as temporary:
            root = Path(temporary)
            for raw in invalid:
                with self.subTest(raw=raw[:32]):
                    (root / capture.MANIFEST).write_bytes(raw)
                    (root / capture.LOCK).write_bytes(self.lock_bytes)
                    with self.assertRaises(common.DevError):
                        dependencies.selected(root, 'rust')
                    (root / capture.MANIFEST).write_bytes(canonical(self.manifest))
                    (root / capture.LOCK).write_bytes(raw)
                    with self.assertRaises(common.DevError):
                        dependencies.selected(root, 'rust')

    def test_generic_controller_depth_and_item_limits_are_unchanged(self):
        for raw in [b'{"x":' + b'[' * 25 + b'0' + b']' * 25 + b'}', self.lock_bytes]:
            with self.subTest(size=len(raw)), self.assertRaisesRegex(common.DevError, 'document-complexity-limit'):
                common.decode(raw, capture.MAX_LOCK)


if __name__ == '__main__':
    unittest.main()
