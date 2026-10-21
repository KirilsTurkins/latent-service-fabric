"""Authority, original-source and compiler-owned root projection boundaries."""
import copy
from pathlib import Path
import shutil
import tempfile
import unittest

from tools import rust_wasi_http_profile as profile
from tools import rust_wasi_http_root as root
from tools import rust_wasi_http_io as io


def value_graph():
    return {
        'worlds': [{'name': 'root', 'imports': {}, 'exports': {
            'interface-0': {'interface': {'id': 0}}}}],
        'packages': [{'name': 'outside:varied-client@1.2.3'}],
        'interfaces': [{'package': 0, 'name': 'api', 'types': {}, 'functions': {
            'request': {'name': 'request', 'kind': 'freestanding',
                'params': [{'name': 'url', 'type': 'string'}], 'result': 0}}}],
        'types': [{'name': None, 'owner': None, 'kind': {
            'result': {'ok': 'string', 'err': 'string'}}}],
    }


class OriginalSourceAndAuthority(unittest.TestCase):
    def test_encoder_can_only_process_exact_pinned_metadata_and_keeps_code_and_other_sections(self):
        from tools.dotnet_guest.internal_io import encoded_integer as enc
        def text(value):
            body = value.encode()
            return enc(len(body)) + body
        def section(kind, body):
            return bytes([kind]) + enc(len(body)) + body
        def custom(name, body):
            return section(0, text(name) + body)
        def producers(extra=()):
            values = [('rustc', '1.97.1 (8bab26f4f 2026-07-14)'), *extra]
            return enc(2) + text('language') + enc(1) + text('Rust') + text('') + text('processed-by') + enc(len(values)) + b''.join(text(k)+text(v) for k, v in values)
        marker = 'component-type:wit-bindgen:0.62.0:latent:rust-http-runtime@0.1.0:client:encoded world'
        header = b'\0asm\x01\0\0\0'
        retained = section(10, b'code-control') + custom('target_features', b'features-control')
        original = header + retained + custom(marker, b'original-wit-control') + custom('producers', producers())
        encoded = header + retained + custom('producers', producers([
            ('wit-component', '0.259.0'), ('wit-bindgen-rust', '0.62.0')]))
        self.assertTrue(profile.verify_compiled_core(original, [encoded])['allNonEncoderMetadataSectionsExact'])
        self.assertTrue(profile.verify_compiled_core(original, [original])['originalCoreExact'])
        for changed in (encoded.replace(b'code-control', b'code-altered'),
                encoded.replace(b'features-control', b'features-altered'),
                encoded.replace(b'0.259.0', b'0.258.0'), encoded + custom(marker, b'unexpected'),
                encoded + custom('component-type:unknown', b'unexpected')):
            with self.subTest(changed=changed), self.assertRaises(ValueError):
                profile.verify_compiled_core(original, [changed])
        with self.assertRaisesRegex(ValueError, 'executable-or-metadata-drift'):
            profile.verify_compiled_core(original, [encoded, encoded])

    def test_whole_original_files_and_manifest_are_authenticated(self):
        self.assertEqual(len(profile.validate_assets()), 12)
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            copied = directory/'sdk/wasi-http-runtime'
            shutil.copytree(profile.ROOT/'sdk/wasi-http-runtime', copied)
            original = copied/'wit/deps/http.wit'
            original.write_bytes(original.read_bytes() + b'\n')
            with self.assertRaisesRegex(ValueError, 'original-byte-drift'):
                profile.validate_assets(directory)
            manifest = copied/'upstream-source.json'
            manifest.write_bytes(manifest.read_bytes() + b'\n')
            with self.assertRaisesRegex(ValueError, 'original-manifest-drift'):
                profile.validate_assets(directory)

    def test_only_eight_internal_io_declarations_may_differ_from_whole_original(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            copied = directory/'sdk/wasi-http-runtime'
            shutil.copytree(profile.ROOT/'sdk/wasi-http-runtime', copied)
            original = (copied/'upstream/wit/deps/io.wit').read_bytes()
            selected = copied/'wit/deps/io.wit'
            self.assertEqual(selected.read_bytes(), profile.selected_io(original))
            self.assertEqual(selected.read_bytes().count(b': async func('), 8)
            self.assertEqual(len(profile.validate_assets(directory)), 12)
            selected.write_bytes(selected.read_bytes().replace(b'    read: func(', b'    read: async func('))
            with self.assertRaisesRegex(ValueError, 'selected-io-projection-drift'):
                profile.validate_assets(directory)

    def test_linker_may_eliminate_only_host_import_members_without_changing_any_export(self):
        reference = {'worlds': [{'name': 'client', 'imports': {}, 'exports': {}}],
            'interfaces': [], 'packages': [], 'types': []}
        for direction, identities in (('imports', profile.AUTHORITY),
                ('exports', profile.EXTERNAL | {profile.RETIREMENT})):
            for identity in sorted(identities):
                package, interface = identity.split('/', 1)
                name, version = interface.split('@')
                index = len(reference['interfaces'])
                reference['packages'].append({'name': package + '@' + version})
                functions = {key: {'name': key, 'kind': 'freestanding',
                    'params': [{'name': 'value', 'type': 'u32'}], 'result': None,
                    'stability': {'stable': {'since': '0.2.0'}}}
                    for key in ('used', 'unused')}
                if identity == profile.RETIREMENT:
                    functions = {'drain': {'name': 'drain', 'kind': 'async-freestanding',
                        'params': [], 'result': None}}
                reference['interfaces'].append({'name': name, 'package': index,
                    'types': {}, 'functions': functions})
                reference['worlds'][0][direction][str(index)] = {'interface': {'id': index}}
        actual = copy.deepcopy(reference)
        for interface in actual['interfaces']:
            for function in interface['functions'].values():
                function.pop('stability', None)
        for row in actual['worlds'][0]['imports'].values():
            del actual['interfaces'][row['interface']['id']]['functions']['unused']
        self.assertTrue(profile.validate_adapter(reference, actual)['emittedImportsAreExactSubsets'])
        imports = list(actual['worlds'][0]['imports'].values())
        first = actual['interfaces'][imports[0]['interface']['id']]
        first['functions']['unknown'] = copy.deepcopy(first['functions']['used'])
        with self.assertRaisesRegex(ValueError, 'unknown-or-empty-import-member'):
            profile.validate_adapter(reference, actual)
        del first['functions']['unknown']
        first['functions']['used']['params'][0]['type'] = 'u64'
        with self.assertRaisesRegex(ValueError, 'original-function-drift'):
            profile.validate_adapter(reference, actual)
        first['functions']['used']['params'][0]['type'] = 'u32'
        exported = next(row for row in actual['worlds'][0]['exports'].values()
            if 'unused' in actual['interfaces'][row['interface']['id']]['functions'])
        del actual['interfaces'][exported['interface']['id']]['functions']['unused']
        with self.assertRaisesRegex(ValueError, 'exact-type-or-function-set'):
            profile.validate_adapter(reference, actual)

    def test_renumbered_option_and_tuple_references_keep_nominal_payload_types(self):
        first = {'packages': [{'name': 'outside:contract@1.0.0'}],
            'interfaces': [{'name': 'api', 'package': 0}], 'types': [
                {'name': 'token', 'owner': {'interface': 0}, 'kind': {
                    'record': {'fields': [{'name': 'id', 'type': 'u64'}]}}},
                {'name': None, 'owner': None, 'kind': {'option': 0}},
                {'name': None, 'owner': None, 'kind': {'tuple': {'types': [0, 1]}}}]}
        second = copy.deepcopy(first)
        second['types'].insert(0, {'name': 'unused', 'owner': None, 'kind': {'type': 'u32'}})
        second['types'][2]['kind']['option'] = 1
        second['types'][3]['kind']['tuple']['types'] = [1, 2]
        expected = profile.shape(first, 2, type_index=True)
        self.assertEqual(expected, profile.shape(second, 3, type_index=True))
        second['types'][1]['kind']['record']['fields'][0]['type'] = 'u32'
        self.assertNotEqual(expected, profile.shape(second, 3, type_index=True))
        second['types'][1]['kind']['record']['fields'][0]['type'] = 'u64'
        second['packages'][0]['name'] = 'outside:other-owner@1.0.0'
        self.assertNotEqual(expected, profile.shape(second, 3, type_index=True))
        with self.assertRaisesRegex(ValueError, 'depth-or-work-bound'):
            profile.shape({'types': [{'name': None, 'kind': {'option': 0}}]}, 0, type_index=True)

    def test_emission_never_grants_authority_or_aliases_versions(self):
        declared, emitted = sorted(profile.AUTHORITY), sorted(profile.EXTERNAL)
        self.assertTrue(profile.select(declared, emitted))
        for missing in declared:
            with self.subTest(missing=missing), self.assertRaisesRegex(ValueError, 'requires-explicit'):
                profile.select([name for name in declared if name != missing], emitted)
        for changed in (emitted[:-1], [*emitted, emitted[0]],
                [name.replace('@0.2.12', '@0.2.2') for name in emitted]):
            with self.subTest(changed=changed), self.assertRaises(ValueError):
                profile.select(declared, changed)
        for forbidden in (emitted[0], profile.RETIREMENT):
            with self.assertRaisesRegex(ValueError, 'ambient-or-private'):
                profile.select([*declared, forbidden], emitted)
        self.assertFalse(profile.select([], []))


class CompilerRoot(unittest.TestCase):
    def test_compiler_lock_keeps_exact_captured_sdk_closure_and_refuses_ambiguity(self):
        original = b'''version = 4
[[package]]
name = "wit-bindgen"
version = "0.62.0"
source = "registry+https://example.invalid/index"
checksum = "unchanged-public-control"
dependencies = ["macro 1.0.0"]
[[package]]
name = "macro"
version = "1.0.0"
[[package]]
name = "application-only"
version = "1.0.0"
'''
        selected = root.compiler_lock(original, 'lsf-owned-http-root-'+'a'*16)
        self.assertIn(b'checksum = "unchanged-public-control"', selected)
        self.assertIn(b'name = "macro"', selected)
        self.assertNotIn(b'application-only', selected)
        self.assertIn(b'dependencies = ["wit-bindgen"]', selected)
        with self.assertRaisesRegex(ValueError, 'missing-or-ambiguous'):
            root.compiler_lock(original.replace(b'macro 1.0.0', b'absent 1.0.0'), 'lsf-owned-http-root-'+'a'*16)
        with self.assertRaisesRegex(ValueError, 'captured-bindgen'):
            root.compiler_lock(original.replace(b'0.62.0', b'0.61.0'), 'lsf-owned-http-root-'+'a'*16)

    def test_varied_pure_value_api_keeps_actual_result_until_drain(self):
        graph = value_graph()
        source, calls = root.forwarding_source(graph)
        self.assertIn(b'outside::varied_client::api::request(&url)', source)
        self.assertEqual(source.count(b'let result ='), 1)
        self.assertEqual(source.count(b'owner::drain();'), 1)
        self.assertLess(source.index(b'let result ='), source.index(b'owner::drain();'))
        self.assertLess(source.index(b'owner::drain();'), source.index(b'\n        result'))
        self.assertNotIn(b'unwrap', source)
        self.assertNotIn(b'waki', source)
        self.assertNotIn(b'golem', source)
        self.assertEqual(calls, [{'interface': 'outside:varied-client/api@1.2.3',
            'function': 'request', 'asyncPublic': False, 'drainBeforeReturningValueOrError': True}])
        original = 'package root:component;\nworld root {\n  export outside:varied-client/api@1.2.3;\n}\n'
        selected = root.forwarding_wit(original, graph)
        self.assertIn(b'import outside:varied-client/api@1.2.3;', selected)
        self.assertIn(b'export outside:varied-client/api@1.2.3;', selected)
        self.assertIn(b'import '+profile.RETIREMENT.encode()+b';', selected)
        self.assertEqual(graph, value_graph())

    def test_resources_unknown_abis_and_unbounded_types_refuse(self):
        original = value_graph()
        for kind in ({'own': 0}, {'borrow': 0}, {'future': 'string'}, {'type': 0}):
            graph = copy.deepcopy(original)
            graph['types'][0]['kind'] = kind
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                root.forwarding_source(graph)
        graph = copy.deepcopy(original)
        graph['interfaces'][0]['functions']['request']['kind'] = {'method': 0}
        with self.assertRaisesRegex(ValueError, 'kind-unsupported'):
            root.forwarding_source(graph)
        graph = copy.deepcopy(original)
        graph['types'][0]['name'] = 'opaque'
        with self.assertRaisesRegex(ValueError, 'named-or-resource'):
            root.forwarding_source(graph)
        graph = {'types': [{'name': None, 'kind': {'list': index+1}} for index in range(40)]}
        graph['types'].append({'name': None, 'kind': {'list': 'u8'}})
        with self.assertRaisesRegex(ValueError, 'depth'):
            root.rust_type(graph, 0)

    def test_private_projection_never_changes_public_exports_or_unrelated_types(self):
        graph = value_graph()
        graph['packages'].append({'name': 'latent:rust-http-retirement@0.1.0'})
        graph['interfaces'].append({'name': 'owner', 'package': 1, 'types': {}, 'functions': {
            'drain': {'name': 'drain', 'kind': 'freestanding', 'params': [], 'result': None}}})
        graph['worlds'][0]['imports'] = {'interface-1': {'interface': {'id': 1}}}
        adapter = copy.deepcopy(graph)
        adapter['worlds'][0]['imports'] = {}
        adapter['worlds'][0]['exports'] = {'interface-1': {'interface': {'id': 1}}}
        adapter['interfaces'][1]['functions']['drain']['kind'] = 'async-freestanding'
        targets = {profile.RETIREMENT: frozenset({'drain'})}
        expected, selected = io.projection(graph, adapter, targets)
        restored = copy.deepcopy(expected)
        restored['interfaces'][1]['functions']['drain']['kind'] = 'freestanding'
        self.assertEqual(restored, graph)
        self.assertEqual(selected, {profile.RETIREMENT: ['drain']})
        self.assertEqual(expected['worlds'][0]['exports'], graph['worlds'][0]['exports'])
        adapter['interfaces'][1]['functions']['drain']['params'] = [{'name': 'injected', 'type': 'u64'}]
        with self.assertRaisesRegex(ValueError, 'function-shape'):
            io.projection(graph, adapter, targets)
        with self.assertRaisesRegex(ValueError, 'projection-targets'):
            io.projection(graph, adapter, {'outside:varied-client/api@1.2.3': {'request'}})
