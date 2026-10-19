"""Real approval/adoption boundaries with process-modeled generated Go outputs."""
import ast
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools import go_generator_fixture as fixture, application_dependency_tools as tools
from tools.go_capsule_project import create, validate, snapshot
from tools.phase2_operator_process import WorkflowError
from tools.rust_capsule_project import digest
from tools.build_snapshot import canonical


class GeneratedGoFixture(unittest.TestCase):
    def test_generator_program_is_valid_and_uses_only_selected_inputs_for_outputs(self):
        tree = ast.parse(fixture.TOOL)
        strings = [node.value for node in ast.walk(tree) if isinstance(node, ast.Constant) and isinstance(node.value, str)]
        self.assertIn('/inputs/selection.json', strings)
        self.assertIn('/outputs/approved_value.go', strings)
        self.assertIn(fixture.CANARY, strings)
        self.assertIn('parent network exposed', strings)
        self.assertIn('ambient host source exposed', strings)
        self.assertIn('func ApprovedGeneratedValue(text string) (uint32, string) { return ', strings)
        self.assertTrue(any('+uint32(len([]byte(text)))' in value for value in strings))

    def test_real_cli_exact_request_negatives_adoption_and_offline_validation(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            app = create(root/'project', 'greeting')
            source = app/'src/main.go'
            source.write_bytes(source.read_bytes().replace(b'"Hello, " + name + "!"', b'applicationPrefix(name) + name + "!"')
                + b'\nfunc applicationPrefix(name string) string { return "Hello, " }\n')
            original_sdk = (app/'sdk-lock.json').read_bytes()
            def execute(executable, arguments, inputs, outputs, receipt, **options):
                spec = tools.specification(executable, arguments, inputs,
                    tool_version=options['tool_version'], environment=options['environment'])
                self.assertEqual(options['approved_identity'], digest(canonical(spec)))
                self.assertEqual(options['timeout_seconds'], 15)
                self.assertEqual(options['maximum_output_bytes'], 65536)
                self.assertEqual(spec['network'], 'denied')
                value = json.loads((inputs/'selection.json').read_bytes())
                self.assertTrue(Path(value['outsideCanary']).is_file())
                outputs.mkdir()
                (outputs/'approved_value.go').write_text('package export_examples_greeting_api\n'
                    + 'func ApprovedGeneratedValue(text string) (uint32, string) { return '
                    + str(value['value']) + '+uint32(len([]byte(text))), ' + json.dumps(value['nonce']) + '+"|"+text }\n'
                    + 'func ApprovedGeneratedText(text string) string { return "process-modeled-only" }\n')
                result = {'identity': options['approved_identity'], 'cleanup': 'reaped', 'status': 'succeeded'}
                receipt.write_bytes(canonical(result))
                return result
            with patch.object(tools, 'execute', side_effect=execute) as run:
                result = fixture.install(app, root/'outside')
            self.assertEqual(run.call_count, 1)
            self.assertEqual([row['exitCode'] for row in result['commands']], [0, 1, 1, 0, 0])
            self.assertEqual(result['runtimeExecution'], 'not-yet-observed')
            self.assertFalse(result['compilerExecution'])
            self.assertEqual(result['cleanup'], 'reaped')
            self.assertEqual((app/'sdk-lock.json').read_bytes(), original_sdk)
            self.assertFalse((root/'outside/generate-source').exists())
            self.assertFalse((root/'outside/inputs/selection.json').exists())
            self.assertFalse((root/'outside/host-only-canary').exists())
            self.assertIn(str(result['value']).encode(), (app/'src/generated/approved_value.go').read_bytes())
            self.assertIn(result['nonce'].encode(), (app/'src/generated/approved_value.go').read_bytes())
            self.assertIn(b'ApprovedGeneratedText(strings.TrimPrefix(name, "generated-go:"))', source.read_bytes())
            self.assertIn(b'func applicationPrefix(name string) string { return "Hello, " }', source.read_bytes())
            self.assertLess(source.read_bytes().index(b'if len(name) > 100'), source.read_bytes().index(b'"generated-go:"'))
            self.assertIn(b'return wit.Ok[string, string](applicationPrefix(name) + name + "!")', source.read_bytes())
            validate(snapshot(app))
            (app/'src/generated/approved_value.go').write_bytes(b'package modified\n')
            with self.assertRaisesRegex(ValueError, 'generated-inputs-drift'):
                validate(snapshot(app))

    def test_changed_template_stops_before_any_generator_request(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            app = create(root/'project', 'greeting')
            with patch.object(fixture, 'cli') as cli:
                with self.assertRaisesRegex(WorkflowError, 'source-hook'):
                    fixture.install(app, root/'outside')
            cli.assert_not_called()


class SignedGeneratedResults(unittest.TestCase):
    def execute(self, *, fault=None):
        from tools import rust_capsule_node as node
        selection = {'nonce': 'a'*24, 'value': 1241}
        revision = {'publicationId': 'p', 'routeGeneration': '18', 'releaseDigest': 'component', 'revisionId': 'revision'}
        target = {'generation': '1'}
        texts, values = [], []
        def call(_client, selected, template, function, arguments, activation):
            self.assertIs(selected, target)
            self.assertEqual((template, function), ('greeting', 'greet'))
            text = arguments[0].removeprefix('generated-go:')
            texts.append(text)
            number = selection['value'] + (len(text) if fault == 'unicode-runes' else len(text.encode('utf-8')))
            value = str(number) + '|' + selection['nonce'] + '|' + text
            if fault == 'value': value = 'wrong'
            return {'processReaped': fault != 'process', 'decoded': [{'ok': value}],
                'response': {'data': {'resolvedRevision': {**revision, 'routeGeneration': '1'} if fault == 'revision' else revision,
                    'consumption': {name: '1' if fault == name else '0'
                        for name in ('outboundRequests', 'childCalls', 'effectCount')}}}}
        def assert_value(_client, observed, expected):
            self.assertEqual(observed['decoded'], expected)
            values.append(observed['decoded'])
        result = {'invocations': [], 'samples': [], 'providerIdle': []}
        with patch.object(node, 'selected_revision', return_value=revision), patch.object(node, 'call', side_effect=call), \
                patch.object(node, 'assert_value', side_effect=assert_value), patch.object(node, 'sample') as sample, \
                patch.object(node, 'provider_idle') as idle:
            fixture.probe(None, target, None, result, 27, selection)
        self.assertEqual(texts, ['alpha', 'Gr\u00fc\u00dfe', 'fresh-state'])
        self.assertEqual(values[1], [{'ok': '1248|' + 'a'*24 + '|Gr\u00fc\u00dfe'}])
        self.assertEqual((sample.call_count, idle.call_count), (3, 3))
        self.assertEqual(len(result['approvedGoGenerator']['cases']), 3)
        self.assertFalse(result['approvedGoGenerator']['fullTicketQualification'])

    def test_exact_generated_utf8_dependent_values_and_identity_are_observed_with_normal_idle(self):
        self.execute()

    def test_wrong_values_or_rune_counts_cannot_replace_generated_byte_length_results(self):
        for fault in ('value', 'unicode-runes'):
            with self.subTest(fault=fault), self.assertRaises(AssertionError):
                self.execute(fault=fault)

    def test_stale_route_unreaped_or_effectful_results_refuse(self):
        for fault in ('revision', 'process', 'outboundRequests', 'childCalls', 'effectCount'):
            with self.subTest(fault=fault), self.assertRaisesRegex(WorkflowError, 'signed-selected-revision'):
                self.execute(fault=fault)

    def test_malformed_or_unknown_selection_refuses_before_any_node_call(self):
        from tools import rust_capsule_node as node
        for value in ({}, {'nonce': 'secret-shaped-value', 'value': 1000}, {'nonce': 'a'*24, 'value': True},
                      {'nonce': 'a'*24, 'value': 1001000}, {'nonce': 'a'*24, 'value': 1000, 'skip': True}):
            with self.subTest(value=value), patch.object(node, 'call') as call, self.assertRaises(WorkflowError):
                fixture.probe(None, None, None, {}, 0, value)
            call.assert_not_called()

    def test_new_runner_selector_is_default_off_strict_boolean_and_go_only_before_effects(self):
        from inspect import signature
        from tools import run_rust_capsule_workflow as workflow
        self.assertIs(signature(workflow.run).parameters['approved_go_generator'].default, False)
        for selected in ({'language': 'rust', 'approved_go_generator': True}, {'language': 'go', 'approved_go_generator': 1}):
            with self.subTest(selected=selected), patch.object(workflow, 'fresh') as fresh, \
                    self.assertRaisesRegex(WorkflowError, 'authoring-Go-generator-language'):
                workflow.run(None, None, None, None, **selected)
            fresh.assert_not_called()

    def test_qualification_requires_explicit_c_or_go_captured_selection_before_dispatch(self):
        from inspect import signature
        from tools import qualify_rust_capsules as qualification
        self.assertIs(signature(qualification.qualify).parameters['approved_generator'].default, False)
        for selected in ({'language': 'rust', 'application_dependencies': True, 'approved_generator': True},
                         {'language': 'go', 'approved_generator': True},
                         {'language': 'go', 'application_dependencies': True, 'approved_generator': 1}):
            with self.subTest(selected=selected), patch.object(qualification, 'fresh') as fresh, \
                    self.assertRaisesRegex(ValueError, 'approved generator qualification'):
                qualification.qualify(None, **selected)
            fresh.assert_not_called()


if __name__ == '__main__':
    unittest.main()
