"""Explicit random selection uses ordinary consent, provider and policy owners."""
import copy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from tools.dev_workflow import node_fixtures, node_test_grants, node_test_profile, paths, random_fixture, state
from tools.dev_workflow.common import DevError, encode
from tools.guest_runtime_profiles import RUNTIME, profiles


class RandomFixture(unittest.TestCase):
    def selection(self):
        return {'random': {'maximumOperations': 16, 'maximumOutputBytes': 4096}}

    def descriptor(self, language='dotnet'):
        return {'language': language, 'tenant': 'examples', 'service': 'examples/my-greeting'}

    def test_closed_bounds_reject_seeds_unknown_keys_booleans_and_unbounded_values(self):
        selected = self.selection()
        self.assertIs(node_fixtures.validate(selected), selected)
        for field, values in [('maximumOperations', (True, 0, 17, '16', None)),
                              ('maximumOutputBytes', (True, 0, 4097, '4096', None))]:
            for value in values:
                changed = copy.deepcopy(selected); changed['random'][field] = value
                with self.subTest(field=field, value=value), self.assertRaises(DevError):
                    node_fixtures.validate(changed)
        for change in ({'seed': 'captured-bytes'}, {'operations': ['u64-value']}, {'tenant': 'other'}):
            with self.subTest(change=change), self.assertRaises(DevError):
                node_fixtures.validate({'random': {**selected['random'], **change}})

    def test_default_managed_profiles_remain_unchanged_and_selected_configuration_grants_nothing(self):
        original = {'securityProfile': 'local-experimental-v1', 'audit': {'mode': 'durable'}}
        before = copy.deepcopy(original)
        configured, selected = node_test_profile.configuration(original, self.descriptor())
        self.assertEqual(profiles('dotnet'), {'clockMonotonic': RUNTIME['clockMonotonic']})
        self.assertEqual(set(selected), {'clockMonotonic'})
        self.assertNotIn('random', configured['providers'])
        configured, selected = node_test_profile.configuration(original, self.descriptor(), self.selection())
        self.assertEqual(selected['random'], list(random_fixture.PROVIDER))
        self.assertEqual(configured['providers']['random']['identity']['tenant'], 'examples')
        self.assertNotIn('policies', configured)
        self.assertNotIn('grants', configured)
        self.assertEqual(original, before)
        self.assertEqual(profiles('go'), RUNTIME)
        self.assertEqual(profiles('java'), {name: value for name, value in RUNTIME.items() if name != 'random'})

    def test_refused_consent_starts_no_signer_and_creates_no_provider_or_policy_state(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / 'test-uncreated'
            with patch('tools.dev_workflow.node_test_signing.prepare') as sign:
                with self.assertRaisesRegex(DevError, 'consent'):
                    node_test_profile.prepare(root, self.descriptor(), consent=False,
                        admission='signed-fixture', tool_root=Path('/unused'), fixtures=self.selection())
            sign.assert_not_called()
            self.assertFalse(root.exists())

    def prepared(self, root, fixtures):
        state.atomic(root / 'runtime/config', 'node.json', {'credentials': [
            {'tenant': 'examples', 'role': 'operator', 'subject': 'test-operator'}]})
        state.atomic(root, 'test-profile.json', {'fixtures': fixtures})
        return {'random': {'capability': random_fixture.PROVIDER[0], 'configurationDigest': 'sha256:' + '1' * 64}}

    def test_only_explicit_byte_operation_and_selected_ceiling_reach_ordinary_policy_owner(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); (root / 'runtime/config').mkdir(parents=True, mode=0o700)
            installed = self.prepared(root, self.selection()); applied = []
            with patch('tools.dev_workflow.node_test_grants.policy_operations.apply',
                       side_effect=lambda *args: applied.append(args[5])):
                grants = node_test_grants.selection(root, self.descriptor(), 'publication',
                    {'grants': [random_fixture.PROVIDER[0]]}, installed, Mock(), Mock())
            self.assertEqual(len(grants), 1)
            self.assertEqual(applied[0]['restriction'], {'operations': ['bytes']})
            rule = applied[1]['rules'][0]
            self.assertEqual(rule['operations'], ['bytes'])
            self.assertEqual(rule['publications'], ['publication'])
            self.assertEqual(rule['services'], [self.descriptor()['service']])
            self.assertEqual(rule['ceiling'], {'operations': 16, 'inputBytes': 8,
                'outputBytes': 4096, 'wallTimeMillis': 5000})

    def test_unrequested_grants_do_not_publish_policies_and_default_go_operation_is_preserved(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); (root / 'runtime/config').mkdir(parents=True, mode=0o700)
            installed = self.prepared(root, self.selection())
            with patch('tools.dev_workflow.node_test_grants.policy_operations.apply') as apply:
                self.assertEqual(node_test_grants.selection(root, self.descriptor(), 'publication',
                    {'grants': []}, installed, Mock(), Mock()), [])
            apply.assert_not_called()
            self.prepared(root, None); applied = []
            with patch('tools.dev_workflow.node_test_grants.policy_operations.apply',
                       side_effect=lambda *args: applied.append(args[5])):
                node_test_grants.selection(root, self.descriptor('go'), 'publication',
                    {'grants': [random_fixture.PROVIDER[0]]}, installed, Mock(), Mock())
            self.assertEqual(applied[0]['restriction'], {'operations': ['u64-value']})
            self.assertEqual(applied[1]['rules'][0]['ceiling']['operations'], 4096)

    def test_missing_provider_or_invalid_selected_bounds_fail_before_policy_mutation(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); (root / 'runtime/config').mkdir(parents=True, mode=0o700)
            installed = self.prepared(root, self.selection())
            with patch('tools.dev_workflow.node_test_grants.policy_operations.apply') as apply:
                with self.assertRaisesRegex(DevError, 'unsupported'):
                    node_test_grants.selection(root, self.descriptor(), 'publication',
                        {'grants': [random_fixture.PROVIDER[0]]}, {}, Mock(), Mock())
                self.prepared(root, {'random': {'maximumOperations': 17, 'maximumOutputBytes': 4096}})
                with self.assertRaisesRegex(DevError, 'bounds'):
                    node_test_grants.selection(root, self.descriptor(), 'publication',
                        {'grants': [random_fixture.PROVIDER[0]]}, installed, Mock(), Mock())
            apply.assert_not_called()

    def test_real_provider_fixture_requires_exact_initialized_profile_and_selected_bytes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); selected = self.selection()
            paths.write_new(root / 'random.json', encode(selected))
            from tools.dev_workflow.common import digest
            fixture = {'id': 'hash-entropy', 'kind': 'real-provider',
                'configuration': 'random.json', 'identity': digest(encode(selected))}
            cases = [{'fixtures': [fixture]}]
            providers = {'random': {'id': 'random', 'tenant': 'examples',
                'capability': random_fixture.PROVIDER[0], 'profile': random_fixture.PROVIDER[1],
                'service': 'runtime-host', 'configurationEpoch': '1'}}
            self.assertEqual(node_fixtures.initialized(root, cases, selected, providers=providers), {'hash-entropy'})
            for field, value in [('id', 'wrong'), ('tenant', 'other'), ('capability', 'wrong'),
                                  ('profile', 'wrong'), ('service', 'other'), ('configurationEpoch', '2')]:
                changed = copy.deepcopy(providers); changed['random'][field] = value
                self.assertEqual(node_fixtures.initialized(root, cases, selected, providers=changed), set())
            self.assertEqual(node_fixtures.initialized(root, cases, selected, providers={}), set())
            self.assertEqual(node_fixtures.initialized(root, cases,
                {'random': {'maximumOperations': 1, 'maximumOutputBytes': 1}}, providers=providers), set())

    def test_actual_packaged_helper_imports_random_owner_without_checkout_or_ambient_python(self):
        import json
        import os
        import subprocess
        import sys
        import zipfile
        from tools.build_dev_frontend import helper
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); archive = root / 'helper.pyz'
            helper(archive)
            self.assertLess(archive.stat().st_size, 4 * 1024 * 1024)
            with zipfile.ZipFile(archive) as captured:
                self.assertEqual(captured.read('tools/dev_workflow/random_fixture.py'),
                                 Path(random_fixture.__file__).read_bytes())
            code = ('import json,sys;sys.path.insert(0,sys.argv[1]);'
                    'from tools.dev_workflow.random_fixture import ceiling;'
                    'print(json.dumps(ceiling({"maximumOperations":1,"maximumOutputBytes":8})))')
            environment = {'PATH': os.defpath, 'HOME': temporary, 'TEMP': temporary, 'TMP': temporary}
            if os.name == 'nt':
                environment['SystemRoot'] = os.environ['SystemRoot']
            result = subprocess.run([sys.executable, '-I', '-B', '-c', code, str(archive)],
                cwd=root, env=environment, capture_output=True, timeout=15)
            self.assertEqual(result.returncode, 0, result.stderr.decode(errors='replace'))
            self.assertEqual(json.loads(result.stdout), {'operations': 1, 'inputBytes': 8,
                'outputBytes': 8, 'wallTimeMillis': 5000})


if __name__ == '__main__':
    unittest.main()
