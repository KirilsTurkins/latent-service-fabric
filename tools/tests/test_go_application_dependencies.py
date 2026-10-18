"""Native Go graph/hash boundaries and verified offline staging controls."""
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
import zipfile

from tools.application_dependencies import LOCK, MANIFEST, capture, prepare
from tools.application_dependency_store import DependencyError
from tools.build_snapshot import canonical, digest
from tools.go_application_dependencies import configure, graph, h1, json_stream, native_assembly, selection, sums, verify_download
from tools.go_capsule_project import create, validate
from tools.rust_capsule_project import snapshot


class GoDependencies(unittest.TestCase):
    def test_empty_import_linkage_markers_are_distinct_from_native_assembly_or_preprocessor_reads(self):
        for data in (b'', b'// empty import linkage marker\n', b' /* harmless comment */ \n// comment\n'):
            self.assertFalse(native_assembly(data))
        for data in (b'TEXT native(SB),$0-0\nRET\n', b'#include "/ambient/host.h"\n', b'/* comment */\nCALL operation\n'):
            self.assertTrue(native_assembly(data))

    def test_native_json_stream_is_bounded_closed_and_never_accepts_unresolved_records(self):
        self.assertEqual(json_stream(b'{"Path":"a"}\n {"Path":"b"}\n'), [{'Path': 'a'}, {'Path': 'b'}])
        for raw in (b'[]', b'{"Error":"private endpoint and secret"}', b'{}\n' * 1025):
            with self.subTest(raw=raw[:40]), self.assertRaises(DependencyError):
                json_stream(raw)

    def test_target_tags_and_runtime_selection_are_exact_without_a_module_catalogue(self):
        self.assertEqual(selection({'tags': ['local_feature', 'other', 'local_feature']})['tags'], ['local_feature', 'other'])
        for value in ({'target': 'linux/amd64'}, {'runtimeProfile': 'native-go'}, {'tags': ['-toolexec=host']}, {'unknown': True}):
            with self.subTest(value=value), self.assertRaises(DependencyError):
                selection(value)

    def test_go_dirhash_matches_the_known_empty_hash_and_binds_names_and_bytes(self):
        self.assertEqual(h1({}), 'h1:47DEQpj8HBSa+/TImW+5JCeuQeRkm5NMpJWZG3hSuFU=')
        self.assertNotEqual(h1({'go.mod': b'module a\n'}), h1({'other': b'module a\n'}))
        self.assertEqual(h1({'b': b'B', 'a': b'A'}), h1({'a': b'A', 'b': b'B'}))
        for content in (b'a v1 h1:invalid\n', b'a v1 ' + h1({}).encode() + b'\na v1 ' + h1({'a': b'a'}).encode()):
            with self.assertRaises(DependencyError):
                sums(content)

    def module_download(self, root):
        payload = {'private.example.test/library@v1.2.3/go.mod': b'module private.example.test/library\n',
                   'private.example.test/library@v1.2.3/data/immutable.txt': b'Hello, \xc3\xa9!'}
        original = root / 'library.zip'
        with zipfile.ZipFile(original, 'w') as archive:
            for name, data in payload.items():
                archive.writestr(name, data)
        directory = root / 'expanded'
        for name, data in payload.items():
            path = directory / name.removeprefix('private.example.test/library@v1.2.3/')
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        mod = root / 'library.mod'
        mod.write_bytes(payload['private.example.test/library@v1.2.3/go.mod'])
        row = {'Path': 'private.example.test/library', 'Version': 'v1.2.3', 'Zip': str(original), 'Dir': str(directory),
               'GoMod': str(mod), 'Sum': h1(payload), 'GoModSum': h1({'go.mod': mod.read_bytes()})}
        expected = {(row['Path'], row['Version']): row['Sum'], (row['Path'], row['Version'] + '/go.mod'): row['GoModSum']}
        return row, expected

    def test_original_module_zip_and_manifest_are_independently_bound_to_reviewed_go_sums(self):
        with tempfile.TemporaryDirectory() as temporary:
            row, expected = self.module_download(Path(temporary))
            _, selected = verify_download(row, expected)
            self.assertEqual(selected['data/immutable.txt'], b'Hello, \xc3\xa9!')
            changed = dict(expected)
            changed[(row['Path'], row['Version'])] = h1({})
            with self.assertRaisesRegex(DependencyError, 'reviewed-sums'):
                verify_download(row, changed)
            Path(row['GoMod']).write_bytes(b'module other\n')
            with self.assertRaisesRegex(DependencyError, 'manifest-identity'):
                verify_download(row, expected)

    def test_expanded_module_tampering_extra_files_or_unsafe_original_archive_fail(self):
        with tempfile.TemporaryDirectory() as temporary:
            row, expected = self.module_download(Path(temporary))
            (Path(row['Dir']) / 'ambient.go').write_bytes(b'package unexpected\n')
            with self.assertRaisesRegex(DependencyError, 'expanded-module'):
                verify_download(row, expected)
            with zipfile.ZipFile(row['Zip'], 'a') as archive:
                archive.writestr('../escape', b'bad')
            with self.assertRaises(DependencyError):
                verify_download(row, expected)

    def test_literal_exclamation_module_files_keep_original_hash_and_expanded_identity(self):
        with tempfile.TemporaryDirectory() as temporary:
            row, expected = self.module_download(Path(temporary))
            prefix = row['Path'] + '@' + row['Version'] + '/'
            name = 'testdata/expect/yo!.go'
            data = b'package expect\n'
            with zipfile.ZipFile(row['Zip'], 'a') as archive:
                archive.writestr(prefix + name, data)
            with zipfile.ZipFile(row['Zip']) as archive:
                original = {item: archive.read(item) for item in archive.namelist()}
            path = Path(row['Dir']) / name
            path.parent.mkdir(parents=True)
            path.write_bytes(data)
            row['Sum'] = h1(original)
            expected[(row['Path'], row['Version'])] = row['Sum']
            captured, selected = verify_download(row, expected)
            self.assertEqual(captured, original)
            self.assertEqual(selected[name], data)
            self.assertNotEqual(h1(original), h1({key.replace('!', ''): value
                                                 for key, value in original.items()}))
            with zipfile.ZipFile(row['Zip'], 'w') as archive:
                for item, content in original.items():
                    archive.writestr(item, content + b'changed' if item == prefix + name else content)
            with self.assertRaisesRegex(DependencyError, 'original-module-zip-identity'):
                verify_download(row, expected)
            with zipfile.ZipFile(row['Zip'], 'w') as archive:
                for item, content in original.items():
                    archive.writestr(item, content)
            path.write_bytes(b'package tampered\n')
            with self.assertRaisesRegex(DependencyError, 'expanded-module-differs'):
                verify_download(row, expected)

    def test_graph_metadata_keeps_superseded_versions_offline_with_original_hashes_and_escaping(self):
        from tools.go_application_dependencies import graph_manifests
        with tempfile.TemporaryDirectory() as temporary:
            cache = Path(temporary)
            versions = {'v1.3.0': b'module example.test/Upper/Library\n',
                        'v1.8.0': b'module example.test/Upper/Library\n\ngo 1.27.2\n'}
            expected = {}
            for version, raw in versions.items():
                path = cache / ('example.test/!upper/!library/@v/' + version + '.mod')
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(raw)
                expected[('example.test/Upper/Library', version + '/go.mod')] = h1({'go.mod': raw})
            result = graph_manifests(cache, expected)
            self.assertEqual(result, {'example.test/!upper/!library/@v/' + version + '.mod': raw
                                      for version, raw in versions.items()})
            # Older graph metadata is retained without selecting its source or ZIP.
            self.assertEqual(len(result), 2)
            self.assertTrue(all(name.endswith('.mod') for name in result))
            (cache / 'example.test/!upper/!library/@v/v1.3.0.mod').write_bytes(b'tampered')
            with self.assertRaisesRegex(DependencyError, 'go-graph-manifest-identity'):
                graph_manifests(cache, expected)

    def test_graph_metadata_rejects_unreviewed_mislocated_or_traversing_manifests(self):
        from tools.go_application_dependencies import graph_manifests
        with tempfile.TemporaryDirectory() as temporary:
            cache = Path(temporary)
            raw = b'module example.test/library\n'
            path = cache / 'example.test/library/@v/v1.0.0.mod'
            path.parent.mkdir(parents=True)
            path.write_bytes(raw)
            expected = {('example.test/library', 'v1.0.0/go.mod'): h1({'go.mod': raw})}
            for sums_value in ({}, {('other.test/library', 'v1.0.0/go.mod'): h1({'go.mod': raw})},
                               {('example.test/library', '../../outside/go.mod'): h1({'go.mod': raw})}):
                with self.subTest(sums=sums_value), self.assertRaises(DependencyError):
                    graph_manifests(cache, sums_value)
            self.assertEqual(graph_manifests(cache, expected), {'example.test/library/@v/v1.0.0.mod': raw})

    def test_native_graph_records_mvs_minimums_replacements_excludes_and_closed_selection(self):
        root = {'Module': {'Path': 'application.example.test/new-identity'}, 'Go': '1.27.2',
                'Exclude': [{'Path': 'module.example.test/transitive', 'Version': 'v0.9.0'}]}
        modules = [{'Path': root['Module']['Path'], 'Main': True},
                   {'Path': 'module.example.test/library', 'Version': 'v1.0.0',
                    'Replace': {'Path': '../private/local', 'Dir': '/owned/private/local'}},
                   {'Path': 'module.example.test/transitive', 'Version': 'v1.3.0', 'Indirect': True}]
        actual = graph(modules, root['Module']['Path'] + ' module.example.test/library@v1.0.0\n'
                       'module.example.test/library@v1.0.0 module.example.test/transitive@v1.1.0\n'
                       + root['Module']['Path'] + ' go@1.27.2\n', root)
        self.assertEqual(actual['edges'][1]['minimumVersion'], 'v1.1.0')
        self.assertTrue(actual['edges'][2]['nativeToolchainDirective'])
        self.assertEqual(actual['exclusions'], root['Exclude'])
        local = next(row for row in actual['nodes'] if row['replacement'])
        self.assertIsNone(local['replacement']['path'])
        self.assertNotIn('/owned/private/local', json.dumps(actual))
        with self.assertRaisesRegex(DependencyError, 'not-closed'):
            graph(modules, root['Module']['Path'] + ' missing.example.test/module@v1.0.0\n', root)

    def test_go_declarations_require_reviewed_common_capture_and_keep_sdk_bytes_immutable(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = create(Path(temporary) / 'project', 'greeting')
            files = snapshot(root)
            files['go.mod'] += b'\nrequire example.test/library v1.0.0\n'
            with self.assertRaisesRegex(ValueError, 'unreviewed Go module inputs'):
                validate(files)
            manifest = {'formatVersion': 1, 'language': 'go', 'selection': selection(),
                        'nativeLocks': ['go.mod', 'go.sum', 'go-resolved.lock.json'], 'artifacts': [], 'transformations': []}
            files[MANIFEST] = canonical(manifest)
            files['go-resolved.lock.json'] = b'{}\n'
            validate(files)
            files['vendor/lsf/sdk/go-guest/runtime/deny-wasi.wat'] += b'\n;; changed\n'
            with self.assertRaisesRegex(ValueError, 'vendored SDK changed'):
                validate(files)

    def test_offline_staging_only_copies_verified_local_sources_and_selected_native_manifest(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project = root / 'project'
            project.mkdir()
            (project / 'go.mod').write_bytes(b'module arbitrary.example.test/application\n')
            (project / 'go.sum').write_bytes(b'')
            (project / 'go-resolved.lock.json').write_bytes(canonical({'selection': selection(),
                'module': 'arbitrary.example.test/application', 'selectedManifestDigest': digest((project / 'go.mod').read_bytes())}))
            local, cache = root / 'outside', root / 'cache'
            local.mkdir()
            cache.mkdir()
            (local / 'data.txt').write_bytes(b'immutable')
            (cache / 'selected.info').write_bytes(b'{}')
            rows = [{'id': 'local', 'role': 'application', 'format': 'directory', 'mount': 'dependencies/go-modules/local',
                     'source': {'path': str(local)}, 'dependencies': [], 'metadata': {'assetType': 'local-module'}},
                    {'id': 'cache', 'role': 'application', 'format': 'directory', 'mount': 'dependencies/go-downloads',
                     'source': {'path': str(cache)}, 'dependencies': ['local'], 'metadata': {'assetType': 'selected-module-downloads'}},
                    {'id': 'root', 'role': 'generated', 'format': 'file', 'mount': 'application-vendor/go-project/go.mod',
                     'source': {'path': str(project / 'go.mod')}, 'dependencies': ['local', 'cache'], 'metadata': {'assetType': 'selected-root-module'}}]
            manifest = {'formatVersion': 1, 'language': 'go', 'selection': selection(),
                        'nativeLocks': ['go.mod', 'go.sum', 'go-resolved.lock.json'], 'artifacts': rows, 'transformations': []}
            (project / MANIFEST).write_bytes(canonical(manifest))
            (project / LOCK).write_bytes(canonical(capture(project)))
            work, output = root / 'work', root / 'output'
            work.mkdir()
            output.mkdir()
            for name in ('go.sum', 'go-resolved.lock.json'):
                (work / name).write_bytes((project / name).read_bytes())
            closure = prepare(project, work, output, 'go')
            generated = root / 'generated'
            generated.mkdir()
            result = configure(closure, generated)
            self.assertEqual(result['module'], 'arbitrary.example.test/application')
            self.assertEqual((generated / 'dependencies/go-modules/local/data.txt').read_bytes(), b'immutable')
            self.assertNotIn(str(local), json.dumps(result))
            self.assertFalse(result['cgo'])
            (work / 'go-resolved.lock.json').write_bytes(b'{}')
            with self.assertRaises((DependencyError, KeyError)):
                configure(closure, generated)


class DirectApplicationLibraries(unittest.TestCase):
    def setUp(self):
        from tools.go_dependency_fixture import direct_libraries

        self.select = direct_libraries
        self.declaration = {'Module': {'Path': 'application.example.test/ordinary'},
            'Require': [{'Path': 'unknown.example.test/chosen', 'Version': 'v3.2.1', 'Indirect': False},
                        {'Path': 'private.example.test/independent', 'Version': 'v0.0.0', 'Indirect': False}]}
        self.native = {'module': self.declaration['Module']['Path'], 'nodes': [
            {'id': 'go/root', 'path': self.declaration['Module']['Path'], 'main': True},
            {'id': 'go/chosen', 'path': 'unknown.example.test/chosen', 'version': 'v3.2.1', 'indirect': False},
            {'id': 'go/independent', 'path': 'private.example.test/independent', 'version': 'v0.0.0', 'indirect': False}],
            'edges': [{'owner': self.declaration['Module']['Path'], 'selected': 'go/chosen'},
                      {'owner': self.declaration['Module']['Path'], 'selected': 'go/independent'}]}
        self.artifacts = [{'id': 'go/chosen', 'role': 'application', 'metadata': {
                'module': 'unknown.example.test/chosen', 'version': 'v3.2.1', 'assetType': 'selected-module-source'}},
            {'id': 'go/independent', 'role': 'application', 'metadata': {
                'module': 'private.example.test/independent', 'version': 'v0.0.0', 'assetType': 'local-module'}}]
        self.required = {'unknown.example.test/chosen': ('v3.2.1', 'chosen.Width'),
                         'private.example.test/independent': ('v0.0.0', 'independent.Prefix')}

    def test_arbitrary_direct_module_coordinates_bind_actual_captured_artifacts(self):
        rows = self.select(self.declaration, self.native, self.artifacts, self.required)
        self.assertEqual([(row['module'], row['artifact'], row['ordinaryApi']) for row in rows], [
            ('unknown.example.test/chosen', 'go/chosen', 'chosen.Width'),
            ('private.example.test/independent', 'go/independent', 'independent.Prefix')])
        self.assertTrue(all(row['selection'] == 'application-root-direct' for row in rows))

    def test_transitive_presence_cannot_count_as_an_independent_application_selection(self):
        self.declaration['Require'][0]['Indirect'] = True
        with self.assertRaisesRegex(ValueError, 'independent direct'):
            self.select(self.declaration, self.native, self.artifacts, self.required)
        self.declaration['Require'][0]['Indirect'] = False
        self.native['nodes'][1]['indirect'] = True
        with self.assertRaisesRegex(ValueError, 'native selection is not direct'):
            self.select(self.declaration, self.native, self.artifacts, self.required)

    def test_root_association_and_direct_edges_cannot_be_forged(self):
        self.native['module'] = 'another.example.test/application'
        with self.assertRaisesRegex(ValueError, 'root association'):
            self.select(self.declaration, self.native, self.artifacts, self.required)
        self.native['module'] = self.declaration['Module']['Path']
        self.native['edges'].pop()
        with self.assertRaisesRegex(ValueError, 'direct root edge'):
            self.select(self.declaration, self.native, self.artifacts, self.required)

    def test_duplicate_requirement_version_drift_and_sdk_role_do_not_satisfy_the_fixture(self):
        self.declaration['Require'].append(dict(self.declaration['Require'][0]))
        with self.assertRaisesRegex(ValueError, 'ambiguous'):
            self.select(self.declaration, self.native, self.artifacts, self.required)
        self.declaration['Require'].pop()
        self.artifacts[0]['metadata']['version'] = 'v3.2.2'
        with self.assertRaisesRegex(ValueError, 'capture changed'):
            self.select(self.declaration, self.native, self.artifacts, self.required)
        self.artifacts[0]['metadata']['version'] = 'v3.2.1'
        self.artifacts[0]['role'] = 'runtime'
        with self.assertRaisesRegex(ValueError, 'capture changed'):
            self.select(self.declaration, self.native, self.artifacts, self.required)


class PublishedRuntimeEvidence(unittest.TestCase):
    def setUp(self):
        from tools.qualify_go_runtime_dependencies import LIBRARIES, RUNTIME_SOURCES, library_evidence
        self.verify = library_evidence
        root = 'reviewed.example.test/app'
        self.declaration = {'Module': {'Path': root}, 'Require': []}
        self.native = {'module': root, 'nodes': [{'id': 'root', 'path': root, 'main': True}], 'edges': []}
        self.artifacts = []
        for index, (module, (version, _api)) in enumerate(LIBRARIES.items()):
            identifier = 'go/published-' + str(index)
            self.declaration['Require'].append({'Path': module, 'Version': version})
            self.native['nodes'].append({'id': identifier, 'path': module, 'version': version, 'indirect': False})
            self.native['edges'].append({'owner': root, 'dependency': module + '@' + version, 'selected': identifier})
            self.artifacts.append({'id': identifier, 'role': 'application', 'metadata': {
                'module': module, 'version': version, 'effectiveModule': module, 'effectiveVersion': version,
                'assetType': 'selected-module-source'}, 'files': [
                    {'path': name, 'digest': digest(name.encode()), 'size': len(name)}
                    for name in RUNTIME_SOURCES[module]]})
        first, second = list(LIBRARIES.items())
        self.native['edges'].append({'owner': first[0] + '@' + first[1][0],
            'dependency': second[0] + '@' + second[1][0], 'selected': self.artifacts[1]['id']})

    def test_published_runtime_keeps_direct_api_selections_and_the_real_library_edge(self):
        result = self.verify(self.declaration, self.native, self.artifacts)
        self.assertEqual(len(result['runtimeSources']), 4)
        self.assertEqual(result['libraryEdge']['selected'], self.artifacts[1]['id'])
        self.assertEqual([row['selection'] for row in result['applicationLibraries']],
                         ['application-root-direct', 'application-root-direct'])
        self.assertEqual(result['runtimeCallPath'][-1], 'time.NewTimer/Reset/Stop')

    def test_root_presence_without_the_published_runtime_edge_is_insufficient(self):
        self.native['edges'].pop()
        with self.assertRaisesRegex(ValueError, 'library-edge-missing'):
            self.verify(self.declaration, self.native, self.artifacts)

    def test_local_or_replaced_modules_cannot_impersonate_published_runtime_sources(self):
        self.artifacts[0]['metadata']['assetType'] = 'local-module'
        with self.assertRaisesRegex(ValueError, 'original-module-zip'):
            self.verify(self.declaration, self.native, self.artifacts)
        self.artifacts[0]['metadata']['assetType'] = 'selected-module-source'
        self.native['nodes'][1]['replacement'] = {'path': 'another.example.test/fork', 'version': 'v2.5.0'}
        with self.assertRaisesRegex(ValueError, 'original-module-zip'):
            self.verify(self.declaration, self.native, self.artifacts)
        self.native['nodes'][1]['replacement'] = None
        self.artifacts[0]['metadata']['effectiveVersion'] = 'v2.5.1'
        with self.assertRaisesRegex(ValueError, 'original-module-zip'):
            self.verify(self.declaration, self.native, self.artifacts)

    def test_missing_or_ambiguous_timer_source_cannot_satisfy_runtime_evidence(self):
        source = self.artifacts[1]['files'].pop()
        with self.assertRaisesRegex(ValueError, 'source-not-captured'):
            self.verify(self.declaration, self.native, self.artifacts)
        self.artifacts[1]['files'].extend([source, source])
        with self.assertRaisesRegex(ValueError, 'source-not-captured'):
            self.verify(self.declaration, self.native, self.artifacts)


class PublishedRuntimePreparation(unittest.TestCase):
    def test_fresh_project_is_configured_before_published_module_capture(self):
        from unittest.mock import patch
        from tools import qualify_go_runtime_dependencies as qualification
        from tools.rust_capsule_project import ROOT
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / 'qualification'
            compiler = Path(temporary) / 'go'
            compiler.write_bytes(b'not-executed')
            original = ROOT / 'sdk/go-guest/runtime/published-conformance'
            captured = []

            def inspect(project, go):
                self.assertEqual(go, compiler.resolve())
                files = snapshot(project)
                document, _lock, _pins = validate(files)
                self.assertEqual(document['world'], 'tests:caller/service@1.0.0')
                self.assertEqual(document['runtimeProfile'], qualification.INITIALIZER_PROFILE)
                self.assertEqual(files['src/main.go'], (original / 'main.go').read_bytes())
                self.assertEqual(files['wit/world.wit'], (original / 'world.wit').read_bytes())
                self.assertNotIn('latent.dependencies.json', files)
                captured.append(project)
                raise ValueError('test-stops-before-acquisition')

            with patch.object(qualification.shutil, 'which', return_value=str(compiler)), \
                    patch.object(qualification, 'capture', side_effect=inspect), \
                    patch.object(qualification, 'run_bounded') as command:
                with self.assertRaisesRegex(ValueError, '^test-stops-before-acquisition$'):
                    qualification.qualify(output)
                command.assert_not_called()
            self.assertEqual(captured, [output / 'project'])
            failed = json.loads((output / 'GO-ACTIVATION-FAILED.json').read_bytes())
            self.assertEqual(failed, {'status': 'failed', 'reason': 'test-stops-before-acquisition'})
            self.assertFalse((output / 'GO-ACTIVATION-COMPILE.json').exists())

    def test_existing_output_and_receipts_remain_exclusive_create(self):
        from unittest.mock import patch
        from tools import qualify_go_runtime_dependencies as qualification
        from tools.rust_capsule_project import write_json
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            marker = output / 'GO-ACTIVATION-COMPILE.json'
            write_json(marker, {'retained': True})
            before = snapshot(output)
            with patch.object(qualification, 'create') as create_project, \
                    patch.object(qualification, 'capture') as acquire:
                with self.assertRaises(FileExistsError):
                    qualification.qualify(output)
                create_project.assert_not_called()
                acquire.assert_not_called()
            with self.assertRaises(FileExistsError):
                write_json(marker, {'retained': False})
            self.assertEqual(snapshot(output), before)


if __name__ == '__main__':
    unittest.main()
