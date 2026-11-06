"""Explicit host provisioning does not change signed guest budgets or grants."""
from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

from tools import rust_thread_http_combined_node as node
from tools.phase2_operator_process import WorkflowError


class CombinedCapacityControls(unittest.TestCase):
    def configuration(self):
        return {
            'securityProfile': 'local-experimental-v1',
            'engine': {'activationStackAccounting': 'activation-owned-v1'},
            'cache': {'entries': 4, 'preparations': 1},
            'workers': {'runtime': 1, 'control': 1},
            'providers': {
                'activationRuntime': {'identity': {'service': 'activation-host'},
                                      'limits': deepcopy(node.http.RUNTIME_LIMITS)},
                'bindings': [{'name': f'original-{index}'} for index in range(6)],
            },
        }

    def test_only_the_combined_diagnostic_provisions_http_completion_owners(self):
        original_limits = deepcopy(node.http.RUNTIME_LIMITS)
        original = self.configuration()
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'node.json'
            path.write_text(json.dumps(original), encoding='utf-8')
            with patch.object(node.http, 'configuration', return_value=path):
                self.assertEqual(node.configure(None, None, None, None), path)
            selected = json.loads(path.read_bytes())
        self.assertEqual(selected['providers']['activationRuntime']['limits'],
                         {**original_limits, 'nativeOwners': 10})
        self.assertEqual(original_limits['nativeOwners'], 8)
        self.assertEqual(node.http.RUNTIME_LIMITS, original_limits)
        self.assertEqual(selected['engine']['activationStackAccounting'], 'activation-owned-v1')
        self.assertEqual(selected['engine']['threadingProfile'], node.PROFILE)
        self.assertEqual(selected['workers'], original['workers'])
        self.assertEqual(selected['cache']['entries'], original['cache']['entries'])
        self.assertEqual(selected['cache']['preparations'], original['cache']['preparations'])
        self.assertTrue(selected['providers']['activationRuntime']['nativeThreads'])
        self.assertEqual(selected['providers']['bindings'][:-1], original['providers']['bindings'])
        self.assertEqual(selected['providers']['bindings'][-1]['contract'], node.NATIVE)

    def test_changed_base_profiles_are_refused_before_the_configuration_is_written(self):
        for change in ('profile', 'owners', 'tasks'):
            with self.subTest(change=change), tempfile.TemporaryDirectory() as temporary:
                value = self.configuration()
                if change == 'profile':
                    value['securityProfile'] = 'production'
                else:
                    key = 'nativeOwners' if change == 'owners' else 'tasks'
                    value['providers']['activationRuntime']['limits'][key] += 1
                path = Path(temporary) / 'node.json'
                before = json.dumps(value).encode()
                path.write_bytes(before)
                with patch.object(node.http, 'configuration', return_value=path):
                    with self.assertRaisesRegex(WorkflowError, 'rust-combined-explicit-local-profile'):
                        node.configure(None, None, None, None)
                self.assertEqual(path.read_bytes(), before)

    def test_host_capacity_does_not_enlarge_provider_grants(self):
        descriptors = [{'id': identity, 'capability': capability, 'tenant': 'examples',
                        'profile': profile, 'configurationEpoch': '1',
                        'configurationDigest': 'sha256:' + '1' * 64}
                       for identity, capability, _, profile, _ in node.PROVIDERS]
        origin = {'scheme': 'http', 'host': '127.0.0.1', 'port': 1234}
        with patch.object(node, 'policy') as policy:
            grants = node.grant(object(), SimpleNamespace(startup_record={'providers': descriptors}),
                                'signed-publication', SimpleNamespace(origin=lambda _: origin))
        self.assertEqual({row['capability'] for row in grants}, set(node.IMPORTS))
        rules = [call.args[3]['rules'][0] for call in policy.call_args_list
                 if call.args[1] == 'policy']
        self.assertEqual(len(rules), 4)
        self.assertTrue(all(rule['ceiling']['wallTimeMillis'] == 5000 for rule in rules))
        native, = [rule for rule in rules if rule['capability'] == node.NATIVE]
        self.assertEqual(native['operations'], ['start'])
        http, = [rule for rule in rules if rule['capability'] == node.http.HTTP]
        self.assertEqual(http['resources']['origins'], [origin])
        self.assertEqual(http['ceiling']['operations'], 64)


if __name__ == '__main__':
    unittest.main()
