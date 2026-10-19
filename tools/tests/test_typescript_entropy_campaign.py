"""Fixture/protocol controls are distinct from the owning signed programme."""
import copy
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from tools import typescript_entropy_probe as probe
from tools.typescript_guest.project import create
from tools.rust_capsule_project import digest, snapshot


class EntropyCampaign(unittest.TestCase):
    def test_selected_greeting_preserves_original_body_and_installs_only_the_exact_random_declaration(self):
        with tempfile.TemporaryDirectory() as temporary:
            app = create(Path(temporary)/'app', 'greeting')
            before = snapshot(app)
            recorded = probe.prepare(app, 'greeting')
            after = snapshot(app)
            prefix = b"import {entropyCase} from './entropy-library.js';\n"
            addition = b"\n    if (name.startsWith('entropy:')) return entropyCase(name.slice(8));"
            self.assertEqual(after['src/main.ts'].removeprefix(prefix).replace(addition, b''), before['src/main.ts'])
            self.assertEqual(after['src/entropy-library.ts'], probe.LIBRARY.encode())
            self.assertEqual(after['wit/world.wit'].replace(b'\n    import latent:random/random@0.1.0;', b''), before['wit/world.wit'])
            self.assertEqual({name: body for name, body in before.items() if name.startswith('vendor/')},
                {name: body for name, body in after.items() if name.startswith('vendor/')})
            lock = json.loads(after['sdk-lock.json'])
            self.assertEqual(lock['template']['sourceDigest'], digest(after['src/main.ts']))
            self.assertEqual(recorded['world'], lock['template']['witDigest'])
            self.assertFalse(recorded['publishedLibraryQualification'])

    def test_unselected_default_component_keeps_the_world_and_requires_concrete_unsupported(self):
        with tempfile.TemporaryDirectory() as temporary:
            app = create(Path(temporary)/'app', 'word-count')
            before = snapshot(app);recorded = probe.prepare(app, 'word-count');after = snapshot(app)
            self.assertEqual(after['wit/world.wit'], before['wit/world.wit'])
            self.assertIn(b"error.message === 'unsupported:Math.random-without-approved-entropy'", after['src/main.ts'])
            self.assertIsNone(recorded['applicationLibrary'])
            self.assertFalse((app/'src/entropy-library.ts').exists())
            self.assertIn(b"throw new Error('undeclared-entropy-returned-a-value')", after['src/main.ts'])

    def test_configuration_has_one_explicit_greeting_binding_and_does_not_replace_existing_providers(self):
        original = {'providers': {'http': {'original': True}, 'bindings': [{'name': 'http-binding'}]}}
        selected = copy.deepcopy(original);probe.configure(selected)
        self.assertEqual(selected['providers']['http'], original['providers']['http'])
        self.assertEqual(selected['providers']['bindings'][0], original['providers']['bindings'][0])
        self.assertEqual(len(selected['providers']['bindings']), 2)
        self.assertEqual(selected['providers']['bindings'][1]['consumerService'], 'examples/my-greeting')
        self.assertEqual(selected['providers']['bindings'][1]['contract'], probe.RANDOM)
        for change in ('installed', 'capacity'):
            selected = copy.deepcopy(original)
            if change == 'installed': selected['providers']['random'] = {'unrelated': True}
            else: selected['providers']['bindings'] = [{'name': str(i)} for i in range(16)]
            before = copy.deepcopy(selected)
            with self.assertRaisesRegex(RuntimeError, 'original-provider-capacity'): probe.configure(selected)
            self.assertEqual(selected, before)

    def test_authority_preserves_existing_grants_and_restricts_real_installed_random_to_scalar_calls(self):
        with tempfile.TemporaryDirectory() as temporary:
            client = SimpleNamespace(directory=Path(temporary), call=lambda *a, **k: None)
            descriptor = {'id': 'ts-entropy', 'capability': probe.RANDOM, 'profile': 'system-random-v1',
                          'tenant': 'examples', 'service': 'entropy-host', 'configurationDigest': 'sha256:'+'a'*64}
            node = SimpleNamespace(startup_record={'providers': [descriptor]})
            target = {'service': 'examples/my-greeting', 'generation': '1', 'grants': [{'capability': 'existing', 'policy': 'kept'}]}
            targets = {'greeting': target};result = {'invocations': [], 'providerIdle': []}
            denied = {'exitCode': 4, 'processReaped': True, 'response': {'outcomeKnown': True,
                'error': {'code': 'permission-denied'}, 'data': {'terminalState': 'rejected',
                'consumption': {'cpuFuel': '0', 'peakMemoryBytes': '0'}}}}
            with patch('tools.rust_capsule_node.call', return_value=denied), \
                    patch('tools.rust_capsule_node.provider_idle', return_value={}), \
                    patch('tools.rust_capsule_node.deploy', return_value=target) as deployed:
                probe.grant(client, node, Path('fixture'), targets, {'greeting': 'published'}, result)
            self.assertEqual(deployed.call_args.kwargs['grants'], [*target['grants'],
                {'capability': probe.RANDOM, 'policy': 'typescript-entropy'}])
            binding = json.loads((client.directory/'entropy-binding.json').read_bytes())
            self.assertEqual(binding['restriction'], {'operations': ['u64-value']})
            policy = json.loads((client.directory/'entropy-policy.json').read_bytes())['rules'][0]
            self.assertEqual(policy['services'], ['examples/my-greeting'])
            self.assertEqual(policy['ceiling'], {'operations': 4096, 'inputBytes': 8, 'outputBytes': 8, 'wallTimeMillis': 5000})

    def test_policy_ceiling_is_separate_zero_input_authority_and_leaves_normal_provider_limits_unchanged(self):
        with tempfile.TemporaryDirectory() as temporary:
            client = SimpleNamespace(directory=Path(temporary), call=lambda *a, **k: None)
            descriptor = {'id': 'ts-entropy', 'capability': probe.RANDOM, 'profile': 'system-random-v1',
                          'tenant': 'examples', 'service': 'entropy-host', 'configurationDigest': 'sha256:'+'a'*64}
            node = SimpleNamespace(startup_record={'providers': [descriptor]})
            target = {'service': 'examples/my-greeting', 'generation': '1', 'grants': [{'capability': 'existing', 'policy': 'kept'}]}
            targets = {'greeting': target};result = {'invocations': [], 'providerIdle': []}
            denied = {'exitCode': 4, 'processReaped': True, 'response': {'outcomeKnown': True,
                'error': {'code': 'permission-denied'}, 'data': {'terminalState': 'rejected',
                'consumption': {'cpuFuel': '0', 'peakMemoryBytes': '0'}}}}
            with patch('tools.rust_capsule_node.call', return_value=denied), \
                    patch('tools.rust_capsule_node.provider_idle', return_value={}), \
                    patch('tools.rust_capsule_node.deploy', return_value=target):
                probe.grant(client, node, Path('fixture'), targets, {'greeting': 'published'}, result)
            normal = json.loads((client.directory/'entropy-policy.json').read_bytes())
            ceiling = json.loads((client.directory/'entropy-policy-ceiling.json').read_bytes())
            self.assertEqual(ceiling['rules'][0]['ceiling']['inputBytes'], 0)
            ceiling['rules'][0]['ceiling']['inputBytes'] = 8
            self.assertEqual(ceiling, normal)
            settings = {'providers': {'bindings': []}}
            probe.configure(settings)
            self.assertEqual(set(settings['providers']['random']), {'identity'})
            self.assertIn('index < 8193', probe.LIBRARY)  # Original compiled guest stays byte-identical.

    def test_real_programme_requires_all_six_values_original_budgets_and_retirement_samples(self):
        def invocation(client, target, template, function, arguments, label):
            mode = arguments[0].split(':')[1]
            value = 681 if mode == 'undeclared' else 'entropy:budget:bounded' if mode == 'budget' else 'entropy:'+mode+':ok'
            return {'processReaped': True, 'activation': label, 'decoded': [{'ok': value}],
                    'response': {'data': {'consumption': {'cpuFuel': '10', 'peakMemoryBytes': '1024',
                    'outboundRequests': 0, 'childCalls': 0, 'logBytes': '0', 'effectCount': 0}}}}
        def expected(client, row, value): self.assertEqual(row['decoded'], value)
        result = {'invocations': [], 'samples': [], 'providerIdle': []}
        target = {'budget': {'cpuFuel': 100, 'memoryBytes': 4096}, 'generation': '1',
                  'grants': [{'capability': 'existing', 'policy': 'kept'},
                             {'capability': probe.RANDOM, 'policy': 'typescript-entropy'}]}
        with patch('tools.rust_capsule_node.call', side_effect=invocation), \
                patch('tools.rust_capsule_node.assert_value', side_effect=expected), \
                patch('tools.rust_capsule_node.provider_idle', return_value={}), \
                patch('tools.rust_capsule_node.sample', return_value={}) as sampled, \
                patch('tools.rust_capsule_node.deploy', side_effect=lambda *a, **k: {**target, 'grants': k['grants']}) as deployed:
            probe.probe(None, {'greeting': target, 'word-count': target}, None, result, 5, Path('fixture'), {'greeting': 'published'})
        self.assertEqual([row['case'] for row in result['typescriptStandardEntropy']['cases']], ['undeclared', *probe.CASES])
        self.assertEqual(len(result['invocations']), 6)
        self.assertEqual(sampled.call_count, 6)
        self.assertFalse(result['typescriptStandardEntropy']['cryptographicAPI'])
        self.assertEqual(deployed.call_count, 2)
        self.assertEqual(deployed.call_args_list[0].kwargs['grants'], [target['grants'][0],
            {'capability': probe.RANDOM, 'policy': 'typescript-entropy-policy-ceiling'}])
        self.assertEqual(deployed.call_args_list[1].kwargs['grants'], target['grants'])
        self.assertFalse(result['typescriptStandardEntropy']['providerAggregateExhaustionQualified'])
        self.assertEqual([row['randomInputBytesPerCall'] for row in result['typescriptStandardEntropy']['policyTransitions']], [0, 8])

    def test_selector_refuses_other_languages_aliases_and_competing_programmes_before_output(self):
        from tools.run_rust_capsule_workflow import run
        for arguments in ({'language': 'go', 'standard_typescript_entropy': True},
                          {'language': 'typescript', 'standard_typescript_entropy': 1},
                          {'language': 'typescript', 'standard_typescript_entropy': True, 'standard_typescript_console': True},
                          {'language': 'typescript', 'standard_typescript_entropy': True, 'captured_npm_private': True}):
            with tempfile.TemporaryDirectory() as temporary:
                output = Path(temporary)/'not-created'
                with self.assertRaisesRegex(RuntimeError, 'typescript-standard-entropy-language'):
                    run(Path('missing'), Path('missing'), Path('missing'), output, **arguments)
                self.assertFalse(output.exists())


if __name__ == '__main__':
    unittest.main()
