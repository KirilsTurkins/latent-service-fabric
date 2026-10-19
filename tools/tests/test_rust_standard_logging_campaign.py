"""Real campaign protocol/source controls; native operations remain mocked here."""
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import Mock, patch

from tools import rust_standard_logging_fixture as fixture, rust_standard_logging_probe as probe
from tools import rust_standard_logging_inputs as standard
from tools import rust_capsule_project as project
from tools.build_snapshot import canonical, digest
from tools.dev_workflow.common import DevError


class StandardStdioCampaign(unittest.TestCase):
    def selector(self, directory, profile=standard.PROFILE):
        project.write_json(directory / 'stdio-probe.json', {'formatVersion': 1, 'runtimeProfile': profile})

    def test_normal_pure_transitive_capture_exact_review_removes_originals_and_preserves_sdk(self):
        for profile in (standard.CLOSED, standard.PROFILE):
            with self.subTest(profile=profile), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                app = project.create(root / 'app', 'greeting', runtime_profile=profile)
                original = project.snapshot(app)
                lock = {'selection': {'runtimeProfile': profile}, 'executableInputs': [], 'artifacts': [
                    {'role': 'application', 'metadata': {'package': name, 'version': fixture.VERSION}}
                    for name in (fixture.PACKAGE, fixture.RESOURCE)]}
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
                    result = fixture.install(app, root / 'outside', root / 'not-executed-cargo', profile)
                self.assertTrue(result['originalsRemoved'])
                self.assertFalse((root / 'outside' / fixture.PACKAGE).exists())
                self.assertFalse((root / 'outside' / fixture.RESOURCE).exists())
                self.assertEqual((app / 'sdk-lock.json').read_bytes(), original['sdk-lock.json'])
                source = (app / 'src/lib.rs').read_bytes()
                insertion = b'    if let Some(mode) = name.strip_prefix("stdio:") {\n        return Ok(outside_standard_stdio_library::run(mode));\n    }\n'
                self.assertEqual(source.replace(insertion, b'', 1), original['src/lib.rs'])
                self.assertEqual(authored.call_args.kwargs['identity'], fixture.PACKAGE)
                self.assertEqual(result['executableInputs'], [])
                self.assertNotIn('latent', fixture.LIBRARY)
                self.assertIn('std::io', fixture.LIBRARY)

    def test_wrong_created_profile_refuses_before_source_or_review_mutation(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); app = project.create(root / 'app', 'greeting')
            before = project.snapshot(app)
            with patch.object(fixture.authoring, 'author') as author, self.assertRaisesRegex(DevError, 'created-profile'):
                fixture.install(app, root / 'outside', root / 'cargo', standard.PROFILE)
            author.assert_not_called()
            self.assertEqual(project.snapshot(app), before)
            self.assertFalse((root / 'outside').exists())

    def observed(self, *, profile=standard.PROFILE, logged=32, reaped=True, fuel=100, memory=10, outbound=0):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary); self.selector(directory, profile)
            def invoke(_client, _target, _template, _function, arguments, activation):
                mode = arguments[0].removeprefix('stdio:')
                consumption = {'cpuFuel': str(fuel), 'peakMemoryBytes': str(memory), 'outboundRequests': str(outbound),
                    'logBytes': str(logged if mode in probe.LOGGED or mode in {'trap', 'fuel'} else 0)}
                result = {'exitCode': 0, 'processReaped': reaped, 'response': {'outcomeKnown': True,
                    'data': {'consumption': consumption}}, 'decoded': [
                        {'ok': 'ordinary-stdio:' + mode + '|resource=Gr\u00fc\u00dfe|fresh=1'}]}
                if mode in {'trap', 'fuel'}:
                    code = 'guest-trap' if mode == 'trap' else 'resource-exhausted'
                    result.update(exitCode=4)
                    result['response']['error'] = {'code': code}
                    result['response']['data']['terminalState'] = code.replace('-', '_')
                return result
            result = {'invocations': [], 'samples': [], 'providerIdle': []}
            with patch('tools.rust_capsule_node.call', side_effect=invoke), \
                    patch('tools.rust_capsule_node.sample', return_value={}) as samples, \
                    patch('tools.rust_capsule_node.provider_idle', return_value={}):
                probe.probe(None, {'budget': {'cpuFuel': 100, 'memoryBytes': 100, 'logBytes': 16384}},
                            directory, None, result, 17)
            return result, samples.call_count

    def test_ten_standard_cases_and_two_trap_fuel_fresh_pairs_require_physical_samples(self):
        result, samples = self.observed()
        actual = result['rustStandardStdio']
        self.assertEqual([row['mode'] for row in actual['cases'][:10]], list(probe.CASES))
        self.assertEqual([row['mode'] for row in actual['recovery']], ['trap', 'fuel'])
        self.assertEqual(len(result['invocations']), 14)
        self.assertEqual(samples, 14)
        self.assertFalse(actual['concurrencyQualified'])
        for change, code in (({'reaped': False}, 'process-not-reaped'), ({'fuel': 99}, 'original-fuel-bound'),
                             ({'logged': 0}, 'log-consumption'), ({'memory': 101}, 'consumption-bounds'),
                             ({'outbound': 1}, 'consumption-bounds')):
            with self.subTest(change=change), self.assertRaisesRegex(DevError, code): self.observed(**change)

    def test_closed_stdio_is_three_separate_zero_log_fresh_invocations(self):
        result, samples = self.observed(profile=standard.CLOSED)
        self.assertEqual(len(result['invocations']), 3)
        self.assertEqual(samples, 3)
        self.assertEqual(result['rustStandardStdio']['recovery'], [])
        self.assertTrue(all(row['mode'] == 'closed' for row in result['rustStandardStdio']['cases']))

    def test_explicit_provider_grant_preserves_existing_grants_and_denies_before_guest(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); self.selector(root)
            client = SimpleNamespace(directory=root, call=Mock(return_value={}))
            node = SimpleNamespace(startup_record={'providers': [{'id': 'log', 'capability': standard.LOG,
                'profile': 'activation-log-v1', 'tenant': 'examples', 'service': 'runtime-host',
                'configurationDigest': digest(b'public fixed log fixture')}]})
            original = [{'capability': 'latent:clock/monotonic@0.1.0', 'policy': 'existing'}]
            target = {'service': 'examples/my-greeting', 'generation': '1', 'grants': original}
            denied = {'exitCode': 4, 'response': {'category': 'permission-denied', 'error': {'code': 'permission-denied'},
                'outcomeKnown': True, 'data': {'terminalState': 'rejected',
                    'consumption': {'cpuFuel': '0', 'peakMemoryBytes': '0', 'effectCount': 0}}}}
            result = {'invocations': []}
            with patch('tools.rust_capsule_node.call', return_value=denied), \
                    patch('tools.rust_capsule_node.deploy', return_value={}) as deploy:
                probe.grant(client, node, root, {'greeting': target}, {'greeting': 'publication'}, result)
            self.assertEqual(deploy.call_args.kwargs['grants'], [*original,
                {'capability': standard.LOG, 'policy': 'rust-standard-stdio'}])
            self.assertEqual(len(result['invocations']), 2)

    def test_selector_rejects_foreign_language_bool_alias_or_competing_suite_before_output(self):
        from tools.run_rust_capsule_workflow import run
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / 'absent'
            for arguments in ({'language': 'go', 'rust_standard_stdio': True},
                              {'language': 'rust', 'rust_standard_stdio': 1},
                              {'language': 'rust', 'rust_standard_stdio': True, 'captured_git_component': True}):
                with self.subTest(arguments=arguments), self.assertRaisesRegex(RuntimeError, 'Rust-stdio-language'):
                    run(Path('missing'), Path('missing'), Path('missing'), output, **arguments)
                self.assertFalse(output.exists())

    def test_same_products_reuse_rejects_companion_bytes_even_when_marker_unchanged(self):
        from tools.qualify_rust_standard_logging import companions, COMPANIONS
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); qualified = {'builds': {}}
            for name in COMPANIONS:
                directory = root / 'builds' / name; directory.mkdir(parents=True)
                marker = {}
                for filename, field in (('component.wasm', 'componentDigest'), ('source-inputs.json', 'sourceDigest'),
                                         ('build-observation.json', 'observationDigest')):
                    raw = (name + '/' + filename).encode()
                    (directory / filename).write_bytes(raw); marker[field] = digest(raw)
                project.write_json(directory / 'BUILD-COMPLETE.json', marker)
                qualified['builds'][name] = marker
            original = companions(root, qualified)
            self.assertEqual(len(original), 12)
            for filename in ('component.wasm', 'source-inputs.json', 'build-observation.json'):
                path = root / 'builds' / COMPANIONS[0] / filename
                before = path.read_bytes(); path.write_bytes(b'changed')
                with self.subTest(filename=filename), self.assertRaisesRegex(DevError, 'companion-bytes'):
                    companions(root, qualified)
                path.write_bytes(before)
            self.assertEqual(companions(root, qualified), original)


if __name__ == '__main__': unittest.main()
