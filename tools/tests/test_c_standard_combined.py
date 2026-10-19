"""Explicit composed libc port, captured sources and independent grant gates."""
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from tools import application_dependencies as dependencies, c_capsule_project as project
from tools.build_snapshot import digest
from tools.c_application_dependencies import selected
from tools.c_guest import standard_facilities as facilities
from tools.c_guest.compiler import Compiler
from tools import c_standard_combined_probe as probe


class StandardCombined(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def test_combined_profile_derives_exact_union_without_mutating_inputs_or_default(self):
        root = project.create(self.root / 'project', 'greeting')
        original = project.snapshot(root)
        derived = self.root / 'derived'
        facilities.stage(root / 'wit', 'examples:greeting/service@1.0.0', derived,
                         project.ROOT / 'wit/platform', profile=facilities.COMBINED_PROFILE)
        text = (derived / 'world.wit').read_text()
        expected = (*facilities.IMPORTS, 'latent:log/log@0.1.0')
        self.assertEqual(facilities.PROFILE_IMPORTS[facilities.COMBINED_PROFILE], expected)
        for name in expected:
            self.assertEqual(text.count('import ' + name + ';'), 1)
        self.assertEqual({path.name for path in (derived / 'deps').iterdir()}, {'clock', 'random', 'log'})
        self.assertNotIn('wasi:', text)
        self.assertEqual(project.snapshot(root), original)
        self.assertEqual(facilities.selected_profile({}), facilities.DEFAULT)
        self.assertEqual(facilities.PROFILE_SOURCES[facilities.PROFILE], ('standard-clock-entropy.c',))
        self.assertEqual(facilities.PROFILE_SOURCES[facilities.LOGGING_PROFILE], ('standard-stdio.c',))
        self.assertEqual(facilities.PROFILE_SOURCES[facilities.COMBINED_PROFILE],
                         ('standard-clock-entropy.c', 'standard-stdio.c'))

    def test_combined_import_authority_and_graph_profile_cannot_be_borrowed(self):
        root = project.create(self.root / 'project', 'greeting')
        path = root / 'wit/world.wit'
        original = path.read_text()
        path.write_text(original.replace('world service {',
            'world service { import latent:log/log@0.1.0;'))
        with self.assertRaisesRegex(ValueError, 'imports-must-be-owned-by-profile'):
            facilities.stage(root / 'wit', 'service', self.root / 'derived', project.ROOT / 'wit/platform',
                             profile=facilities.COMBINED_PROFILE)
        self.assertFalse((self.root / 'derived').exists())
        for other in (facilities.DEFAULT, facilities.PROFILE, facilities.LOGGING_PROFILE):
            with self.subTest(other=other), self.assertRaisesRegex(ValueError, 'selection-mismatch'):
                facilities.selected_profile({'runtimeProfile': facilities.COMBINED_PROFILE},
                                             {'selection': {'runtimeProfile': other}})

    def test_outside_combined_library_is_offline_captured_with_original_sdk_and_limits(self):
        root = project.create(self.root / 'project', 'greeting')
        sdk = (root / 'sdk-lock.json').read_bytes()
        before = json.loads((root / 'capsule-project.json').read_bytes())
        proof = probe.prepare(root)
        self.assertTrue(proof['originalLibraryRemoved'])
        self.assertEqual((root / 'sdk-lock.json').read_bytes(), sdk)
        files = project.snapshot(root)
        value, _, _ = project.validate(files)
        self.assertEqual(value['runtimeProfile'], facilities.COMBINED_PROFILE)
        self.assertEqual(value['limits'], {**before['limits'], 'logBytes': 16384})
        output, work = self.root / 'output', self.root / 'work'
        output.mkdir(); work.mkdir()
        closure = dependencies.prepare(root, work, output, 'c')
        inputs = selected(closure, compiler_digest=digest(b'compiler'), runtime_digest=digest(b'runtime'),
                          runtime_profile=facilities.COMBINED_PROFILE)
        self.assertEqual(len(inputs.sources), 1)
        actual = inputs.sources[0].read_bytes()
        self.assertEqual(digest(actual), proof['originalLibrary']['facilities_probe.c'])
        for ordinary in (b'clock_gettime(', b'getentropy(', b'printf(', b'fprintf(stderr,'):
            self.assertIn(ordinary, actual)
        self.assertNotIn(b'latent_', actual)
        self.assertIn(b'__attribute__((constructor))', actual)
        self.assertIn(b'initialized != 1', actual)
        self.assertEqual(inputs.receipt['runtimeProfile'], facilities.COMBINED_PROFILE)
        closure.check_unchanged()

    def test_combined_compiler_uses_existing_stdio_adapter_and_other_profiles_stay_separate(self):
        source = self.root / 'library.c'; source.write_text('int value;')
        compiler = Compiler.__new__(Compiler)
        compiler.sdk, compiler.platform, compiler.commands, compiler.isolation = project.ROOT / 'sdk/c-guest', None, None, None
        compiler.validate_static_libraries = lambda *args: None
        compiler.check_unchanged = lambda: None
        calls = []
        compiler.run = lambda *args: calls.append(args) or ''
        def generate(run, wit, world, destination, platform):
            destination.mkdir()
            return destination, {'source': 'controlled-binding-boundary'}
        for ordinal, profile in enumerate((facilities.DEFAULT, facilities.PROFILE,
                                            facilities.LOGGING_PROFILE, facilities.COMBINED_PROFILE)):
            calls.clear()
            with self.subTest(profile=profile), patch('tools.c_guest.compiler.generate', generate):
                compiler.compile([source], self.root / 'wit', 'service', self.root / str(ordinal),
                                 runtime_profile=profile)
                parses = [call for call in calls if call[:2] == ('wasm-tools', 'parse')]
                component = [call for call in calls if call[:3] == ('wasm-tools', 'component', 'new')]
                logging = profile in (facilities.LOGGING_PROFILE, facilities.COMBINED_PROFILE)
                self.assertEqual(len(parses), int(logging))
                self.assertEqual('--adapt' in component[0], logging)
                if logging:
                    self.assertEqual(parses[0][2], str(compiler.sdk / 'src/standard-stdio.wat'))

    def test_combined_selection_requires_explicit_bool_c_and_exclusive_profile(self):
        from tools.run_rust_capsule_workflow import run
        for language, combined, clocks, logging in (('java', True, False, False), ('c', 1, False, False),
                ('c', 'yes', False, False), ('c', True, True, False), ('c', True, False, True)):
            output = self.root / 'must-not-exist'
            with self.subTest(language=language, combined=combined, clocks=clocks, logging=logging), \
                    self.assertRaisesRegex(RuntimeError, 'c-standard-combined-language'):
                run(Path('missing'), Path('missing'), Path('missing'), output, language=language,
                    c_standard_combined=combined, c_standard_facilities=clocks, c_standard_logging=logging)
            self.assertFalse(output.exists())

    def test_each_grant_is_independently_required_with_zero_execution_and_idle_samples(self):
        from tools.guest_runtime_profiles import profiles
        client = SimpleNamespace(directory=self.root, call=lambda *args: None)
        providers = {**profiles('c'), 'log': ('latent:log/log@0.1.0', 'activation-log-v1', 'write', 'log')}
        node = SimpleNamespace(startup_record={'providers': [dict(id=name, capability=value[0], profile=value[1],
            tenant='examples', service='runtime-host', configurationDigest=digest(b'configuration'))
            for name, value in providers.items()]})
        targets = {'greeting': {'generation': '1', 'service': 'examples/my-greeting'}}
        result = {'invocations': [], 'providerIdle': []}
        denied = {'exitCode': 4, 'response': {'outcomeKnown': True, 'error': {'code': 'permission-denied'},
            'data': {'terminalState': 'rejected', 'consumption': {'cpuFuel': '0', 'peakMemoryBytes': '0'}}}}
        granted = []
        def deploy(client, fixture, publication, generation, grants):
            granted.append(grants)
            return {**targets['greeting'], 'generation': str(int(generation) + 1)}
        with patch('tools.rust_capsule_node.call', side_effect=[denied] * 4 + [{}] * 6) as calls, \
                patch('tools.rust_capsule_node.deploy', deploy), \
                patch('tools.rust_capsule_node.assert_value') as values, \
                patch('tools.rust_capsule_node.provider_idle', return_value={'owned': 0}):
            probe.grant_and_probe(client, node, self.root, targets, {'greeting': 'publication'}, result)
        self.assertEqual([len(grants) for grants in granted], [3, 3, 3, 3, 4])
        for ordinal, grants in enumerate(granted[:-1]):
            self.assertEqual(grants, [step for index, step in enumerate(granted[-1]) if index != ordinal])
        self.assertEqual([row['capability'] for row in granted[-1]], list(facilities.PROFILE_IMPORTS[facilities.COMBINED_PROFILE]))
        self.assertEqual(calls.call_count, 10)
        self.assertEqual(values.call_count, 6)
        self.assertEqual(len(result['providerIdle']), 10)
        self.assertEqual(len(result['cStandardCombinedGrantSteps']), 4)
        log = json.loads((self.root / 'log-combined-policy.json').read_bytes())['rules'][0]
        self.assertEqual(log['resources'], {'kind': 'log', 'levels': ['info', 'error']})
        self.assertEqual(log['ceiling'], {'operations': 64, 'inputBytes': 16384, 'outputBytes': 0, 'wallTimeMillis': 5000})
        random = json.loads((self.root / 'random-combined-policy.json').read_bytes())['rules'][0]
        self.assertEqual(random['operations'], ['bytes'])
        self.assertEqual(random['ceiling']['outputBytes'], 65536)


if __name__ == '__main__':
    unittest.main()
