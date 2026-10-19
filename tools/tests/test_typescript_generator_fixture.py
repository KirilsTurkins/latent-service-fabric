"""Real approval/adoption boundaries with process-modeled generated TypeScript outputs."""
import ast
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools import typescript_generator_fixture as fixture, application_dependency_tools as tools
from tools.typescript_guest.project import create, validate, snapshot
from tools.phase2_operator_process import WorkflowError
from tools.rust_capsule_project import digest
from tools.build_snapshot import canonical


class GeneratedTypeScriptFixture(unittest.TestCase):
    def test_generator_program_is_valid_and_uses_only_selected_inputs_for_outputs(self):
        tree = ast.parse(fixture.TOOL)
        strings = [node.value for node in ast.walk(tree) if isinstance(node, ast.Constant) and isinstance(node.value, str)]
        self.assertIn('/inputs/selection.json', strings)
        self.assertIn('/outputs/approved_value.ts', strings)
        self.assertIn(fixture.CANARY, strings)
        self.assertIn('parent network exposed', strings)
        self.assertIn('ambient host source exposed', strings)
        self.assertIn('export function approvedGeneratedText(text: string): string { return ', strings)
        self.assertTrue(any('+text.length)' in value for value in strings))

    def test_real_cli_exact_request_negatives_adoption_and_offline_validation(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            app = create(root/'project', 'greeting')
            source = app/'src/main.ts'
            source.write_bytes(source.read_bytes().replace(b'`Hello, ${clean}!`', b'`${prefix()}${clean}!`')
                + b'\nfunction prefix(): string { return "Hello, "; }\n')
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
                (outputs/'approved_value.ts').write_text('export function approvedGeneratedText(text: string): string { return '
                    + 'String(' + str(value['value']) + '+text.length)+"|"+' + json.dumps(value['nonce']) + '+"|"+text; }\n')
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
            self.assertIn(str(result['value']).encode(), (app/'src/generated/approved_value.ts').read_bytes())
            self.assertIn(result['nonce'].encode(), (app/'src/generated/approved_value.ts').read_bytes())
            self.assertIn(b'approvedGeneratedText(clean.slice(13))', source.read_bytes())
            self.assertIn(b'function prefix(): string { return "Hello, "; }', source.read_bytes())
            self.assertLess(source.read_bytes().index(b'if (utf8Length(clean) > 100)'), source.read_bytes().index(b'"generated-ts:"'))
            self.assertIn(b'return `${prefix()}${clean}!`;', source.read_bytes())
            validate(snapshot(app))
            (app/'src/generated/approved_value.ts').write_bytes(b'export const modified = 1;\n')
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
            text = arguments[0].removeprefix('generated-ts:')
            texts.append(text)
            number = selection['value'] + (len(text.encode('utf-8')) if fault == 'utf8-bytes' else len(text.encode('utf-16-le'))//2)
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
        self.assertEqual(values[1], [{'ok': '1246|' + 'a'*24 + '|Gr\u00fc\u00dfe'}])
        self.assertEqual((sample.call_count, idle.call_count), (3, 3))
        self.assertEqual(len(result['approvedTypeScriptGenerator']['cases']), 3)
        self.assertFalse(result['approvedTypeScriptGenerator']['fullTicketQualification'])

    def test_exact_generated_utf16_dependent_values_and_identity_are_observed_with_normal_idle(self):
        self.execute()

    def test_wrong_values_or_byte_counts_cannot_replace_generated_string_lengths(self):
        for fault in ('value', 'utf8-bytes'):
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

    def test_new_runner_selector_is_default_off_strict_boolean_and_typescript_only_before_effects(self):
        from inspect import signature
        from tools import run_rust_capsule_workflow as workflow
        self.assertIs(signature(workflow.run).parameters['approved_typescript_generator'].default, False)
        for selected in ({'language': 'go', 'approved_typescript_generator': True}, {'language': 'typescript', 'approved_typescript_generator': 1}):
            with self.subTest(selected=selected), patch.object(workflow, 'fresh') as fresh, \
                    self.assertRaisesRegex(WorkflowError, 'authoring-TypeScript-generator-language'):
                workflow.run(None, None, None, None, **selected)
            fresh.assert_not_called()

    def test_qualification_requires_explicit_c_or_typescript_captured_selection_before_dispatch(self):
        from inspect import signature
        from tools import qualify_rust_capsules as qualification
        self.assertIs(signature(qualification.qualify).parameters['approved_generator'].default, False)
        for selected in ({'language': 'rust', 'application_dependencies': True, 'approved_generator': True},
                         {'language': 'typescript', 'approved_generator': True},
                         {'language': 'typescript', 'application_dependencies': True, 'approved_generator': 1}):
            with self.subTest(selected=selected), patch.object(qualification, 'fresh') as fresh, \
                    self.assertRaisesRegex(ValueError, 'approved generator qualification'):
                qualification.qualify(None, **selected)
            fresh.assert_not_called()


class ActualGeneratedSource(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from tools.tests.test_typescript_generator_authoring import require_containment
        require_containment()

    def test_actual_generator_cannot_read_live_parent_listener_canaries_and_is_captured_offline(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            app = create(root/'project', 'greeting')
            source = app/'src/main.ts'
            source.write_bytes(source.read_bytes().replace(b'`Hello, ${clean}!`', b'`${prefix()}${clean}!`')
                + b'\nfunction prefix(): string { return "Hello, "; }\n')
            original_sdk = (app/'sdk-lock.json').read_bytes()
            value = fixture.install(app, root/'outside')
            self.assertEqual(value['cleanup'], 'reaped')
            self.assertEqual(value['network'], 'denied')
            self.assertEqual(value['runtimeExecution'], 'not-yet-observed')
            self.assertFalse((root/'outside/generate-source').exists())
            self.assertFalse((root/'outside/inputs/selection.json').exists())
            self.assertEqual((app/'sdk-lock.json').read_bytes(), original_sdk)
            with patch('subprocess.Popen', side_effect=AssertionError('offline validation reran generator')):
                validate(snapshot(app))
            self.assertIn(str(value['value']).encode(), (app/'src/generated/approved_value.ts').read_bytes())
            self.assertIn(value['nonce'].encode(), (app/'src/generated/approved_value.ts').read_bytes())


if __name__ == '__main__':
    unittest.main()
