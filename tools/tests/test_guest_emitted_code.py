"""Emitted-byte graph fixtures; these do not qualify library execution."""
import copy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools import guest_emitted_code as emitted
from tools.dev_workflow.common import DevError, digest, encode

SOURCE = digest(b'captured source fixture')
RUNTIME = 'controlled-runtime-v1'
HOST = 'lsf-host-abi-phase3-v5'


def unsigned(value):
    raw = bytearray()
    while value >= 128:
        raw.append((value & 127) | 128); value >>= 7
    raw.append(value)
    return bytes(raw)


def name(value):
    raw = value.encode(); return unsigned(len(raw)) + raw


def section(kind, raw): return bytes([kind]) + unsigned(len(raw)) + raw


def core(bodies, *, imported=True, exports=(1,), start=None, table=False, names=None, data=b''):
    raw = emitted.CORE + section(1, b'\x01\x60\x00\x00')
    if imported: raw += section(2, b'\x01' + name('controlled') + name('unsupported') + b'\x00\x00')
    raw += section(3, unsigned(len(bodies)) + b'\x00' * len(bodies))
    if table: raw += section(4, b'\x01\x70\x01\x01\x01')
    raw += section(7, unsigned(len(exports)) + b''.join(name('run' + str(index)) + b'\x00' + unsigned(index) for index in exports))
    if start is not None: raw += section(8, unsigned(start))
    if table: raw += section(9, b'\x01\x00\x41\x00\x0b\x01\x02')
    raw += section(10, unsigned(len(bodies)) + b''.join(unsigned(len(body) + 1) + b'\x00' + body for body in bodies))
    if data: raw += section(11, data)
    if names:
        raw += section(0, name('name') + section(1, unsigned(len(names)) +
            b''.join(unsigned(index) + name(label) for index, label in names.items())))
    return raw


def analyze(raw, **bindings): return emitted.analyze(raw, SOURCE, RUNTIME, HOST, **bindings)


def by_function(value): return {row['function']: row for row in value['findings']}


def rehash(value):
    value['identity'] = digest(encode({key: item for key, item in value.items() if key != 'identity'}))
    return value


class EmittedGraph(unittest.TestCase):
    def test_direct_calls_are_potentially_reachable_and_unselected_core_function_is_unreachable(self):
        value = analyze(core([b'\x10\x00\x0b', b'\x01\x0b']))
        rows = by_function(value)
        self.assertEqual(rows[0]['state'], 'potentially-reachable')
        self.assertEqual(rows[0]['phases'], ['invocation'])
        self.assertEqual(rows[2]['state'], 'statically-unreachable')
        self.assertEqual(rows[2]['moduleGraph'], 'closed')
        self.assertEqual((value['libraryReachability'], value['workerDrain'], value['qualification']), ('unknown', 'unproven', 'unknown'))

    def test_unsupported_name_does_not_create_an_api_elimination_or_execution_claim(self):
        value = analyze(core([b'\x01\x0b']))
        row = by_function(value)[0]
        self.assertEqual(row['state'], 'statically-unreachable')
        self.assertEqual(row['apiElimination'], 'not-established')
        self.assertEqual(value['initializationExecution'], 'not-executed')
        self.assertNotIn('unsupported-eliminated', encode(value).decode())
        self.assertNotIn('unsupported-reached', encode(value).decode())

    def test_initialization_start_is_a_root_without_running_it(self):
        value = analyze(core([b'\x01\x0b', b'\x10\x00\x0b'], start=2))
        self.assertEqual(by_function(value)[0]['phases'], ['initialization'])
        self.assertEqual(by_function(value)[2]['phases'], ['initialization'])
        self.assertEqual(value['initializationExecution'], 'not-executed')

    def test_all_core_exports_are_conservative_roots_not_an_exact_component_export_map(self):
        value = analyze(core([b'\x01\x0b', b'\x10\x00\x0b'], exports=(1, 2)))
        self.assertEqual(by_function(value)[0]['state'], 'potentially-reachable')
        self.assertEqual(value['selectedExportMapping'], 'conservative-superset')

    def test_indirect_callback_and_table_dispatch_prevent_elimination(self):
        value = analyze(core([b'\x41\x00\x11\x00\x00\x0b', b'\x10\x00\x0b'], table=True))
        self.assertEqual(by_function(value)[0]['state'], 'dynamic-unknown')
        self.assertEqual(by_function(value)[2]['state'], 'dynamic-unknown')
        self.assertIn('table-or-indirect-dispatch', value['analysisReasons'])
        self.assertEqual(value['libraryReachability'], 'unknown')

    def test_addressable_function_is_a_callback_candidate_even_without_invoking_it(self):
        value = analyze(core([b'\xd2\x02\x1a\x0b', b'\x01\x0b'], exports=(1, 2)))
        self.assertIn('callbacks', by_function(value)[2]['phases'])
        self.assertEqual(value['dynamicDispatch'], 'unknown')

    def test_constants_and_data_bytes_are_not_scanned_for_call_patterns(self):
        raw = core([b'\x43\x10\x00\x00\x00\x1a\x41\x10\x1a\x0b'],
                   data=b'\x01\x01\x03\x10\x00\x0b')
        self.assertEqual(by_function(analyze(raw))[0]['state'], 'statically-unreachable')

    def test_trap_opcode_is_not_an_unsupported_operation_classification(self):
        value = analyze(core([b'\x00\x0b']))
        self.assertEqual(by_function(value)[1]['state'], 'potentially-reachable')
        self.assertTrue(all(row['apiElimination'] == 'not-established' for row in value['findings']))

    def test_unrecognized_gc_or_simd_encoding_stays_unknown_instead_of_skipping_bytes(self):
        for body in (b'\xfb\x00\x10\x00\x0b', b'\xfd\x10\x00\x0b'):
            with self.subTest(body=body):
                value = analyze(core([body]))
                self.assertEqual(by_function(value)[0]['state'], 'dynamic-unknown')
                self.assertIn('unsupported-or-malformed-encoding', value['analysisReasons'])

    def test_nested_components_bind_all_observed_core_modules(self):
        module = core([b'\x10\x00\x0b'])
        component = emitted.COMPONENT + section(1, module) + section(4, emitted.COMPONENT + section(1, module))
        value = analyze(component)
        self.assertEqual(value['modulesObserved'], 2)
        self.assertEqual({row['module'] for row in value['findings']}, {0, 1})
        self.assertEqual(value['componentDigest'], digest(component))

    def test_absent_core_module_is_unknown_including_empty_final_component(self):
        value = analyze(emitted.COMPONENT)
        self.assertEqual(value['analysisReasons'], ['no-core-module-observed'])
        self.assertEqual(value['findings'], [])
        self.assertEqual(value['libraryReachability'], 'unknown')

    def test_malformed_lengths_dangling_indices_and_versions_do_not_create_eliminated_findings(self):
        for raw in (b'not wasm', core([b'\x01\x0b'])[:-1], core([b'\x10\x7f\x0b']),
                    core([b'\x01\x0b'], exports=(99,)), emitted.COMPONENT + b'\x01\xff\xff\xff\xff\xff'):
            with self.subTest(raw=raw[:20]):
                value = analyze(raw)
                self.assertTrue(value['analysisReasons'])
                self.assertFalse(any(row['state'] == 'statically-unreachable' for row in value['findings']))

    def test_limits_report_omissions_and_unknown_instead_of_an_empty_safe_pass(self):
        raw = core([b'\x01\x0b'] * 100, imported=False, exports=(0,))
        value = analyze(raw)
        self.assertEqual(len(value['findings']), 64)
        self.assertEqual(value['omittedFindings'], 36)
        self.assertLessEqual(len(encode(value)), 65536)
        huge = analyze(emitted.CORE + b'\x00' * emitted.MAX_ANALYSIS_BYTES)
        self.assertEqual(huge['analysisReasons'], ['analysis-byte-limit'])
        self.assertEqual(huge['libraryReachability'], 'unknown')

    def test_instruction_depth_and_function_work_are_bounded(self):
        deep = core([b'\x02\x40' * 257 + b'\x0b' * 258])
        self.assertIn('analysis-work-limit', analyze(deep)['analysisReasons'])
        oversized = emitted.CORE + section(3, unsigned(emitted.MAX_FUNCTIONS + 1))
        self.assertIn('analysis-work-limit', analyze(oversized)['analysisReasons'])

    def test_compiler_names_are_redacted_without_source_payloads_or_host_paths(self):
        raw = core([b'\x01\x0b'] * 4, imported=False, exports=(0,), names={
            0: '/home/private/secret', 1: 'https://user:password@private.invalid',
            2: 'C:/private/token', 3: 'credential@host'})
        value = analyze(raw); encoded = encode(value).decode()
        self.assertEqual(value['redactedSymbols'], 4)
        self.assertNotIn('private', encoded); self.assertNotIn('credential', encoded)
        self.assertEqual(by_function(value)[0]['symbol'], 'core-0.function-0')

    def test_actual_safe_emitted_symbol_name_is_retained_with_missing_source_location_explicit(self):
        value = analyze(core([b'\x01\x0b'], names={1: 'library::callback'}))
        self.assertEqual(by_function(value)[1]['symbol'], 'library::callback')
        self.assertEqual(by_function(value)[1]['sourceLocation'], 'not-observed')

    def test_source_component_runtime_host_graph_and_recipe_cannot_borrow_stale_analysis(self):
        graph, recipe = digest(b'graph'), digest(b'recipe')
        value = analyze(core([b'\x01\x0b']), graph_digest=graph, recipe_digest=recipe)
        for bindings, field in (({'source': digest(b'other')}, 'source'), ({'component': digest(b'other')}, 'component'),
                                ({'runtime': 'other-profile'}, 'runtime'), ({'host': 'other-host'}, 'host'),
                                ({'graph': digest(b'other')}, 'graph'), ({'recipe': digest(b'other')}, 'recipe')):
            with self.subTest(field=field), self.assertRaisesRegex(DevError, 'stale-' + field):
                emitted.validate(value, **bindings)

    def test_rehashed_report_cannot_assert_execution_supported_api_or_retirement(self):
        value = analyze(core([b'\x01\x0b']))
        for field, claim in (('initializationExecution', 'executed'), ('libraryReachability', 'safe'),
                             ('workerDrain', 'reaped'), ('qualification', 'qualified'), ('authority', 'grant')):
            changed = copy.deepcopy(value); changed[field] = claim; rehash(changed)
            with self.subTest(field=field), self.assertRaisesRegex(DevError, 'cannot-certify'):
                emitted.validate(changed)

    def test_findings_unknown_fields_and_document_limits_are_fail_closed(self):
        value = analyze(core([b'\x01\x0b']))
        value['findings'][0]['rawSource'] = 'secret'; rehash(value)
        with self.assertRaises(DevError): emitted.validate(value)
        with self.assertRaises(DevError): emitted.read(b'x' * (emitted.MAX_BYTES + 1))

    def test_same_bound_diagnostic_can_be_reused_without_overwriting_or_rebinding_it(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory); raw = core([b'\x01\x0b'])
            emitted.emit(output, raw, SOURCE, RUNTIME, HOST)
            before = (output / 'compatibility-reachability.json').read_bytes()
            emitted.emit(output, raw, SOURCE, RUNTIME, HOST)
            self.assertEqual((output / 'compatibility-reachability.json').read_bytes(), before)
            with self.assertRaisesRegex(DevError, 'stale-source'):
                emitted.emit(output, raw, digest(b'new source'), RUNTIME, HOST)

    def test_existing_owner_context_hooks_bind_sidecar_and_preserve_original_v1_report(self):
        from tools.tests.test_guest_compatibility_context import BuildContext, SOURCE as source, COMPONENT as component
        fixture = BuildContext('test_immutable_v1_report_bytes_and_identity_survive_context_emission')
        fixture.setUp()
        try:
            fixture.test_immutable_v1_report_bytes_and_identity_survive_context_emission()
            value = emitted.read((fixture.output / 'compatibility-reachability.json').read_bytes(),
                source=digest(source), component=digest(component), runtime='not-observed', host='lsf-host-abi-phase3-v4')
            self.assertEqual(value['libraryReachability'], 'unknown')
            self.assertEqual((fixture.output / 'compatibility-report.json').read_bytes(), fixture.original)
        finally: fixture.doCleanups()

    def test_context_emission_reuses_capture_domain_for_large_selected_graph_identity(self):
        from tools.tests.test_guest_runtime_receipts import OwnerSelection
        fixture = OwnerSelection('test_large_valid_captured_file_graph_uses_capture_domain_without_widening_controller_limits')
        fixture.setUp()
        try:
            fixture.test_large_valid_captured_file_graph_uses_capture_domain_without_widening_controller_limits()
            selected = emitted.read((fixture.output / 'compatibility-reachability.json').read_bytes())
            from tools import guest_runtime_receipts
            owner = guest_runtime_receipts.read((fixture.output / 'standard-runtime-selection.json').read_bytes())
            self.assertEqual(selected['graphDigest'], owner['graphDigest'])
            self.assertEqual(selected['runtimeProfile'], owner['profile'])
            self.assertEqual(selected['libraryReachability'], 'unknown')
        finally: fixture.doCleanups()

    def test_developer_presentation_keeps_uncertainty_and_rejects_stale_context(self):
        from tools import guest_compatibility as compatibility
        from tools import guest_compatibility_context as context
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory); raw = core([b'\x01\x0b'])
            value = emitted.emit(output, raw, SOURCE, RUNTIME, HOST)
            text = emitted.present(value)
            self.assertIn('library/API reachability remains unknown', text)
            self.assertIn('Initialization was not executed', text)
            report = compatibility.report('rust', SOURCE, digest(b'other component'), HOST, [], [])
            selected = context.create(report,
                [context.material('runtime', 'selected', digest(b'receipt'), profile=RUNTIME)],
                {'state': 'selected-unqualified', 'profile': RUNTIME, 'receiptDigest': digest(b'receipt')})
            path = output / 'context.json'; path.write_bytes(encode(selected))
            with patch('sys.argv', ['guest_emitted_code', str(output / 'compatibility-reachability.json'), '--context', str(path)]), \
                    self.assertRaisesRegex(DevError, 'stale-component'):
                emitted.main()


if __name__ == '__main__': unittest.main()
