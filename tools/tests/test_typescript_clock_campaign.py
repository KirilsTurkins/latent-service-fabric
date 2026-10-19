"""Explicit clock-policy/protocol controls, separate from real signed execution."""
import copy
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from tools import typescript_standard_clock_probe as probe


class ClockCampaign(unittest.TestCase):
    def test_configure_keeps_existing_provider_and_installs_only_greeting_clock_bindings(self):
        settings = {'providers': {'http': {'kept': True}, 'bindings': [{'name': 'old'}]}}
        probe.configure(settings)
        self.assertEqual(settings['providers']['http'], {'kept': True})
        self.assertEqual(len(settings['providers']['bindings']), 3)
        self.assertEqual(settings['providers']['bindings'][0], {'name': 'old'})
        self.assertEqual({r['consumerService'] for r in settings['providers']['bindings'][1:]}, {'examples/my-greeting'})
        for providers in ({'clockWall': {}, 'bindings': []}, {'bindings': [{'name': str(i)} for i in range(15)]}):
            source = {'providers': providers};before = copy.deepcopy(source)
            with self.assertRaisesRegex(RuntimeError, 'original-provider-capacity'): probe.configure(source)
            self.assertEqual(source, before)

    def test_each_missing_clock_is_refused_before_guest_and_only_both_exact_sources_are_granted(self):
        with tempfile.TemporaryDirectory() as temporary:
            client = SimpleNamespace(directory=Path(temporary), call=lambda *a, **k: None)
            installed = [{'id': identity, 'capability': capability, 'profile': profile, 'tenant': 'examples',
                          'service': 'clock-host', 'configurationDigest': 'sha256:'+'a'*64}
                         for identity, capability, profile, _ in probe.PROFILES.values()]
            node = SimpleNamespace(startup_record={'providers': installed})
            target = {'service': 'examples/my-greeting', 'generation': '1', 'grants': []}
            targets = {'greeting': target};result = {'invocations': [], 'providerIdle': []}
            row = {'processReaped': True, 'exitCode': 4, 'response': {'outcomeKnown': True,
                'error': {'code': 'permission-denied'}, 'data': {'terminalState': 'rejected',
                'consumption': {'cpuFuel': '0', 'peakMemoryBytes': '0'}}}}
            with patch('tools.rust_capsule_node.call', return_value=row), \
                    patch('tools.rust_capsule_node.provider_idle', return_value={}), \
                    patch('tools.rust_capsule_node.deploy', side_effect=lambda *a, **k: {**target, 'grants': k['grants']}) as deployed:
                probe.grant(client, node, Path('fixture'), targets, {'greeting': 'published'}, result)
            self.assertEqual(len(result['invocations']), 3)
            self.assertEqual([len(c.kwargs['grants']) for c in deployed.call_args_list], [1, 1, 2])
            self.assertNotEqual(deployed.call_args_list[0].kwargs['grants'], deployed.call_args_list[1].kwargs['grants'])
            for identity, capability, _profile, operation in probe.PROFILES.values():
                document = json.loads((client.directory/(identity+'-policy.json')).read_bytes())['rules'][0]
                self.assertEqual(document['capability'], capability)
                self.assertEqual(document['operations'], [operation])
                self.assertEqual(document['services'], ['examples/my-greeting'])
                self.assertEqual(document['ceiling'], {'operations': 4096, 'inputBytes': 0, 'outputBytes': 32768, 'wallTimeMillis': 5000})

    def test_all13_values_and_two_terminal_fresh_pairs_preserve_original_caps_and_idle_samples(self):
        target = {'budget': {'cpuFuel': 100, 'memoryBytes': 4096}}
        result = {'invocations': [], 'samples': [], 'providerIdle': []}
        def call(client, target, template, function, arguments, label):
            mode = arguments[0].removeprefix('clock:')
            failed = mode in {'trap', 'fuel'}
            code = 'resource-exhausted' if mode == 'fuel' else 'guest-trap'
            value = 681 if template == 'word-count' else probe.expected(mode)
            return {'processReaped': True, 'activation': label, 'exitCode': 4 if failed else 0,
                'decoded': [{'ok': value}], 'response': {'outcomeKnown': True, 'error': {'code': code},
                'data': {'terminalState': code.replace('-', '_'), 'consumption': {'cpuFuel': '100' if mode == 'fuel' else '10',
                'peakMemoryBytes': '1024', 'outboundRequests': 0, 'childCalls': 0, 'logBytes': '0', 'effectCount': 0}}}}
        def exact(client, row, value): self.assertEqual(row['decoded'], value)
        with patch('tools.rust_capsule_node.call', side_effect=call), \
                patch('tools.rust_capsule_node.assert_value', side_effect=exact), \
                patch('tools.rust_capsule_node.provider_idle', return_value={}), \
                patch('tools.rust_capsule_node.sample', return_value={}):
            probe.probe(None, {'greeting': target, 'word-count': target}, None, result, 5)
        self.assertEqual(len(result['invocations']), 17)
        self.assertEqual(len(result['samples']), 17)
        self.assertEqual(len(result['typescriptStandardClocks']['cases']), 13)
        self.assertEqual([r['case'] for r in result['typescriptStandardClocks']['recovery']], ['trap', 'fuel'])

    def test_selector_refuses_other_languages_aliases_or_other_programmes_before_any_output(self):
        from tools.run_rust_capsule_workflow import run
        for options in ({'language': 'go', 'standard_typescript_clocks': True},
                        {'language': 'typescript', 'standard_typescript_clocks': 1},
                        {'language': 'typescript', 'standard_typescript_clocks': True, 'standard_typescript_entropy': True},
                        {'language': 'typescript', 'standard_typescript_clocks': True, 'captured_npm_private': True}):
            with tempfile.TemporaryDirectory() as temporary:
                output = Path(temporary)/'never-created'
                with self.assertRaisesRegex(RuntimeError, 'typescript-standard-clocks-language'):
                    run(Path('missing'), Path('missing'), Path('missing'), output, **options)
                self.assertFalse(output.exists())


if __name__ == '__main__':
    unittest.main()
