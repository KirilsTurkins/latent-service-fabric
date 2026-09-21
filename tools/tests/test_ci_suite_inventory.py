"""Offline dependency selection and versioned inventory contract regression fixtures."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools import ci_profile, ci_suite_inventory as registry
from tools.ci_fast import selected_packages


class InventoryTests(unittest.TestCase):
    def test_inventory_has_all_four_boundaries_and_preserved_recipes(self):
        data = registry.load()
        self.assertEqual(set(data['boundaries']), registry.BOUNDARIES)
        self.assertIn('--doc', data['recipes']['explicit-doctests']['run'])
        self.assertIn('ed25519-dalek/legacy_compatibility', data['recipes']['signing-compatibility']['run'])
        self.assertEqual(len([s for s in data['suites'] if s['mode'] == 'custom']), 2)
        self.assertEqual(len({s['id'] for s in data['suites']}), len(data['suites']))

    def test_invalid_registrations_are_rejected(self):
        data = registry.load()
        changes = [lambda d: d.update(schemaVersion='next'),
                   lambda d: d['suites'].append(d['suites'][0]),
                   lambda d: d['suites'][0].update(timeoutSeconds=0),
                   lambda d: d['suites'][0].update(mode='libtest', minimumCases=0),
                   lambda d: d['suites'][0].update(manifest='../foreign'),
                   lambda d: d['suites'][0].update(mode='custom', listContract='libtest'),
                   lambda d: d['selections']['operator-fixture'].update(names=[])]
        with tempfile.TemporaryDirectory() as directory:
            file = Path(directory) / 'inventory.json'
            for change in changes:
                changed = copy.deepcopy(data); change(changed); file.write_text(json.dumps(changed))
                with self.subTest(change=change), self.assertRaises(ValueError): registry.load(file)
            file.write_text('{"schemaVersion":1,"schemaVersion":2}')
            with self.assertRaises(ValueError): registry.load(file)

    def test_all_deterministic_affected_fixtures_are_offline(self):
        fixtures = registry.read_json(registry.ROOT / 'tools/tests/fixtures/ci-suites/affected.json')
        with patch('subprocess.Popen', side_effect=AssertionError('selection spawned a command')):
            for fixture in fixtures['cases']:
                with self.subTest(case=fixture['name']):
                    decision = ci_profile.classify_paths(fixture['paths'])
                    self.assertEqual(decision.profile, fixture['profile'])
                    self.assertEqual(decision.renderer, fixture['renderer'])
                    if 'packages' in fixture: self.assertEqual(list(decision.fast_packages), fixture['packages'])

    def test_full_fast_build_graph_contains_no_convenience_runtime_helper(self):
        data = registry.load()
        with patch('subprocess.Popen', side_effect=AssertionError('selection invoked Cargo')):
            self.assertEqual(selected_packages(json.dumps(data['fastPackages']), data), data['fastPackages'])
        for value in ('[]', '["latent-testkit"]', '["latent-core","latent-core"]', '{}'):
            with self.subTest(value=value), self.assertRaises(ValueError): selected_packages(value, data)

    def test_a_new_reverse_dependency_prevents_filename_allowlist_bypass(self):
        graph = registry.workspace(registry.ROOT)
        node = graph['latent-node']
        graph['latent-node'] = registry.Package(node.name, node.directory, node.dependencies | {'latent-state'})
        with patch.object(registry, 'workspace', return_value=graph):
            decision = ci_profile.classify_paths(['crates/latent-state/src/lib.rs'])
        self.assertEqual(decision.profile, 'full')
        self.assertTrue(decision.renderer)

    def test_workspace_alias_inherited_optional_dev_build_and_platform_edges(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root/'Cargo.toml').write_text('[workspace]\nmembers=["a","b","c"]\n[workspace.dependencies]\nrenamed={package="a",path="a"}\n')
            for name in ('a','b','c'):
                (root/name).mkdir(); (root/name/'Cargo.toml').write_text(f'[package]\nname="{name}"\nversion="0.1.0"\n')
            with (root/'b/Cargo.toml').open('a') as f:
                f.write('[dev-dependencies]\nrenamed={workspace=true}\n[target.\'cfg(windows)\'.build-dependencies]\nalias={package="c",path="../c",optional=true}\n')
            graph = registry.workspace(root)
            self.assertEqual(graph['b'].dependencies, {'a','c'})
            self.assertEqual(registry.closure(graph, {'a'}, reverse=True), {'a','b'})
            self.assertEqual(registry.closure(graph, {'b'}), {'a','b','c'})
            (root/'c/Cargo.toml').write_text('[package]\nname="wrong"\n')
            with self.assertRaises(ValueError): registry.workspace(root)

    def test_unavailable_or_ambiguous_graph_preserves_full(self):
        for error in (ValueError('ambiguous'), OSError('missing'), KeyError('dependency')):
            with patch.object(registry, 'workspace', side_effect=error):
                decision = ci_profile.classify_paths(['crates/latent-state/src/lib.rs'])
            self.assertEqual((decision.profile, decision.renderer), ('full', True))
