"""Joined filesystem controls configure only their declared activation authority."""
import copy
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from tools import dotnet_filesystem_runtime as runtime
from tools.dotnet_guest.runtime import ACTIVATION, CLOCK, RANDOM, WALL
from tools.run_rust_capsule_workflow import run


def refused():
    return {'processReaped': True, 'exitCode': 4, 'response': {'outcomeKnown': True,
        'error': {'code': 'permission-denied'}, 'data': {'consumption': {name: '0' for name in
            ('cpuFuel', 'peakMemoryBytes', 'outboundRequests', 'logBytes', 'effectCount')}}}}


class FilesystemRuntimeAuthority(unittest.TestCase):
    def setup_authority(self, directory):
        client = SimpleNamespace(directory=directory, call=Mock(return_value={
            'outcomeKnown': True, 'category': 'success'}))
        node = SimpleNamespace(startup_record={'providers': [{
            'id': 'activation-filesystem', 'capability': ACTIVATION,
            'profile': 'observed-profile', 'configurationDigest': 'sha256:' + 'a'*64}]})
        target = {'grants': [{'capability': CLOCK, 'policy': 'clock-original'}],
                  'generation': 3, 'service': 'examples/my-greeting'}
        return client, node, {'greeting': target}

    def test_selector_is_explicit_boolean_dotnet_scratch_only_before_inputs(self):
        for selected in ({'dotnet_scratch_task_runtime': 1},
                         {'dotnet_scratch_task_runtime': True},
                         {'dotnet_scratch_task_runtime': True, 'standard_scratch_refusal': True, 'language': 'rust'},
                         {'dotnet_scratch_task_runtime': True, 'standard_scratch_refusal': False, 'language': 'dotnet'}):
            with self.subTest(selected=selected), self.assertRaisesRegex(RuntimeError, 'scratch-task-runtime-selection'):
                run(Path('missing'), Path('missing'), Path('missing'), Path('missing'), **selected)

    def test_configuration_preserves_existing_providers_and_limits_without_random_wall_or_http(self):
        settings = {'providers': {'bindings': [{'contract': CLOCK}], 'clockMonotonic': {'original': True}}}
        before = copy.deepcopy(settings)
        runtime.configure(settings)
        self.assertEqual(settings['providers']['clockMonotonic'], before['providers']['clockMonotonic'])
        self.assertEqual(settings['providers']['bindings'][:-1], before['providers']['bindings'])
        self.assertEqual(set(settings['providers']), {'bindings', 'clockMonotonic', 'activationRuntime'})
        self.assertEqual(settings['providers']['activationRuntime']['limits'], runtime.LIMITS)
        self.assertEqual(settings['providers']['bindings'][-1]['contract'], ACTIVATION)
        with self.assertRaisesRegex(RuntimeError, 'binding-bound'):
            runtime.configure({'providers': {'bindings': [{} for _ in range(16)]}})

    def test_denial_and_installed_identity_precede_any_policy_or_deployment(self):
        for mutation in ('unreaped', 'unknown', 'wrong-error', 'fuel', 'missing-provider'):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as temporary:
                client, node, targets = self.setup_authority(Path(temporary)); denied = refused()
                if mutation == 'unreaped': denied['processReaped'] = False
                elif mutation == 'unknown': denied['response']['outcomeKnown'] = False
                elif mutation == 'wrong-error': denied['response']['error']['code'] = 'incompatible-contract'
                elif mutation == 'fuel': denied['response']['data']['consumption']['cpuFuel'] = '1'
                else: node.startup_record['providers'] = []
                with patch('tools.rust_capsule_node.call', return_value=denied), \
                        patch('tools.rust_capsule_node.deploy') as deploy, self.assertRaises(RuntimeError):
                    runtime.grant(client, node, Path(temporary), targets, {'greeting': 'publication'}, {'invocations': []})
                deploy.assert_not_called(); client.call.assert_not_called()

    def test_uncertain_binding_or_policy_never_grants_or_deploys(self):
        for failed in (0, 1):
            with self.subTest(failed=failed), tempfile.TemporaryDirectory() as temporary:
                client, node, targets = self.setup_authority(Path(temporary))
                answers = [{'outcomeKnown': True, 'category': 'success'} for _ in range(2)]
                answers[failed] = {'outcomeKnown': False, 'category': 'uncertain'}
                client.call.side_effect = answers
                original = copy.deepcopy(targets)
                with patch('tools.rust_capsule_node.call', return_value=refused()), \
                        patch('tools.rust_capsule_node.deploy') as deploy, self.assertRaisesRegex(RuntimeError, '-apply'):
                    runtime.grant(client, node, Path(temporary), targets, {'greeting': 'publication'}, {'invocations': []})
                deploy.assert_not_called(); self.assertEqual(targets, original)

    def test_only_greeting_gains_exact_activation_grant_after_original_clock_denial(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary); client, node, targets = self.setup_authority(directory)
            targets['word-count'] = {'unchanged': True}; original = copy.deepcopy(targets)
            denied = refused(); result = {'invocations': []}
            with patch('tools.rust_capsule_node.call', return_value=denied), \
                    patch('tools.rust_capsule_node.deploy', return_value={'installed': True}) as deploy:
                runtime.grant(client, node, directory, targets, {'greeting': 'publication'}, result)
            self.assertEqual(targets['word-count'], original['word-count'])
            self.assertEqual(deploy.call_args.kwargs['grants'], [*original['greeting']['grants'],
                {'capability': ACTIVATION, 'policy': 'activation-filesystem-allow'}])
            policy = json.loads((directory / 'activation-filesystem-policy.json').read_bytes())['rules'][0]
            self.assertEqual(policy['operations'], runtime.OPERATIONS)
            self.assertEqual(policy['capability'], ACTIVATION)
            self.assertEqual(policy['ceiling'], {'operations': 4096, 'inputBytes': 0,
                'outputBytes': 32768, 'wallTimeMillis': 5000})
            self.assertEqual(policy['services'], [original['greeting']['service']])
            self.assertEqual(result['invocations'], [denied])
            self.assertEqual(result['dotnetFilesystemRuntimeAuthority']['requiredDeclarations'], [CLOCK, ACTIVATION])
            self.assertFalse(result['dotnetFilesystemRuntimeAuthority']['additionalWallEntropyOrHttpAuthority'])

    def test_extra_existing_entropy_or_wall_grants_are_rejected_before_call(self):
        for capability in (RANDOM, WALL):
            with self.subTest(capability=capability), tempfile.TemporaryDirectory() as temporary:
                client, node, targets = self.setup_authority(Path(temporary))
                targets['greeting']['grants'].append({'capability': capability, 'policy': 'unrelated'})
                with patch('tools.rust_capsule_node.call') as call, self.assertRaisesRegex(RuntimeError, 'clock-only-grant'):
                    runtime.grant(client, node, Path(temporary), targets, {'greeting': 'publication'}, {'invocations': []})
                call.assert_not_called(); client.call.assert_not_called()


if __name__ == '__main__':
    unittest.main()
