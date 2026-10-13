"""Exact parsed public types and explicit selection; no runtime qualification."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import unittest

from tools.typescript_guest import fetch_profile as fetch, runtime_profile as runtime
from tools.typescript_guest.activation_engine import engine_input_paths
from tools.typescript_guest.compiler import Compiler

ROOT = Path(__file__).resolve().parents[2]
WORLD = 'lsf:typescript-probe/capsule@1.0.0'
SELECTED = runtime.scoped_selected_world(WORLD)


def graphs():
    value = json.loads((ROOT/'tools/tests/fixtures/typescript_fetch/profile-graphs.json').read_bytes())
    assert value['parser'] == 'wasm-tools1.254.0'
    for name, expected in value['sources'].items():
        assert hashlib.sha256((ROOT/name).read_bytes()).hexdigest() == expected
    return value


class TypeScriptFetchProfileTests(unittest.TestCase):
    def test_explicit_fetch_candidate_preserves_synchronous_default_and_requires_real_tools(self):
        self.assertEqual(runtime.selected_profile({}), runtime.SYNC_PROFILE)
        self.assertEqual(runtime.selected_profile({'runtimeProfile': fetch.FETCH_PROFILE}), fetch.FETCH_PROFILE)
        self.assertEqual(runtime.selection(fetch.FETCH_PROFILE)['qualification'], 'unknown')
        with self.assertRaisesRegex(ValueError, 'requires actual source-bound compiler inputs'):
            Compiler(Path('unused'), None, {}, runtime_profile=fetch.FETCH_PROFILE)

    def test_complete_sdk_http_body_added_without_changing_application_contract(self):
        value = graphs()
        observed = fetch.check_binding_world(value['original'], value['binding'], value['http'], WORLD, SELECTED)
        self.assertEqual((observed['qualification'], observed['apiSupport'], observed['authority']),
                         ('unknown', 'not-evaluated', 'none'))
        self.assertEqual(set(runtime.public_graph(value['binding'], SELECTED)['imports']) -
                         set(runtime.public_graph(value['original'], WORLD)['imports']), {fetch.HTTP_INTERFACE})

    def test_engine_activation_and_clocks_are_not_duplicated_as_application_bindings(self):
        value = graphs()
        observed = runtime.check_derived_world(value['binding'], value['runtime'], value['activation'],
            SELECTED, selected_world=SELECTED, clock=value['clock'])
        self.assertTrue(observed['publicExportsAndOriginalImportsPreserved'])
        self.assertNotIn(runtime.ACTIVATION_INTERFACE, runtime.public_graph(value['binding'], SELECTED)['imports'])

    def test_borrowed_body_changed_to_owned_body_cannot_shadow_sdk_contract(self):
        value = graphs()
        modified = deepcopy(value['binding'])
        handle = next(item for item in modified['types'] if 'handle' in item['kind']
                      and 'borrow' in item['kind']['handle'])
        handle['kind']['handle'] = {'own': handle['kind']['handle']['borrow']}
        with self.assertRaisesRegex(ValueError, 'changed-application-contract'):
            fetch.check_binding_world(value['original'], modified, value['http'], WORLD, SELECTED)

    def test_native_async_read_changed_to_synchronous_is_rejected(self):
        value = graphs()
        modified = deepcopy(value['binding'])
        interface = next(item for item in modified['interfaces'] if item['name'] == 'streaming')
        interface['functions']['read']['kind'] = 'freestanding'
        with self.assertRaisesRegex(ValueError, 'changed-application-contract'):
            fetch.check_binding_world(value['original'], modified, value['http'], WORLD, SELECTED)

    def test_original_export_parameter_change_is_rejected(self):
        value = graphs()
        modified = deepcopy(value['binding'])
        interface = next(item for item in modified['interfaces'] if item['name'] == 'probe')
        interface['functions']['run']['params'][0]['type'] = 'u32'
        with self.assertRaisesRegex(ValueError, 'changed-application-contract'):
            fetch.check_binding_world(value['original'], modified, value['http'], WORLD, SELECTED)

    def test_fetch_selection_binds_exact_sdk_globals_and_operation_capture_sources(self):
        names = set(engine_input_paths(fetch.FETCH_PROFILE))
        self.assertLessEqual(len(names), 64)
        self.assertTrue({'tools/typescript_guest/operation_capture.mjs',
            'tools/typescript_guest/fetch_startup.mjs', 'sdk/typescript-guest/runtime/http-fetch.mjs',
            'sdk/typescript-guest/activation/fetch-globals.d.ts', 'wit/platform/http-v3/package.wit'} <= names)
        self.assertNotIn('sdk/typescript-guest/runtime/http-fetch.mjs',
                         engine_input_paths(runtime.IMPORT_PROFILE))

    def test_editable_fetch_project_captures_sdk_source_and_rejects_a_local_override(self):
        import tempfile
        from tools.rust_capsule_project import snapshot, inventory
        from tools.typescript_guest.project import create, validate
        with tempfile.TemporaryDirectory() as temporary:
            path = create(Path(temporary)/'fetch', 'greeting', 'fetch-control', runtime_profile=fetch.FETCH_PROFILE)
            files = snapshot(path)
            validate(files)
            source = 'vendor/lsf/sdk/typescript-guest/runtime/http-fetch.mjs'
            self.assertEqual(files[source], (ROOT/source.removeprefix('vendor/lsf/')).read_bytes())
            files[source] += b'\n// application override\n'
            with self.assertRaisesRegex(ValueError, 'SDK source lock'):
                validate(files)
            lock = json.loads(files['sdk-lock.json'])
            lock['sdk'] = json.loads(inventory({name.removeprefix('vendor/lsf/'): raw
                for name, raw in files.items() if name.startswith('vendor/lsf/')}))
            files['sdk-lock.json'] = json.dumps(lock).encode()
            with self.assertRaisesRegex(ValueError, 'fetch runtime differs'):
                validate(files)
