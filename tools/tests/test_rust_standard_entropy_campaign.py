"""Real campaign protocol/source controls; native operations remain mocked here."""
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import Mock, patch

from tools import rust_standard_entropy_fixture as fixture, rust_standard_entropy_probe as probe
from tools import rust_standard_logging_inputs as standard
from tools import rust_capsule_project as project
from tools.build_snapshot import canonical, digest
from tools.dev_workflow.common import DevError
from tools.phase2_operator_process import WorkflowError


class StandardEntropyCampaign(unittest.TestCase):
    def test_normal_pure_transitive_capture_exact_review_removes_originals_and_preserves_sdk(self):
        for profile in (standard.ENTROPY,):
            with self.subTest(profile=profile), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                app = project.create(root / 'app', 'greeting', runtime_profile=profile)
                original = project.snapshot(app)
                lock = {'selection': {'runtimeProfile': profile}, 'artifacts': [
                    {'role': 'application', 'metadata': {'package': name, 'version': fixture.VERSION}}
                    for name in (fixture.PACKAGE, fixture.RESOURCE, 'getrandom', 'rand_core')]}
                lock['artifacts'][2]['metadata']['version'] = '0.3.4'
                lock['artifacts'][3]['metadata']['version'] = '0.9.3'
                lock['artifacts'].append({'role': 'build-tool', 'metadata': {'package': 'getrandom', 'version': '0.3.4', 'executableKinds': [['custom-build']]}})
                def capture(source, candidate, **_kwargs):
                    self.assertEqual((root / 'outside' / fixture.PACKAGE / 'src/lib.rs').read_text(encoding='utf-8'), fixture.LIBRARY)
                    self.assertEqual((root / 'outside' / fixture.RESOURCE / 'src/text.txt').read_bytes(), b'Gr\xc3\xbc\xc3\x9fe')
                    candidate.write_bytes(canonical(lock))
                    return lock
                def accept(source, candidate, expected):
                    self.assertEqual(expected, digest(candidate.read_bytes()))
                    (source / fixture.LOCK).write_bytes(candidate.read_bytes())
                with patch.object(fixture.authoring, 'author') as authored, \
                        patch.object(fixture.native, 'resolve', side_effect=capture), \
                        patch.object(fixture.review, 'review', side_effect=accept), \
                        patch.object(fixture.review, 'status', return_value={'status': 'verified'}):
                    result = fixture.install(app, root / 'outside', root / 'not-executed-cargo')
                self.assertTrue(result['originalsRemoved'])
                self.assertFalse((root / 'outside' / fixture.PACKAGE).exists())
                self.assertFalse((root / 'outside' / fixture.RESOURCE).exists())
                self.assertEqual((app / 'sdk-lock.json').read_bytes(), original['sdk-lock.json'])
                source = (app / 'src/lib.rs').read_bytes()
                insertion = b'    if let Some(mode) = name.strip_prefix("entropy:") {\n        return Ok(outside_standard_entropy_library::run(mode));\n    }\n'
                self.assertEqual(source.replace(insertion, b'', 1), original['src/lib.rs'])
                self.assertEqual(authored.call_args.kwargs['identity'], fixture.PACKAGE)
                self.assertTrue(result['normalExecutableApprovalRequired'])
                self.assertNotIn('latent', fixture.LIBRARY)
                self.assertIn('getrandom::fill', fixture.LIBRARY)
                self.assertIn('rand_core::OsRng', fixture.LIBRARY)
                self.assertIn('std::collections::HashMap', fixture.LIBRARY)

    def test_wrong_created_profile_refuses_before_source_or_review_mutation(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); app = project.create(root / 'app', 'greeting')
            before = project.snapshot(app)
            with patch.object(fixture.authoring, 'author') as author, self.assertRaisesRegex(DevError, 'explicit-profile'):
                fixture.install(app, root / 'outside', root / 'cargo')
            author.assert_not_called()
            self.assertEqual(project.snapshot(app), before)
            self.assertFalse((root / 'outside').exists())

    def observed(self, *, reaped=True, memory=10, fuel=100, outbound=0, effects=0):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            target = {'generation': 1, 'service': 'examples/my-greeting',
                'budget': {'cpuFuel': 100, 'memoryBytes': 100},
                'grants': [{'capability': probe.RANDOM, 'policy': probe.ALLOW},
                           {'capability': 'other', 'policy': 'keep'}]}
            targets = {'greeting': target}
            policies = []
            def deploy(_client, _path, _publication, *, generation, grants):
                policies.append(grants)
                return {**target, 'generation': int(generation) + 1, 'grants': grants}
            def invoke(_client, _target, _template, _function, arguments, activation):
                mode = arguments[0].removeprefix('entropy:')
                consumption = {'cpuFuel': str(fuel), 'peakMemoryBytes': str(memory),
                    'outboundRequests': str(outbound), 'logBytes': '0', 'effectCount': str(effects)}
                result = {'exitCode': 0, 'processReaped': reaped, 'response': {'outcomeKnown': True,
                    'data': {'consumption': consumption}}, 'decoded': [{'ok': fixture.expected(mode) if mode in fixture.CASES or mode == 'denied' else ''}]}
                if mode in {'trap', 'fuel', 'std-denied'}:
                    code = 'resource-exhausted' if mode == 'fuel' else 'guest-trap'
                    result.update(exitCode=4)
                    result['response']['error'] = {'code': code}
                    result['response']['data']['terminalState'] = code.replace('-', '_')
                return result
            result = {'invocations': [], 'samples': [], 'providerIdle': []}
            with patch('tools.rust_capsule_node.call', side_effect=invoke), \
                    patch('tools.rust_capsule_node.sample', return_value={}) as samples, \
                    patch('tools.rust_capsule_node.provider_idle', return_value={}), \
                    patch('tools.rust_capsule_node.deploy', side_effect=deploy):
                probe.probe(None, directory, targets, {'greeting': 'publication'}, None, result, 17)
            return result, samples.call_count, policies, targets['greeting']

    def test_nine_cases_typed_and_infallible_denials_trap_fuel_and_fresh_recovery_retire(self):
        result, samples, policies, target = self.observed()
        receipt = result['rustStandardEntropy']
        self.assertEqual([row['mode'] for row in receipt['cases']], list(fixture.CASES))
        self.assertEqual([row['mode'] for row in receipt['recovery']], ['policy-budget', 'trap', 'fuel'])
        self.assertEqual(len(result['invocations']), 16)
        self.assertEqual(samples, 16)
        self.assertEqual(len(result['providerIdle']), 16)
        self.assertEqual(policies[0][0]['policy'], probe.DENY)
        self.assertEqual(policies[1], target['grants'])
        self.assertEqual(policies[0][1], policies[1][1])
        self.assertFalse(receipt['rawEntropyRetained'])
        self.assertFalse(receipt['aggregateExhaustionClaimed'])

    def test_unknown_unretired_overbudget_or_unrelated_effects_never_pass(self):
        for change in ({'reaped': False}, {'memory': 101}, {'fuel': 99}, {'outbound': 1}, {'effects': 1}):
            with self.subTest(change=change), self.assertRaisesRegex(WorkflowError, 'rust-entropy-'):
                self.observed(**change)


if __name__ == '__main__': unittest.main()
