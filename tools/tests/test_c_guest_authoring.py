"""Fast contract tests; the C/node qualification gates separately execute code."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import tempfile
import unittest

from tools.c_guest.bindings import aliases, check_lock, digest
from tools.c_guest.compiler import ROOT, safe_output
from tools.c_guest.metadata import Projection, canonical
from tools.c_guest.project import closed_json, inventory, load
from tools.c_guest_authoring import create, TEMPLATES
from tools.c_guest.node import expected


def resolved():
    return {
        'worlds': [{'name': 'component', 'imports': {}, 'exports': {'interface-0': {'interface': {'id': 0}}}, 'package': 0}],
        'interfaces': [{'name': 'api', 'types': {'parcel': 1, 'error': 2}, 'functions': {
            'quote': {'name': 'quote', 'kind': 'freestanding', 'params': [{'name': 'input', 'type': 1}], 'result': 3}}, 'package': 0}],
        'types': [
            {'name': None, 'kind': {'list': 'string'}, 'owner': None},
            {'name': 'parcel', 'kind': {'record': {'fields': [{'name': 'id', 'type': 'u64'}, {'name': 'labels', 'type': 0}]}}, 'owner': {'interface': 0}},
            {'name': 'error', 'kind': {'variant': {'cases': [{'name': 'invalid', 'type': 'string'}, {'name': 'overflow', 'type': None}]}}, 'owner': {'interface': 0}},
            {'name': None, 'kind': {'result': {'ok': 'u64', 'err': 2}}, 'owner': None}],
        'packages': [{'name': 'examples:authoring@1.0.0', 'interfaces': {'api': 0}, 'worlds': {'component': 0}}],
    }


class CGuestAuthoringTests(unittest.TestCase):
    def test_projection_matches_runtime_named_records_results_and_exact_digests(self):
        data, exports, imports = Projection(resolved()).contracts('examples:authoring/component@1.0.0')
        self.assertEqual(exports, ['examples:authoring/api@1.0.0'])
        self.assertEqual(imports, [])
        descriptor = json.loads(data)['contracts'][0]
        identity = descriptor.pop('digest')
        self.assertEqual(identity, digest(canonical(descriptor)))
        interface = descriptor['interfaces'][0]
        identity = interface.pop('digest')
        self.assertEqual(identity, digest(canonical(interface)))
        function = interface['functions'][0]
        self.assertEqual(function['parameters'][0]['value_type'], {'Record': 'parcel'})
        self.assertEqual(function['results'][0]['value_type'], {'Result': {'ok': 'U64', 'error': {'Variant': 'error'}}})

    def test_projection_rejects_recursive_hidden_unsupported_and_unknown_types(self):
        for kind in ({'future': 'string'}, {'resource': {}}, {'flags': []}, {'option': 1}):
            value = resolved()
            value['types'][0]['kind'] = kind
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                Projection(value).contracts('examples:authoring/component@1.0.0')
        for value in (True, -1, 100, 'pointer', None):
            with self.subTest(value=value), self.assertRaises(ValueError):
                Projection(resolved()).value(value)

    def test_projection_handles_primitive_optional_tuple_and_empty_results(self):
        value = resolved()
        value['types'].extend([
            {'name': None, 'kind': {'option': 'u64'}},
            {'name': None, 'kind': {'tuple': {'types': ['bool', 's64', 'string']}}},
            {'name': None, 'kind': {'result': {'ok': None, 'err': None}}},
        ])
        projection = Projection(value)
        self.assertEqual(projection.value(4), {'Option': 'U64'})
        self.assertEqual(projection.value(5), {'Tuple': ['Bool', 'S64', 'String']})
        self.assertEqual(projection.value(6), {'Result': {'ok': None, 'error': None}})
        with self.assertRaises(ValueError):
            projection.contracts('examples:authoring/missing@1.0.0')

    def test_no_raw_function_or_unsupported_capability_import_is_accepted(self):
        for imports in ({'raw': {'function': {}}}, {'resource': {'type': 0}}):
            value = resolved()
            value['worlds'][0]['imports'] = imports
            with self.assertRaises(ValueError):
                Projection(value).contracts('examples:authoring/component@1.0.0')
        value = resolved()
        value['worlds'][0]['imports'] = {'interface-0': {'interface': {'id': 0}}}
        with self.assertRaises(ValueError):
            Projection(value).contracts('examples:authoring/component@1.0.0')

    def test_aliases_only_derive_real_current_version_names(self):
        header = 'latent_http_0_2_0_client_send LATENT_HTTP_0_3_0_STREAMING_HTTP_ERROR_PERMISSION_DENIED latent_blob_0_1_0_blob_read'
        value = aliases(header)
        self.assertIn('#define latent_http_client_send latent_http_0_2_0_client_send', value)
        self.assertIn('#define LATENT_HTTP_STREAMING_HTTP_ERROR_PERMISSION_DENIED LATENT_HTTP_0_3_0_STREAMING_HTTP_ERROR_PERMISSION_DENIED', value)
        self.assertNotIn('#define latent_blob_blob_read', value)
        with self.assertRaises(ValueError):
            aliases('latent_http_client_send latent_http_0_2_0_client_send')

    def test_binding_lock_requires_explicit_update_and_rejects_drift(self):
        with tempfile.TemporaryDirectory() as directory:
            lock = Path(directory) / 'lock.json'
            actual = {'formatVersion': 1, 'outputs': {'probe.h': digest(b'generated')}}
            with self.assertRaises(ValueError):
                check_lock(lock, actual)
            check_lock(lock, actual, update=True)
            check_lock(lock, actual)
            with self.assertRaises(ValueError):
                check_lock(lock, {'formatVersion': 1, 'outputs': {}})
            self.assertEqual(json.loads(lock.read_text()), actual)

    def test_new_projects_contain_only_selected_source_and_closed_configuration(self):
        with tempfile.TemporaryDirectory() as directory:
            for name in TEMPLATES:
                path = Path(directory) / name
                create(path, name)
                self.assertEqual({p.relative_to(path).as_posix() for p in path.rglob('*') if p.is_file()},
                                 {'component.c', 'c-project.json', 'wit/world.wit'})
                _, config, sources = load(path)
                self.assertEqual(config['name'], name)
                self.assertEqual(sources, [path / 'component.c'])
                config['grant'] = 'forged'
                (path / 'c-project.json').write_text(json.dumps(config))
                with self.assertRaises(ValueError):
                    load(path)
                with self.assertRaises(ValueError):
                    create(path, name)

    def test_nonportable_duplicate_linked_and_oversized_inputs_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'project'
            create(path, 'greeting')
            original = closed_json(path / 'c-project.json')
            for sources in (['../component.c'], ['./component.c'], ['/component.c'], ['component.c', 'component.c']):
                config = dict(original, sources=sources)
                (path / 'c-project.json').write_text(json.dumps(config))
                with self.subTest(sources=sources), self.assertRaises(ValueError):
                    load(path)
            (path / 'c-project.json').write_text(json.dumps(original))
            (path / 'component.c').rename(path / 'original.c')
            try:
                (path / 'component.c').symlink_to('original.c')
            except OSError:
                return  # Windows without link privileges still executes other boundary cases.
            with self.assertRaises(ValueError):
                load(path)

    def test_output_overlap_and_duplicate_json_never_overwrite_inputs(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            with self.assertRaises(ValueError):
                safe_output(path)
            with self.assertRaises(ValueError):
                safe_output(ROOT)
            source = path / 'duplicate.json'
            source.write_text('{"formatVersion":1,"formatVersion":2}')
            with self.assertRaises(ValueError):
                closed_json(source)
            source.write_text('{"value":NaN}')
            with self.assertRaises(ValueError):
                closed_json(source)

    def test_source_snapshots_change_with_author_code_but_ignore_python_bytecode(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'project'
            create(path, 'greeting')
            before = inventory(path)
            (path / '__pycache__').mkdir()
            (path / '__pycache__/ignored.pyc').write_bytes(b'cache')
            self.assertEqual(before, inventory(path))
            with (path / 'component.c').open('a') as output:
                output.write('\n/* changed source */\n')
            self.assertNotEqual(before, inventory(path))

    def test_shipping_expectations_preserve_full_width_integer_arithmetic(self):
        value = expected('shipping', [{'grams': '9007199254740993', 'express': True, 'destination': 'LV'}])
        self.assertEqual(value, [{'ok': {'total-cents': '18014398509483486', 'currency': 'EUR', 'eta-days': 1}}])
        self.assertEqual(expected('word-count', ['a\tb\nc']), [{'ok': '3'}])


if __name__ == '__main__':
    unittest.main()
