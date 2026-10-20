"""Pinned C async argument-record controls; actual component execution is separate."""
from copy import deepcopy
import unittest

from tools.java_guest.model import Graph
from tools.java_guest import async_imports


def selected():
    data = {
        'worlds': [{'name': 'service', 'package': 0,
            'imports': {'pending': {'interface': {'id': 1}}},
            'exports': {'api': {'interface': {'id': 0}}}}],
        'packages': [{'name': 'examples:sample@1.0.0'}],
        'interfaces': [
            {'name': 'api', 'package': 0, 'types': {}, 'functions': {
                'run': {'name': 'run', 'kind': 'freestanding', 'params': [], 'result': None}}},
            {'name': 'pending', 'package': 0, 'types': {}, 'functions': {
                'open': {'name': 'open', 'kind': 'async-freestanding', 'params': [
                    {'name': 'request', 'type': 'string'}, {'name': 'timeout-millis', 'type': 0}],
                    'result': 'u32'}}}],
        'types': [{'name': None, 'owner': None, 'kind': {'option': 'u32'}}],
    }
    header = """typedef struct examples_sample_pending_open_args {
probe_string_t request;
probe_option_u32_t timeout_millis;
} examples_sample_pending_open_args_t;
void exports_examples_sample_api_run(void);
extern probe_subtask_status_t examples_sample_pending_open(examples_sample_pending_open_args_t *args, uint32_t *result);
"""
    return data, header


class JavaAsyncIndirect(unittest.TestCase):
    def test_phase_fixture_retains_every_nominal_type_without_legacy_operations(self):
        from pathlib import Path
        import json
        import re
        import tempfile
        from unittest.mock import patch
        from tools import java_http_phase_fixture as fixture
        from tools.http_phase_wit import nominal_type_owner
        from tools.phase2_operator_process import WorkflowError
        from tools.rust_capsule_project import ROOT
        original = (ROOT/'wit/platform/http-v3/package.wit').read_bytes()
        expected = re.sub(rb'^    ([a-z-]+): async func[^\n]*;\n', b'', original, flags=re.MULTILINE)
        self.assertNotEqual(expected, original)
        self.assertEqual(nominal_type_owner(original), expected)
        for invalid in (expected, original.replace(b'resource body;', b'resource other;'), original+b'\n'):
            with self.subTest(value=invalid), self.assertRaises(WorkflowError): nominal_type_owner(invalid)
        def captured(directory):
            app = directory/'app'
            (app/'src/dev/latent/app').mkdir(parents=True)
            (app/'wit').mkdir()
            (app/'java-dependencies.json').write_text(json.dumps({'dependencies': [
                {'exclusions': [], 'group': 'com.goebl', 'name': 'david-webb', 'scope': 'runtime', 'version': '1.3.0'}]}))
            (app/'sdk-lock.json').write_text('{}')
            (app/'capsule-project.json').write_text('{}')
            for package in ('http-v3', 'http-phases', 'activation-runtime'):
                relative = Path('wit/platform')/package/'package.wit'
                target = app/'vendor/lsf'/relative;target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes((ROOT/relative).read_bytes())
            return app
        with tempfile.TemporaryDirectory() as temporary, patch.object(fixture, 'published_project', side_effect=captured):
            app = fixture.project(Path(temporary))
            self.assertEqual((app/'wit/deps/http-v3/package.wit').read_bytes(), expected)
            self.assertEqual((app/'vendor/lsf/wit/platform/http-v3/package.wit').read_bytes(), original)
            self.assertEqual((app/'wit/deps/http-phases/package.wit').read_bytes(),
                (ROOT/'wit/platform/http-phases/package.wit').read_bytes())

    def test_packed_arguments_decode_every_field_into_one_retained_owned_call(self):
        data, header = selected()
        graph = Graph(data, 'service', header, async_imports=True)
        output = async_imports.generate(graph)
        self.assertIn('examples_sample_pending_open_args_t args;', output)
        self.assertIn('call->data.op0.args.request', output)
        self.assertIn('call->data.op0.args.timeout_millis', output)
        self.assertIn('examples_sample_pending_open(&call->data.op0.args, &call->data.op0.result)', output)
        take = output[output.index('void *lsf_java_async_take'):]
        self.assertIn('call->data.op0.args.request', take)
        self.assertLess(take.index('probe_subtask_drop'), take.index('lsf_release((call->data.op0.args.request)'))
        self.assertLess(take.index('lsf_release((call->data.op0.args.request)'), take.index('lsf_release(call, sizeof(*call))'))
        self.assertNotIn('probe_option_u32_t result;', output)

    def test_malformed_duplicate_reordered_or_pointer_fields_are_refused(self):
        data, header = selected()
        invalid = [
            header.replace('probe_string_t request;', 'probe_string_t *request;'),
            header.replace('probe_option_u32_t timeout_millis;', ''),
            header.replace('timeout_millis;', 'request;'),
            header.replace('probe_string_t request;\nprobe_option_u32_t timeout_millis;',
                'probe_option_u32_t timeout_millis;\nprobe_string_t request;'),
            header.replace('} examples_sample_pending_open_args_t;', '} another_args_t;'),
            header + header[:header.index('void exports')],
            header.replace('*args,', 'args,'),
            header.replace('*result', 'result'),
            header.replace(', uint32_t *result', ''),
            header.replace('uint32_t *result', 'uint32_t *result, uint32_t extra'),
        ]
        for value in invalid:
            with self.subTest(header=value), self.assertRaises(ValueError):
                Graph(data, 'service', value, async_imports=True)

    def test_record_is_never_accepted_for_sync_or_unselected_async_imports(self):
        data, header = selected()
        with self.assertRaises(ValueError): Graph(data, 'service', header)
        data['interfaces'][1]['functions']['open']['kind'] = 'freestanding'
        with self.assertRaises(ValueError): Graph(data, 'service', header, async_imports=True)

    def test_direct_async_layout_and_result_lifetime_are_unchanged(self):
        data, header = selected()
        prefix = header[header.index('void exports'):]
        direct = prefix.replace('examples_sample_pending_open_args_t *args',
            'probe_string_t *request, probe_option_u32_t *timeout_millis')
        graph = Graph(data, 'service', direct, async_imports=True)
        output = async_imports.generate(graph)
        self.assertNotIn('cAggregate', graph.imports[0])
        self.assertIn('probe_string_t arg0;', output)
        self.assertIn('probe_option_u32_t arg1;', output)
        self.assertIn('examples_sample_pending_open(&call->data.op0.arg0, &call->data.op0.arg1, &call->data.op0.result)', output)

    def test_aggregate_without_result_owns_and_frees_all_inputs(self):
        data, header = selected()
        data['interfaces'][1]['functions']['open']['result'] = None
        header = header.replace(', uint32_t *result', '')
        output = async_imports.generate(Graph(data, 'service', header, async_imports=True))
        self.assertIn('examples_sample_pending_open(&call->data.op0.args)', output)
        self.assertNotIn('uint32_t result;', output)
        self.assertIn('lsf_release((call->data.op0.args.request).ptr', output)

    def test_same_record_name_cannot_be_reused_for_an_unrelated_function(self):
        data, header = selected()
        function = deepcopy(data['interfaces'][1]['functions']['open'])
        function['name'] = 'other'
        data['interfaces'][1]['functions'] = {'other': function}
        header = header.replace('examples_sample_pending_open(', 'examples_sample_pending_other(')
        with self.assertRaises(ValueError): Graph(data, 'service', header, async_imports=True)
