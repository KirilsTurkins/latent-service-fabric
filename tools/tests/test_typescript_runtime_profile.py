"""Selection/provenance and actual-parser public-contract controls.

These do not substitute for actual source-built engine or signed guests.
"""
from __future__ import annotations
import copy
import hashlib
import json
import contextlib
import io
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from tools.typescript_guest import runtime_profile as runtime

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = Path(__file__).parent/'fixtures/typescript_runtime_profile'
WORLD = 'lsf:typescript-probe/capsule@1.0.0'


def actual_graph(name):
    value = json.loads((FIXTURES/(name+'.json')).read_bytes())
    assert value['parser'] == 'wasm-tools1.254.0'
    assert value['originalSourceSha256'] == hashlib.sha256(
        (ROOT/'sdk/typescript-guest/probes/world.wit').read_bytes()).hexdigest()
    assert value['activationSourceSha256'] == hashlib.sha256(
        (ROOT/'wit/platform/activation-runtime/package.wit').read_bytes()).hexdigest()
    return value['graph']


class TypeScriptRuntimeProfileTests(unittest.TestCase):
    def test_candidate_project_captures_native_source_without_changing_application_or_limits(self):
        from tools.typescript_guest.project import create, validate
        from tools.rust_capsule_project import snapshot
        from tools.typescript_guest.activation_engine import NATIVE_SOURCES
        with tempfile.TemporaryDirectory() as owned:
            ordinary = create(Path(owned)/'ordinary', 'greeting', 'same-name')
            candidate = create(Path(owned)/'candidate', 'greeting', 'same-name', runtime_profile=runtime.ASYNC_PROFILE)
            old, new = snapshot(ordinary), snapshot(candidate)
            before = json.loads(old['capsule-project.json'])
            after = json.loads(new['capsule-project.json'])
            self.assertNotIn('runtimeProfile', before)
            self.assertEqual(after['runtimeProfile'], runtime.ASYNC_PROFILE)
            self.assertEqual(before['limits'], after['limits'])
            self.assertEqual(old['src/main.ts'], new['src/main.ts'])
            self.assertEqual(old['wit/world.wit'], new['wit/world.wit'])
            for name in NATIVE_SOURCES:
                path = 'vendor/lsf/sdk/typescript-guest/activation/'+name
                self.assertNotIn(path, old)
                self.assertEqual(new[path], (ROOT/path.removeprefix('vendor/lsf/')).read_bytes())
            validate(new)

    def test_cli_forwards_exact_candidate_engine_inputs(self):
        from tools import typescript_capsule
        with mock.patch.object(typescript_capsule, 'build', return_value=Path('result')) as build, contextlib.redirect_stdout(io.StringIO()):
            result = typescript_capsule.main(['build', 'project', '--tools', 'compiler', '--output', 'result',
                '--repository', 'https://example.com/source', '--runtime-engine', 'selected.wasm',
                '--runtime-engine-receipt', 'engine.json'])
        self.assertEqual(result, 0)
        self.assertEqual(build.call_args.kwargs['runtime_engine'], Path('selected.wasm'))
        self.assertEqual(build.call_args.kwargs['runtime_engine_receipt'], Path('engine.json'))

    def test_npm_explicit_candidate_preserves_conditions_without_promoting_api(self):
        from tools.typescript_application_dependencies import selection
        selected = selection({'runtimeProfile': runtime.ASYNC_PROFILE, 'conditions': ['private']})
        self.assertEqual(selected['runtimeProfile'], runtime.ASYNC_PROFILE)
        self.assertEqual(selected['conditions'], ['private'])
        self.assertEqual(runtime.selection(selected['runtimeProfile'])['apiSupport'], 'not-evaluated')

    def test_default_ordinary_selection_is_sync(self):
        self.assertEqual(runtime.selected_profile({}), runtime.SYNC_PROFILE)

    def test_explicit_candidate_does_not_certify_api(self):
        profile = runtime.selected_profile({'runtimeProfile': runtime.ASYNC_PROFILE})
        self.assertEqual(runtime.selection(profile)['qualification'], 'unknown')
        self.assertEqual(runtime.selection(profile)['apiSupport'], 'not-evaluated')
        self.assertEqual(runtime.selection(profile)['authority'], 'none')

    def test_project_and_captured_profile_must_match(self):
        with self.assertRaisesRegex(ValueError, 'capture-mismatch'):
            runtime.selected_profile({'runtimeProfile': runtime.ASYNC_PROFILE},
                {'selection': {'runtimeProfile': runtime.SYNC_PROFILE}})

    def test_unknown_runtime_cannot_be_selected(self):
        with self.assertRaisesRegex(ValueError, 'unsupported-typescript-runtime'):
            runtime.selected_profile({'runtimeProfile': 'node-everything'})

    def test_unknown_captured_runtime_cannot_be_selected(self):
        with self.assertRaisesRegex(ValueError, 'unsupported-captured'):
            runtime.selected_profile({}, {'selection': {'runtimeProfile': 'unknown'}})

    def test_explicit_null_is_not_an_absent_selection(self):
        with self.assertRaisesRegex(ValueError, 'unsupported-typescript-runtime'):
            runtime.selected_profile({'runtimeProfile': None})
        with self.assertRaisesRegex(ValueError, 'unsupported-captured'):
            runtime.selected_profile({}, {'selection': {'runtimeProfile': None}})

    def engine(self):
        core = b'\x00asm\x01\x00\x00\x00' + b'candidate-input'
        sdk = {'sdk/typescript-guest/activation/native_engine.cpp': b'current source'}
        wit = b'current exact WIT'
        value = {'schemaVersion': runtime.ENGINE_SCHEMA, 'profile': runtime.ASYNC_PROFILE,
            'coreDigest': runtime.digest(core), 'coreBytes': len(core),
            'sdkInputs': [{'path': name, 'digest': runtime.digest(raw), 'size': len(raw)}
                          for name, raw in sdk.items()],
            'runtimeWitDigest': runtime.digest(wit), 'upstream': runtime.SOURCE_PINS,
            'sourceDerivationDigest': runtime.digest(b'source derivation'),
            'buildReceiptDigest': runtime.digest(b'build receipt'),
            'qualification': 'unknown', 'apiSupport': 'not-evaluated', 'inputTrust': 'operator-asserted'}
        return value, core, sdk, wit

    def test_engine_envelope_binds_actual_bytes_and_keeps_unknown(self):
        value, core, sdk, wit = self.engine()
        self.assertEqual(runtime.validate_engine(value, core, sdk, wit)['qualification'], 'unknown')

    def test_engine_replaced_bytes_rejected(self):
        value, core, sdk, wit = self.engine()
        with self.assertRaisesRegex(ValueError, 'core-identity'):
            runtime.validate_engine(value, core+b'changed', sdk, wit)

    def test_engine_stale_sdk_source_rejected(self):
        value, core, sdk, wit = self.engine()
        sdk[next(iter(sdk))] += b'changed'
        with self.assertRaisesRegex(ValueError, 'sdk-source-mismatch'):
            runtime.validate_engine(value, core, sdk, wit)

    def test_engine_stale_runtime_interface_rejected(self):
        value, core, sdk, wit = self.engine()
        with self.assertRaisesRegex(ValueError, 'runtime-wit-mismatch'):
            runtime.validate_engine(value, core, sdk, wit+b'changed')

    def test_engine_declaration_cannot_promote_qualification(self):
        value, core, sdk, wit = self.engine()
        value['qualification'] = 'qualified'
        with self.assertRaisesRegex(ValueError, 'cannot-certify-api'):
            runtime.validate_engine(value, core, sdk, wit)

    def test_wrong_original_sysroot_is_rejected(self):
        value, core, sdk, wit = self.engine()
        value = copy.deepcopy(value)
        value['upstream']['publicSDK30ArchiveDigest'] = runtime.digest(b'SDK29')
        with self.assertRaisesRegex(ValueError, 'upstream-mismatch'):
            runtime.validate_engine(value, core, sdk, wit)

    def test_actual_parser_relocation_preserves_full_public_contract(self):
        value = runtime.check_derived_world(actual_graph('original'), actual_graph('derived'),
                                             actual_graph('activation'), WORLD)
        self.assertTrue(value['publicExportsAndOriginalImportsPreserved'])
        self.assertEqual(value['qualification'], 'unknown')

    def test_actual_parser_nested_record_change_rejected(self):
        graph = actual_graph('derived')
        item = next(item for item in graph['types'] if item['name'] == 'item')
        item['kind']['record']['fields'][1]['type'] = 's64'
        with self.assertRaisesRegex(ValueError, 'public-exports-changed'):
            runtime.check_derived_world(actual_graph('original'), graph, actual_graph('activation'), WORLD)

    def test_original_async_import_kind_change_rejected(self):
        graph = actual_graph('derived')
        host = next(item for item in graph['interfaces'] if item['name'] == 'host')
        host['functions']['echo']['kind'] = 'freestanding'
        with self.assertRaisesRegex(ValueError, 'import-contract-changed'):
            runtime.check_derived_world(actual_graph('original'), graph, actual_graph('activation'), WORLD)

    def test_exact_activation_async_kind_required(self):
        graph = actual_graph('derived')
        activation = next(item for item in graph['interfaces'] if item['name'] == 'activation')
        activation['functions']['timer-next']['kind'] = 'freestanding'
        with self.assertRaisesRegex(ValueError, 'import-contract-changed'):
            runtime.check_derived_world(actual_graph('original'), graph, actual_graph('activation'), WORLD)

    def test_undeclared_import_cannot_survive_derivation(self):
        graph = actual_graph('derived')
        world = runtime.find_world(graph, runtime.SELECTED_WORLD)
        world['imports']['unexpected'] = {'function': {'name': 'unexpected', 'kind': 'freestanding',
                                                   'params': [], 'result': None}}
        with self.assertRaisesRegex(ValueError, 'import-contract-changed'):
            runtime.check_derived_world(actual_graph('original'), graph, actual_graph('activation'), WORLD)

    def test_unknown_type_kind_is_not_name_only_success(self):
        graph = actual_graph('derived')
        item = next(item for item in graph['types'] if item['name'] == 'item')
        item['kind'] = {'unsupported-kind': {}}
        with self.assertRaisesRegex(ValueError, 'unsupported-type-kind'):
            runtime.check_derived_world(actual_graph('original'), graph, actual_graph('activation'), WORLD)

    def test_selected_surface_preserves_exports_and_declares_activation_for_admission(self):
        from tools.rust_capsule_build import package_inputs
        from tools import guest_compatibility_build
        from tools.typescript_guest.project import create
        from tools.rust_capsule_project import snapshot
        with tempfile.TemporaryDirectory() as owned:
            root = Path(owned)
            project = create(root/'project', 'greeting', 'selected-admission', runtime_profile=runtime.ASYNC_PROFILE)
            files = snapshot(project)
            value = json.loads(files['capsule-project.json'])
            value['world'] = runtime.SELECTED_WORLD
            exports = [{'contract': 'examples:greeting/greeting@1.0.0'}]
            surface = {'imports': [runtime.ACTIVATION_INTERFACE], 'exports': exports}
            output = root/'output'
            output.mkdir()
            package_inputs(output, value, surface, files, b'actual-component-bytes')
            manifest = json.loads((output/'capsule.json').read_bytes())
            self.assertEqual(manifest['imports'], [{'contract': runtime.ACTIVATION_INTERFACE, 'optional': False}])
            self.assertEqual(manifest['exports'], exports)
            self.assertEqual(manifest['component']['world'], runtime.SELECTED_WORLD)
            self.assertEqual(manifest['execution']['limits'], value['limits'])
            self.assertEqual(guest_compatibility_build.declared_host_abi(surface), 'lsf-host-abi-phase3-v5')

    def test_native_activation_is_not_synthesized_as_a_second_js_application_import(self):
        runtime.check_application_bindings(actual_graph('original'), WORLD)
        with self.assertRaisesRegex(ValueError, 'engine-owned-activation-interface'):
            runtime.check_application_bindings(actual_graph('derived'), runtime.SELECTED_WORLD)


class TypeScriptAbortSourceTests(unittest.TestCase):
    def test_pinned_timeout_conversion_precedes_signal_graph_allocation(self):
        from tools.typescript_guest.abort_engine import derive_abort_timeout
        raw = (FIXTURES/'original-abort-signal.cpp').read_bytes()
        after, receipt = derive_abort_timeout(raw)
        start = after.index(b'JSObject *AbortSignal::create_with_timeout(')
        end = after.index(b'// https://dom.spec.whatwg.org/#dom-abortsignal-any', start)
        body = after[start:end]
        self.assertLess(body.index(b'timeout_nanoseconds('), body.index(b'create(cx)'))
        self.assertLess(body.index(b'timeout_nanoseconds('), body.index(b'start_timeout_nanoseconds('))
        self.assertNotIn(b'JS::ToNumber(cx, timeout, &ms)', body)
        self.assertNotIn(b'timers::set_timeout(', body)
        self.assertFalse(receipt['supportedAsyncProfile'])
        self.assertFalse(receipt['signedLSFComponentQualified'])

    def test_pinned_abort_reason_event_algorithms_and_other_methods_are_preserved(self):
        from tools.typescript_guest.abort_engine import derive_abort_timeout
        raw = (FIXTURES/'original-abort-signal.cpp').read_bytes()
        after, _ = derive_abort_timeout(raw)
        first = b'bool AbortSignal::run_abort_steps('
        boundary = b'JSObject *AbortSignal::create_with_timeout('
        self.assertEqual(raw[raw.index(first):raw.index(boundary)],
                         after[after.index(first):after.index(boundary)])
        following = b'// https://dom.spec.whatwg.org/#dom-abortsignal-any'
        self.assertEqual(raw[raw.index(following, raw.index(boundary)):],
                         after[after.index(following, after.index(boundary)):])
        self.assertIn(b'DOMException::create(cx, "TimeoutError", "TimeoutError")', after)

    def test_pinned_abort_source_change_is_rejected_before_derivation(self):
        from tools.typescript_guest.abort_engine import derive_abort_timeout
        raw = (FIXTURES/'original-abort-signal.cpp').read_bytes()
        with self.assertRaisesRegex(ValueError, 'unreviewed-original-AbortSignal-source'):
            derive_abort_timeout(raw+b'changed')

    def test_abort_recipe_and_native_sources_are_closed_compiler_inputs(self):
        from tools.typescript_guest.activation_engine import NATIVE_SOURCES, PREIMAGES, engine_input_paths
        from tools.typescript_guest.build import RECIPE
        self.assertIn('native_timeout.h', NATIVE_SOURCES)
        self.assertEqual(PREIMAGES['StarlingMonkey/builtins/web/abort/abort-signal.cpp'],
            hashlib.sha256((FIXTURES/'original-abort-signal.cpp').read_bytes()).hexdigest())
        self.assertIn('tools/typescript_guest/abort_engine.py', RECIPE)
        self.assertEqual(set(engine_input_paths()),
            {'sdk/typescript-guest/activation/'+name for name in NATIVE_SOURCES} |
            {'tools/typescript_guest/'+name for name in (
                'activation_engine.py', 'promise_engine.py', 'timer_engine.py', 'abort_engine.py', 'event_engine.py')})
        for name in NATIVE_SOURCES:
            self.assertIn('sdk/typescript-guest/activation/'+name, RECIPE)

    def test_unrepresentable_timeout_is_explicit_and_never_promotes_qualification(self):
        from tools.typescript_guest.abort_engine import derive_abort_timeout
        _, receipt = derive_abort_timeout((FIXTURES/'original-abort-signal.cpp').read_bytes())
        self.assertEqual(receipt['maximumRepresentableMilliseconds'], (2**64-1)//1000000)
        self.assertEqual(receipt['unrepresentableNanoseconds'], 'explicit-profile-TypeError')
        self.assertEqual(receipt['fractionalMilliseconds'], 'truncate-toward-zero-after-ToNumber')
        self.assertFalse(receipt['supportedAsyncProfile'])
        self.assertFalse(receipt['signedLSFComponentQualified'])


if __name__ == '__main__':
    unittest.main()
