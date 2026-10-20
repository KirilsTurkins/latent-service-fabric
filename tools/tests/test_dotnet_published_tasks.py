"""Published NuGet graph, immutable inputs and strict signed-outcome controls."""
import copy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from tools import dotnet_published_task_fixture as fixture, dotnet_published_task_probe as probe
from tools.dotnet_guest import project, runtime
from tools.rust_capsule_project import snapshot
from tools.run_rust_capsule_workflow import run


class PublishedManagedTasks(unittest.TestCase):
    def test_normal_authoring_keeps_sdk_limits_and_declares_only_reviewed_runtime_authority(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            pristine = project.create(root / 'pristine', 'greeting')
            app = fixture.application(root / 'published')
            original = snapshot(pristine)
            actual = snapshot(app)
            for name in original:
                if name not in {'src/Main.cs', 'wit/world.wit', 'Capsule.csproj'}:
                    self.assertEqual(actual[name], original[name], name)
            project.validate_sdk_inputs(actual)
            with self.assertRaisesRegex(ValueError, "compiler configuration"):
                project.validate(actual)
            wit = actual['wit/world.wit'].decode()
            self.assertIn(runtime.CLOCK, wit)
            self.assertIn(runtime.ACTIVATION, wit)
            self.assertIn(runtime.RANDOM, wit)
            self.assertNotIn(runtime.HTTP, wit)
            self.assertIn(b'Polly', actual['Capsule.csproj'])
            self.assertIn(b'[8.6.3]', actual['Capsule.csproj'])
            self.assertEqual(actual['src/PublishedTasks.cs'], fixture.SOURCE.encode())

    def test_reviewed_primary_and_transitive_graph_never_accepts_drift_or_build_tools(self):
        rows = [dict(id=name, role='application', format='zip',
                     metadata={'ecosystem': 'nuget', 'sdk': False, 'executableAssets': []},
                     dependencies=['polly.core/8.6.3'] if name=='polly/8.6.3' else [])
                for name in ('polly/8.6.3', 'polly.core/8.6.3')]
        fixture.selected({'artifacts': rows})
        for mode in ('version', 'edge', 'tool', 'sdk', 'script', 'extra'):
            changed = copy.deepcopy(rows)
            if mode == 'version': changed[1]['id'] = 'polly.core/8.6.4'
            elif mode == 'edge': changed[0]['dependencies'] = []
            elif mode == 'tool': changed[1]['role'] = 'build-tool'
            elif mode == 'sdk': changed[1]['metadata']['sdk'] = True
            elif mode == 'script': changed[1]['metadata']['executableAssets'] = ['build/hidden.targets']
            elif mode == 'extra': changed.append({**copy.deepcopy(changed[1]), 'id': 'outside/1.0.0'})
            with self.subTest(mode=mode), self.assertRaisesRegex(RuntimeError, 'selected-graph'):
                fixture.selected({'artifacts': changed})

    def test_invalid_or_combined_selector_fails_before_materials_or_execution(self):
        for keywords in ({'language': 'rust'}, {'language': 'dotnet', 'dotnet_task_runtime': True},
                         {'language': 'dotnet', 'noncrypto_entropy': True},
                         {'language': 'dotnet', 'standard_scratch_refusal': True},
                         {'language': 'dotnet', 'dotnet_published_tasks': 1}):
            selected = {'dotnet_published_tasks': True, **keywords}
            with self.subTest(selected=selected), self.assertRaisesRegex(RuntimeError, 'published-tasks-language'):
                run(Path('missing'), Path('missing'), Path('missing'), Path('missing'), **selected)

    def test_failed_guest_result_is_retained_before_assertion_without_retry_or_success(self):
        row = {'activation': 'published-failed', 'exitCode': 4, 'decoded': None,
               'response': {'outcomeKnown': True}}
        result = {'invocations': [], 'providerIdle': [], 'samples': []}
        with patch('tools.rust_capsule_node.call', return_value=row) as invoke, \
                patch('tools.capsule_invocation_diagnostics.capture'):
            with self.assertRaisesRegex(RuntimeError, 'application-result'):
                probe.probe(None, {}, None, result, 0)
        invoke.assert_called_once()
        self.assertEqual(result['invocations'], [row])
        self.assertNotIn('dotnetPublishedTasks', result)
        self.assertEqual(result['samples'], [])

    def test_every_published_result_requires_original_limits_reaping_and_retirement(self):
        target = {'budget': {'cpuFuel': 1000, 'memoryBytes': 10000}}
        original = {'processReaped': True, 'response': {'outcomeKnown': True, 'data': {
            'consumption': {'cpuFuel': '17', 'peakMemoryBytes': '100', 'outboundRequests': '0',
                'logBytes': '0', 'effectCount': '0'}}}}
        for mode in ('none', 'unreaped', 'unknown', 'fuel', 'memory', 'outbound', 'log', 'effect'):
            row = copy.deepcopy(original)
            if mode == 'unreaped': row['processReaped'] = False
            elif mode == 'unknown': row['response']['outcomeKnown'] = False
            elif mode != 'none':
                key, value = {'fuel': ('cpuFuel', '1001'), 'memory': ('peakMemoryBytes', '10001'),
                    'outbound': ('outboundRequests', '1'), 'log': ('logBytes', '1'),
                    'effect': ('effectCount', '1')}[mode]
                row['response']['data']['consumption'][key] = value
            result = {'invocations': [], 'providerIdle': [], 'samples': []}
            with self.subTest(mode=mode), patch('tools.rust_capsule_node.call', return_value=row), \
                    patch('tools.rust_capsule_node.assert_value') as values, \
                    patch('tools.rust_capsule_node.provider_idle', return_value={'idle': True}), \
                    patch('tools.rust_capsule_node.sample', return_value={'retired': True}):
                if mode != 'none':
                    with self.assertRaisesRegex(RuntimeError, 'consumption-or-reaping'):
                        probe.probe(None, target, None, result, 0)
                    self.assertNotIn('dotnetPublishedTasks', result)
                else:
                    probe.probe(None, target, None, result, 0)
                    self.assertEqual(len(result['samples']), len(fixture.CASES))
                    self.assertEqual([args.args[2] for args in values.call_args_list],
                                     [[{'ok': fixture.expected(case)}] for case in fixture.CASES])
                    self.assertFalse(result['dotnetPublishedTasks']['fullRuntimeQualification'])


if __name__ == '__main__':
    unittest.main()
