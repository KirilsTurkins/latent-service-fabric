"""Native npm graph, original archive, profile and offline consumption controls."""
import base64
import hashlib
import io
from pathlib import Path
import tarfile
import tempfile
import unittest

from tools.application_dependencies import LOCK, MANIFEST, capture, prepare
from tools.application_dependency_store import DependencyError
from tools.build_snapshot import canonical
from tools.typescript_application_dependencies import (bundle_configuration, cached_archive, edge_location,
    graph, native_lock, selection, source_snapshot)
from tools.typescript_guest.project import create, validate


class NpmDependencies(unittest.TestCase):
    def test_native_lock_requires_exact_supported_graph_and_no_url_credentials(self):
        for version in (1, True, 4):
            with self.subTest(version=version), self.assertRaisesRegex(DependencyError, 'lock-version'):
                native_lock(canonical({'lockfileVersion': version, 'packages': {'': {}}}))
        for source in ('https://user:password@example.com/a.tgz', 'https://example.com/a.tgz?token=hidden', 'http://example.com/a.tgz'):
            with self.subTest(source=source), self.assertRaises(DependencyError):
                native_lock(canonical({'lockfileVersion': 3, 'packages': {'': {}, 'node_modules/a': {'resolved': source}}}))

    def test_native_graph_uses_nearest_nested_package_and_peer_identity(self):
        lock = {'packages': {'': {'dependencies': {'outside': 'file:../outside'}},
            'node_modules/outside': {'version': '1.0.0', 'dependencies': {'transitive': '^1'}, 'peerDependencies': {'peer': '^2'}},
            'node_modules/transitive': {'version': '9.0.0'},
            'node_modules/outside/node_modules/transitive': {'version': '1.0.0'},
            'node_modules/peer': {'version': '2.0.0', 'peer': True}}}
        installed = {name: {'version': row['version']} for name, row in lock['packages'].items() if name}
        native = graph(lock, installed, {'os': 'linux', 'cpu': 'x64'})
        outside = next(row for row in native['nodes'] if row['location'] == 'node_modules/outside')
        self.assertEqual(outside['dependencies'][0]['selected'], 'node_modules/outside/node_modules/transitive')
        self.assertEqual(outside['dependencies'][1]['selected'], 'node_modules/peer')
        self.assertEqual(edge_location('node_modules/outside/node_modules/transitive', 'peer', lock['packages']), 'node_modules/peer')

    def test_required_missing_or_mismatched_installed_transitive_fails(self):
        lock = {'packages': {'': {}, 'node_modules/outside': {'version': '1.0.0', 'dependencies': {'absent': '^1'}}}}
        with self.assertRaisesRegex(DependencyError, 'not-closed'):
            graph(lock, {'node_modules/outside': {'version': '1.0.0'}}, {})
        with self.assertRaisesRegex(DependencyError, 'package-missing'):
            graph({'packages': {'': {}, 'node_modules/outside': {'version': '1.0.0'}}}, {}, {})
        with self.assertRaisesRegex(DependencyError, 'version-differs'):
            graph({'packages': {'': {}, 'node_modules/outside': {'version': '1.0.0'}}}, {'node_modules/outside': {'version': '2.0.0'}}, {})

    def test_optional_platform_absence_is_explicit_and_does_not_hide_required_edges(self):
        lock = {'packages': {'': {'optionalDependencies': {'native': '^1'}},
            'node_modules/native': {'version': '1.0.0', 'optional': True, 'os': ['darwin']}}}
        native = graph(lock, {}, {'os': 'linux', 'cpu': 'x64'})
        row = next(row for row in native['nodes'] if row['location'])
        self.assertFalse(row['selected'])
        self.assertTrue(row['optional'])
        self.assertEqual(row['os'], ['darwin'])

    def test_conditions_are_bound_without_forcing_browser_or_enabling_async(self):
        self.assertEqual(selection()['conditions'], [])
        self.assertEqual(selection({'conditions': ['private', 'private']})['conditions'], ['private'])
        with self.assertRaisesRegex(DependencyError, 'profile-not-installed'):
            selection({'runtimeProfile': 'pending-promises'})
        with self.assertRaisesRegex(DependencyError, 'conditions-invalid'):
            selection({'conditions': ['../escape']})

    def archive(self, name='package/index.js'):
        buffer = io.BytesIO()
        with tarfile.open(fileobj=buffer, mode='w:gz') as archive:
            row = tarfile.TarInfo(name)
            row.size = 1
            archive.addfile(row, io.BytesIO(b'x'))
        return buffer.getvalue()

    def cache(self, root, data):
        identity = hashlib.sha512(data).hexdigest()
        path = root / '_cacache/content-v2/sha512' / identity[:2] / identity[2:4] / identity[4:]
        path.parent.mkdir(parents=True)
        path.write_bytes(data)
        return 'sha512-' + base64.b64encode(bytes.fromhex(identity)).decode(), path

    def test_original_native_archive_sri_and_all_entries_are_rechecked(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            data = self.archive()
            integrity, path = self.cache(root, data)
            self.assertEqual(cached_archive(root, integrity), data)
            path.write_bytes(data + b'tampered')
            with self.assertRaisesRegex(DependencyError, 'archive-integrity'):
                cached_archive(root, integrity)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            integrity, _path = self.cache(root, self.archive('package/../../outside'))
            with self.assertRaisesRegex(DependencyError, 'path-invalid'):
                cached_archive(root, integrity)

    def test_original_archive_is_required_even_when_expanded_cache_exists(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            integrity = 'sha512-' + base64.b64encode(bytes(64)).decode()
            with self.assertRaisesRegex(DependencyError, 'archive-unavailable'):
                cached_archive(root, integrity)

    def test_native_declarations_extend_project_only_with_a_reviewed_capture(self):
        with tempfile.TemporaryDirectory() as temporary:
            project = create(Path(temporary) / 'project', 'greeting')
            (project / 'package.json').write_bytes(b'{}')
            (project / 'package-lock.json').write_bytes(b'{}')
            with self.assertRaisesRegex(ValueError, 'reviewed dependency capture'):
                validate(source_snapshot(project))
            (project / 'npm-resolved.lock.json').write_bytes(b'{}')
            (project / MANIFEST).write_bytes(canonical({'formatVersion': 1, 'language': 'typescript', 'selection': selection(),
                'nativeLocks': ['package.json', 'package-lock.json', 'npm-resolved.lock.json'], 'artifacts': [], 'transformations': []}))
            (project / 'node_modules').mkdir()
            (project / 'node_modules/unobserved.js').write_bytes(b'danger')
            files = source_snapshot(project)
            self.assertNotIn('node_modules/unobserved.js', files)
            validate(files)  # prepare still verifies the reviewed exact closure.

    def test_offline_module_lookup_consumes_captured_bytes_with_owned_paths(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project, module, work, output = (root / name for name in ('project', 'original', 'work', 'output'))
            for path in (project, module, work, output): path.mkdir()
            (module / 'index.cjs').write_bytes(b'exports.value = 7;')
            (project / MANIFEST).write_bytes(canonical({'formatVersion': 1, 'language': 'typescript', 'selection': selection(),
                'nativeLocks': [], 'artifacts': [{'id': 'outside/native/7', 'role': 'application', 'format': 'directory',
                    'mount': 'dependencies/npm/node_modules', 'source': {'path': str(module)}, 'dependencies': [],
                    'metadata': {'assetType': 'selected-node-modules'}}], 'transformations': []}))
            (project / LOCK).write_bytes(canonical(capture(project)))
            (module / 'index.cjs').unlink()
            closure = prepare(project, work, output, 'typescript')
            configuration = bundle_configuration(closure)
            self.assertEqual(configuration['nodePaths'], [str(work / 'dependencies/npm/node_modules')])
            self.assertEqual(configuration['inputIdentity'], closure.identity)
            self.assertEqual((work / 'dependencies/npm/node_modules/index.cjs').read_bytes(), b'exports.value = 7;')


if __name__ == '__main__':
    unittest.main()
