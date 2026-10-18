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
    def test_lock_only_optional_rows_cannot_satisfy_required_or_peer_edges(self):
        for kind in ('dependencies', 'devDependencies', 'peerDependencies'):
            lock = {'packages': {'': {kind: {'required': '1.0.0'}},
                'node_modules/required': {'version': '1.0.0', 'optional': True, 'os': ['darwin']}}}
            with self.subTest(kind=kind), self.assertRaisesRegex(DependencyError, 'graph-not-closed'):
                graph(lock, {}, {'os': 'linux', 'cpu': 'x64'})

    def test_optional_overrides_and_peer_omissions_have_no_phantom_selected_target(self):
        lock = {'packages': {'': {'dependencies': {'feature': '1.0.0'},
            'optionalDependencies': {'feature': '2.0.0'}, 'peerDependencies': {'peer': '^3'},
            'peerDependenciesMeta': {'peer': {'optional': True}}},
            'node_modules/feature': {'version': '2.0.0', 'optional': True, 'os': ['darwin'],
                'dependencies': {'available': '^4'}},
            'node_modules/peer': {'version': '3.0.0', 'optional': True, 'peer': True},
            'node_modules/available': {'version': '4.0.0', 'optional': True}}}
        value = graph(lock, {'node_modules/available': {'version': '4.0.0'}}, {'os': 'linux', 'cpu': 'x64'})
        root = next(row for row in value['nodes'] if row['location'] == '')
        self.assertEqual(root['dependencies'], [
            {'name': 'feature', 'kind': 'optionalDependencies', 'specification': '2.0.0', 'selected': None, 'optional': True},
            {'name': 'peer', 'kind': 'peerDependencies', 'specification': '^3', 'selected': None, 'optional': True}])
        feature = next(row for row in value['nodes'] if row['location'] == 'node_modules/feature')
        self.assertFalse(feature['selected'])
        self.assertEqual(feature['os'], ['darwin'])
        self.assertIsNone(feature['dependencies'][0]['selected'])
        lock['packages']['']['peerDependenciesMeta']['peer']['optional'] = False
        with self.assertRaisesRegex(DependencyError, 'graph-not-closed'):
            graph(lock, {}, {})

    def test_omitted_nested_package_does_not_hide_an_installed_ancestor(self):
        for consumer, name in (('node_modules/outside', 'shared'), ('node_modules/@team/outside', '@other/shared')):
            nearest, hoisted = consumer + '/node_modules/' + name, 'node_modules/' + name
            lock = {'packages': {'': {'dependencies': {consumer.removeprefix('node_modules/'): '1.0.0'}},
                consumer: {'version': '1.0.0', 'dependencies': {name: '^2'}},
                nearest: {'version': '2.0.0', 'optional': True}, hoisted: {'version': '2.1.0', 'optional': True}}}
            installed = {consumer: {'version': '1.0.0'}, hoisted: {'version': '2.1.0'}}
            with self.subTest(consumer=consumer):
                value = graph(lock, installed, {})
                row = next(row for row in value['nodes'] if row['location'] == consumer)
                self.assertEqual(row['dependencies'][0]['selected'], hoisted)
                installed[nearest] = {'version': '2.0.0'}
                row = next(row for row in graph(lock, installed, {})['nodes'] if row['location'] == consumer)
                self.assertEqual(row['dependencies'][0]['selected'], nearest)
                sibling = 'node_modules/unrelated/node_modules/' + name
                lock['packages'][sibling] = {'version': '2.0.0', 'optional': True}
                self.assertIsNone(edge_location(consumer, name, lock['packages'], installed={sibling: {'version': '2.0.0'}}))

    def test_native_lock_optional_flags_and_peer_metadata_are_explicit_booleans(self):
        for field in ('optional', 'peer', 'link'):
            for value in (False, True):
                lock = {'lockfileVersion': 3, 'packages': {'': {},
                    'node_modules/feature': {'version': '1.0.0', field: value}}}
                self.assertEqual(native_lock(canonical(lock)), lock)
            for value in ('false', 1, None, []):
                with self.subTest(field=field, value=value), self.assertRaisesRegex(DependencyError, 'flags-invalid'):
                    native_lock(canonical({'lockfileVersion': 3, 'packages': {'': {},
                        'node_modules/feature': {'version': '1.0.0', field: value}}}))
        for metadata in ([], {'feature': None}, {'feature': {'optional': 'false'}}):
            with self.subTest(metadata=metadata), self.assertRaisesRegex(DependencyError, 'peer-metadata-invalid'):
                native_lock(canonical({'lockfileVersion': 3, 'packages': {'': {'peerDependenciesMeta': metadata}}}))
        for value in (False, True):
            lock = {'lockfileVersion': 3, 'packages': {'': {'peerDependenciesMeta': {'feature': {'optional': value}}}}}
            self.assertEqual(native_lock(canonical(lock)), lock)

    def test_incomplete_native_install_preserves_prior_capture_and_emits_no_candidate(self):
        import json
        import subprocess
        from unittest.mock import patch
        from tools import typescript_application_dependencies as native, typescript_dependency_authoring as authoring
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            app = create(root / 'project', 'greeting')
            library = root / 'outside'
            library.mkdir()
            (library / 'package.json').write_bytes(canonical({'name': 'required', 'version': '1.0.0'}))
            (library / 'index.js').write_bytes(b'export const value = 1;')
            spec = 'file:' + str(library)
            (app / 'package.json').write_bytes(canonical({'name': 'application', 'dependencies': {'required': spec}}))
            (app / 'package-lock.json').write_bytes(canonical({'lockfileVersion': 3, 'packages': {
                '': {'dependencies': {'required': spec}}, 'node_modules/required': {
                    'version': '1.0.0', 'resolved': spec, 'optional': True}}}))
            for name in (MANIFEST, LOCK, 'npm-resolved.lock.json'):
                (app / name).write_bytes(('prior accepted ' + name).encode())
            before = authoring.source_files(app)
            node, npm = root / 'node-model-only', root / 'npm-model-only.js'
            for path in (node, npm): path.write_bytes(b'not executable: native outputs are modelled')
            calls = []
            def command(argv, cwd, environment, seconds, maximum):
                calls.append(list(argv))
                if argv[1:] == ['--version']: raw = b'v24.19.0\n'
                elif argv[-1] == '--version': raw = b'11.17.0\n'
                elif argv[1:] == ['-p', 'process.arch']: raw = b'x64\n'
                else:
                    self.assertEqual(argv[2], 'ci')
                    for flag in ('--ignore-scripts', '--bin-links=false', '--strict-peer-deps'):
                        self.assertIn(flag, argv)
                    self.assertEqual((seconds, maximum), (600, 4 * 1024 * 1024))
                    self.assertIn('required', json.loads((Path(cwd) / 'package-lock.json').read_bytes())['packages']['']['dependencies'])
                    (Path(cwd) / 'node_modules').mkdir()
                    raw = b''
                return subprocess.CompletedProcess(argv, 0, raw, b'')
            candidate = root / 'candidate.json'
            with patch.object(native, 'run_bounded', side_effect=command):
                with self.assertRaisesRegex(DependencyError, 'graph-not-closed'):
                    native.resolve(app, candidate, node=node, npm=npm)
            self.assertEqual(authoring.source_files(app), before)
            self.assertFalse(candidate.exists())
            self.assertEqual(len(calls), 4)

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


class PreparedNpmQualification(unittest.TestCase):
    def fixture(self, root):
        from tools.qualify_typescript_dependencies import PRODUCTS
        from tools.phase3_resource_identity import file_identity
        from tools.build_snapshot import digest
        (root / 'native-binaries').mkdir()
        inputs = {'fixture': 'exact maintained source selection'}
        source = canonical(inputs)
        for name in ('source-inputs.json', 'source-inputs-after.json'):
            (root / name).write_bytes(source)
        binaries = {}
        for name in PRODUCTS:
            identity = name if name in ('latent', 'latentd') else 'examples/' + name
            path = root / 'native-binaries' / identity.replace('/', '-')
            path.write_bytes(('owned fixture ' + name).encode())
            binaries[identity] = file_identity(path)
        qualified = {'status': 'passed', 'applicationDependencies': {}, 'sourceIdentityDigest': digest(source),
                     'binaries': binaries}
        (root / 'qualification.json').write_bytes(canonical(qualified))
        return inputs, qualified

    def test_exact_completed_source_and_five_products_are_required(self):
        from unittest.mock import patch
        from tools.phase2_operator_process import WorkflowError
        from tools.qualify_typescript_dependencies import prepared_native
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            inputs, _ = self.fixture(root)
            with patch('tools.qualify_typescript_dependencies.inputs', return_value=inputs):
                products, identity = prepared_native(root)
            self.assertEqual(set(products), {'latent', 'latentd', 'package', 'capsule_contracts', 'capsule_authoring'})
            self.assertEqual(identity['scope'], 'exact-source-preceding-maintained-qualification')
            (products['latentd']).write_bytes(b'changed after native capture')
            with patch('tools.qualify_typescript_dependencies.inputs', return_value=inputs):
                with self.assertRaisesRegex(WorkflowError, 'prepared-native-changed'):
                    prepared_native(root)

    def test_changed_current_source_or_after_snapshot_never_selects_native_products(self):
        from unittest.mock import patch
        from tools.phase2_operator_process import WorkflowError
        from tools.qualify_typescript_dependencies import prepared_native
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            inputs, _ = self.fixture(root)
            with patch('tools.qualify_typescript_dependencies.inputs', return_value={'fixture': 'changed'}):
                with self.assertRaisesRegex(WorkflowError, 'exact-prepared-source-required'):
                    prepared_native(root)
            (root / 'source-inputs-after.json').write_bytes(canonical(inputs) + b'\n')
            with patch('tools.qualify_typescript_dependencies.inputs', return_value=inputs):
                with self.assertRaisesRegex(WorkflowError, 'exact-prepared-source-required'):
                    prepared_native(root)

    def test_pending_or_source_only_qualification_cannot_replace_completed_dependency_gate(self):
        from unittest.mock import patch
        from tools.phase2_operator_process import WorkflowError
        from tools.qualify_typescript_dependencies import prepared_native
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            inputs, qualified = self.fixture(root)
            for change in ({**qualified, 'status': 'in-progress'},
                           {key: value for key, value in qualified.items() if key != 'applicationDependencies'},
                           {**qualified, 'sourceIdentityDigest': 'sha256:' + '0' * 64}):
                (root / 'qualification.json').write_bytes(canonical(change))
                with patch('tools.qualify_typescript_dependencies.inputs', return_value=inputs):
                    with self.assertRaisesRegex(WorkflowError, 'exact-prepared-source-required'):
                        prepared_native(root)

    def test_missing_or_additional_native_product_is_not_an_equivalent_tuple(self):
        from unittest.mock import patch
        from tools.phase2_operator_process import WorkflowError
        from tools.qualify_typescript_dependencies import prepared_native
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            inputs, qualified = self.fixture(root)
            variants = [dict(qualified['binaries']), dict(qualified['binaries'])]
            variants[0].pop('examples/package')
            variants[1]['examples/other-tool'] = qualified['binaries']['latent']
            for binaries in variants:
                (root / 'qualification.json').write_bytes(canonical({**qualified, 'binaries': binaries}))
                with patch('tools.qualify_typescript_dependencies.inputs', return_value=inputs):
                    with self.assertRaisesRegex(WorkflowError, 'prepared-products-not-exact'):
                        prepared_native(root)


if __name__ == '__main__':
    unittest.main()
