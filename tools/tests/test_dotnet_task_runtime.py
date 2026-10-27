"""Authority and retirement gates for the ordinary managed-task programme."""
import copy
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from tools import dotnet_task_runtime_fixture as fixture, dotnet_task_runtime_probe as probe
from tools.dotnet_guest import project, runtime
from tools.run_rust_capsule_workflow import run


class ManagedTaskProgramme(unittest.TestCase):
    def test_async_activation_declaration_preserves_sdk_and_adds_no_network_or_grants(self):
        with tempfile.TemporaryDirectory() as temporary:
            app = project.create(Path(temporary) / 'greeting', 'greeting')
            before = (app / 'sdk-lock.json').read_bytes()
            fixture.declare(app)
            project.validate(project.snapshot(app))
            wit = (app / 'wit/world.wit').read_text(encoding='utf-8')
            self.assertIn('greet: async func(', wit)
            self.assertIn(runtime.ACTIVATION, wit)
            self.assertIn(runtime.WALL, wit)
            self.assertNotIn(runtime.HTTP, wit)
            self.assertIn(runtime.RANDOM, wit)
            self.assertEqual((app / 'sdk-lock.json').read_bytes(), before)
            self.assertNotIn('grants', (app / 'capsule-project.json').read_text(encoding='utf-8'))
            with self.assertRaisesRegex(RuntimeError, 'canonical-greeting'): fixture.declare(app)

    def test_wrong_language_combined_campaign_or_nonboolean_selector_refuses_before_inputs(self):
        for keywords in ({'language': 'rust', 'dotnet_task_runtime': True},
                         {'language': 'dotnet', 'dotnet_task_runtime': 1},
                         {'language': 'dotnet', 'dotnet_task_runtime': True, 'noncrypto_entropy': True}):
            with self.subTest(keywords=keywords), self.assertRaisesRegex(RuntimeError, 'task-runtime-language'):
                run(Path('missing'), Path('missing'), Path('missing'), Path('missing'), **keywords)

    def test_failed_activation_binding_never_adds_grants_or_deploys(self):
        with tempfile.TemporaryDirectory() as temporary:
            client = SimpleNamespace(directory=Path(temporary), call=Mock(return_value={
                'outcomeKnown': False, 'category': 'uncertain'}))
            target = {'grants': [{'capability': runtime.CLOCK, 'policy': 'clock'}],
                      'service': 'examples/my-greeting', 'generation': 3}
            node = SimpleNamespace(startup_record={'providers': [{
                'id': 'activation-tasks', 'capability': runtime.ACTIVATION, 'profile': 'observed-profile',
                'configurationDigest': 'sha256:' + 'a' * 64}]})
            denied = {'processReaped': True, 'exitCode': 4,
                'response': {'outcomeKnown': True, 'error': {'code': 'permission-denied'}}}
            targets = {'greeting': copy.deepcopy(target)}
            with patch('tools.rust_capsule_node.call', return_value=denied), \
                    patch('tools.rust_capsule_node.deploy') as deploy:
                with self.assertRaisesRegex(RuntimeError, 'binding-apply'):
                    probe.grant(client, node, Path(temporary), targets, {'greeting': 'publication'}, {'invocations': []})
                deploy.assert_not_called()
            self.assertEqual(targets['greeting'], target)

    def test_each_runtime_grant_is_omitted_independently_and_refuses_before_guest_entry(self):
        for fuel in ('0', '1'):
            with tempfile.TemporaryDirectory() as temporary:
                directory = Path(temporary)
                denied = {'processReaped': True, 'exitCode': 4, 'response': {'outcomeKnown': True,
                    'error': {'code': 'permission-denied'}, 'data': {'consumption': {
                        'cpuFuel': fuel, 'peakMemoryBytes': '0', 'outboundRequests': '0',
                        'logBytes': '0', 'effectCount': '0'}}}}
                client = SimpleNamespace(directory=directory, call=Mock(return_value={
                    'outcomeKnown': True, 'category': 'success'}))
                node = SimpleNamespace(startup_record={'providers': [
                    {'id': 'activation-tasks', 'capability': runtime.ACTIVATION, 'profile': 'activation-owned-v1',
                     'configurationDigest': 'sha256:' + 'a' * 64},
                    {'id': 'wall-tasks', 'capability': runtime.WALL, 'profile': 'activation-wall-v1',
                     'configurationDigest': 'sha256:' + 'b' * 64}]})
                targets = {'greeting': {'service': 'examples/my-greeting', 'generation': 3,
                    'grants': [{'capability': runtime.CLOCK, 'policy': 'clock'}]}}
                observed = []
                def deployed(*args, grants, **keywords):
                    observed.append(copy.deepcopy(grants))
                    return {**targets['greeting'], 'generation': 3 + len(observed), 'grants': grants}
                def entropy(*args):
                    result = args[-1]
                    result['noncryptoEntropyAuthority'] = {'scope': 'fixture-only'}
                    result['noncryptoEntropyGrantDenied'] = denied
                    target = args[-2]
                    return {**target, 'grants': [*target['grants'], {'capability': runtime.RANDOM, 'policy': 'random'}]}
                result = {'invocations': []}
                with self.subTest(fuel=fuel), patch('tools.rust_capsule_node.call', return_value=denied), \
                        patch('tools.rust_capsule_node.deploy', side_effect=deployed), \
                        patch.object(probe.entropy_grants, 'grant', side_effect=entropy):
                    if fuel != '0':
                        with self.assertRaisesRegex(RuntimeError, 'single-required-grant'):
                            probe.grant(client, node, directory, targets, {'greeting': 'publication'}, result)
                        self.assertNotIn('dotnetTaskRuntimeAuthority', result)
                    else:
                        probe.grant(client, node, directory, targets, {'greeting': 'publication'}, result)
                        all_grants = {runtime.CLOCK, runtime.WALL, runtime.ACTIVATION, runtime.RANDOM}
                        evidence = result['dotnetTaskRuntimeAuthority']['singleMissingGrantDenials']
                        self.assertEqual({row['missingCapability'] for row in evidence}, all_grants)
                        self.assertEqual(len(evidence), 4)
                        for grants, missing in zip(observed[1:-1], evidence):
                            self.assertEqual({row['capability'] for row in grants}, all_grants - {missing['missingCapability']})
                        self.assertEqual({row['capability'] for row in observed[-1]}, all_grants)

    def test_every_case_requires_known_reaped_bounded_zero_effect_execution_and_retirement(self):
        target = {'budget': {'cpuFuel': 1000, 'memoryBytes': 10000}}
        original = {'processReaped': True, 'response': {'outcomeKnown': True, 'data': {
            'consumption': {'cpuFuel': '17', 'peakMemoryBytes': '100', 'outboundRequests': '0',
                'logBytes': '0', 'effectCount': '0'}}}}
        for mutation in ('none', 'unreaped', 'unknown', 'fuel', 'memory', 'outbound', 'effects'):
            row = copy.deepcopy(original)
            if mutation == 'unreaped': row['processReaped'] = False
            elif mutation == 'unknown': row['response']['outcomeKnown'] = False
            elif mutation != 'none':
                key, value = {'fuel': ('cpuFuel', '1001'), 'memory': ('peakMemoryBytes', '10001'),
                    'outbound': ('outboundRequests', '1'), 'effects': ('effectCount', '1')}[mutation]
                row['response']['data']['consumption'][key] = value
            result = {'invocations': [], 'providerIdle': [], 'samples': []}
            with self.subTest(mutation=mutation), patch('tools.rust_capsule_node.call', return_value=row), \
                    patch('tools.rust_capsule_node.assert_value') as values, \
                    patch('tools.rust_capsule_node.provider_idle', return_value={'idle': True}), \
                    patch('tools.rust_capsule_node.sample', return_value={'retired': True}):
                if mutation != 'none':
                    with self.assertRaisesRegex(RuntimeError, 'consumption-or-reaping'):
                        probe.probe(None, target, None, result, 0)
                    self.assertNotIn('dotnetTaskRuntime', result)
                else:
                    probe.probe(None, target, None, result, 0)
                    self.assertEqual(len(result['invocations']), len(fixture.CASES))
                    self.assertEqual(len(result['samples']), len(fixture.CASES))
                    self.assertEqual([args.args[2] for args in values.call_args_list],
                        [[{'ok': fixture.expected(mode)}] for mode in fixture.CASES])
                    self.assertFalse(result['dotnetTaskRuntime']['cpuPreemptionQualified'])


class RootReturnNormalControls(unittest.TestCase):
    def test_marker_parser_requires_real_close_pending_and_original_bounds(self):
        from tools.dotnet_root_return import positive_sequence
        from tools.phase2_operator_process import WorkflowError
        prefix = b'LSF-GO-NODE-STOP-TIMER-V1|'
        lines = [b'pending|root-close|1|2|0|0', b'pending|wait-pending|2|2|1|1',
                 b'drain|root-close|3|1|1|1', b'drain|wait-pending|4|1|1|1']
        encode = lambda values: b'\n'.join(prefix+x for x in values)+b'\n'
        self.assertEqual([r['sequence'] for r in positive_sequence(encode(lines))], [1, 2, 3, 4])
        for bad in (lines[:1]+[b'pending|wait-pending|1|2|1|1']+lines[2:],
                    [b'pending|root-close|1|1|0|0']+lines[1:],
                    lines[:3]+[b'drain|wait-pending|4|1|17|1'],
                    lines[:3]+[b'drain|wait-pending|2|1|1|1'],
                    lines[:1]+[b'pending|wait-pending|0|2|1|1']+lines[2:],
                    lines[:3]+[b'drain|next-entered|4|1|1|1'],
                    lines+[b'overflow'], lines+[b'foreign|root-close|5|1|0|0']):
            with self.subTest(bad=bad), self.assertRaises((WorkflowError, ValueError)):
                positive_sequence(encode(bad))
        with self.assertRaises((WorkflowError, ValueError)):
            positive_sequence(b'x'*262145)

    def test_exact_normal_programme_preserves_caps_and_only_two_observer_ids(self):
        from tools import dotnet_root_return as selected
        self.assertEqual([(t, m) for t, m, _ in selected.STEPS], [
            ('examples', 1), ('foreign', 2), ('examples', 3), ('foreign', 4), ('examples', 5),
            ('foreign', 6), ('examples', 8), ('foreign', 6), ('examples', 9), ('foreign', 6), ('examples', 6)])
        self.assertEqual(len({a for _, _, a in selected.STEPS}), 11)
        self.assertEqual([(m, a) for _, m, a in selected.STEPS if a.startswith('node-stop-')],
            [(1, 'node-stop-pending'), (2, 'node-stop-drain')])
        self.assertEqual(selected.OWNER_CAPS, {'tasks': 8, 'executors': 2, 'queuedWork': 8,
            'waits': 16, 'timers': 8, 'results': 8, 'nativeOwners': 8})
        self.assertNotIn(7, [m for _, m, _ in selected.STEPS])
        self.assertEqual(len(selected.STEPS)+len(selected.PROFILES), 15)


    def test_retention_closes17_and_keeps_component_before_shape_refusal(self):
        import hashlib
        import json
        from tools import dotnet_root_return as selected
        from tools.phase2_operator_process import WorkflowError
        self.assertEqual(len(selected.PROBE_SOURCES), 17)
        for count, extra in ((17, False), (16, False), (17, True)):
            with self.subTest(count=count, unsafe_extra=extra), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary); compiled = root/'compiled'; generated = compiled/'generated'
                generated.mkdir(parents=True); output = root/'output'; output.mkdir()
                # Parser-only fixture bytes, never a real compiled programme.
                component = b'\0asm\x0d\0\x01\0'; (compiled/'component.wasm').write_bytes(component)
                outputs = {}
                for name in selected.PROBE_SOURCES[:count]:
                    raw = ('// parser control '+name).encode(); (generated/name).write_bytes(raw)
                    outputs[name] = hashlib.sha256(raw).hexdigest()
                if extra: outputs['../outside.cs'] = '0'*64
                if count == 17 and not extra:
                    names, records = selected.stage_probe_sources(compiled, output, {'outputs': outputs}, compiler_returned=True)
                    self.assertEqual(tuple(names), selected.PROBE_SOURCES); self.assertEqual(len(records), 17)
                else:
                    with self.assertRaises(WorkflowError):
                        selected.stage_probe_sources(compiled, output, {'outputs': outputs}, compiler_returned=True)
                report = json.loads((output/'probe-capture-inventory.json').read_bytes())
                self.assertEqual(report['csharpCount'], count+int(extra))
                self.assertFalse(report['captureComplete'])
                self.assertEqual((output/'component.wasm').read_bytes(), component)
                self.assertEqual(len(list((output/'probe-inputs').glob('*.cs'))), count)
                self.assertFalse((output/'outside.cs').exists())


if __name__ == '__main__':
    unittest.main()
