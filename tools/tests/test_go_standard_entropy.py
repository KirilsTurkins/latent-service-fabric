"""Source/admission/retirement protocol controls, not signed entropy evidence."""
import copy
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from tools import go_standard_entropy_fixture as fixture, go_standard_entropy_probe as probe
from tools import qualify_go_standard_entropy as qualification
from tools.go_capsule_project import create
from tools.dev_workflow.common import DevError
from tools.phase3_resource_identity import file_identity
from tools.rust_capsule_project import digest, TEMPLATES


class StandardEntropy(unittest.TestCase):
    def test_outside_capture_retains_original_sdk_and_exact_review_then_removes_both_modules(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary); app = create(base / 'app', 'greeting', runtime_profile=fixture.PROFILE)
            original = (app / 'src/main.go').read_bytes(); sdk = (app / 'sdk-lock.json').read_bytes()
            accepted = {'selection': {'runtimeProfile': fixture.PROFILE}, 'executableInputs': [], 'artifacts': [
                {'id': name, 'role': 'application', 'dependencies': [fixture.CHILD] if name == fixture.PARENT else [],
                 'metadata': {'module': name, 'version': fixture.VERSION, 'assetType': 'local-module'}}
                for name in (fixture.PARENT, fixture.CHILD)]}
            def capture(_app, candidate, **kwargs):
                self.assertEqual((base / 'outside/resource/message.txt').read_bytes(), bytes((71, 114, 195, 188, 195, 159, 101)))
                self.assertEqual((base / 'outside/library/library.go').read_text(), fixture.LIBRARY)
                candidate.write_text(json.dumps(accepted), encoding='utf-8')
                return accepted
            def reviewed(_app, candidate, identity):
                self.assertEqual(identity, digest(candidate.read_bytes()))
                (app / 'latent.dependencies.lock.json').write_bytes(candidate.read_bytes())
            with patch.object(fixture.native, 'edit') as edited, patch.object(fixture.native, 'create_lock') as locked, \
                    patch.object(fixture, 'resolve', side_effect=capture), patch.object(fixture.review, 'review', side_effect=reviewed), \
                    patch.object(fixture.review, 'status', return_value={'status': 'verified'}):
                result = fixture.install(app, base / 'outside', Path('never-invoked-go'))
            self.assertEqual([row.kwargs['identity'] for row in edited.call_args_list], [fixture.PARENT, fixture.CHILD])
            locked.assert_called_once()
            self.assertTrue(result['originalsRemoved'])
            self.assertFalse((base / 'outside/library').exists()); self.assertFalse((base / 'outside/resource').exists())
            self.assertEqual((app / 'sdk-lock.json').read_bytes(), sdk)
            modified = (app / 'src/main.go').read_bytes()
            modified = modified.replace(b'\n    entropy "' + fixture.PARENT.encode() + b'"', b'', 1)
            added = b'\n    if strings.HasPrefix(name, "entropy:") { return wit.Ok[string, string](entropy.Run(strings.TrimPrefix(name, "entropy:"))) }'
            self.assertEqual(modified.replace(added, b'', 1), original)
            self.assertFalse(result['customReader']); self.assertFalse(result['randomPayloadRetained'])

    def test_foreign_profile_refuses_before_outside_or_application_mutation(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary); app = create(base / 'app', 'greeting', runtime_profile='go-component-activation-v4')
            before = (app / 'src/main.go').read_bytes()
            with self.assertRaisesRegex((RuntimeError, DevError), 'default-profile-required'):
                fixture.install(app, base / 'outside', Path('absent'))
            self.assertFalse((base / 'outside').exists())
            self.assertEqual((app / 'src/main.go').read_bytes(), before)

    def test_compiler_observation_requires_real_standard_api_and_transitive_embed_selection(self):
        value = {'packages': [{'importPath': name, 'standard': True, 'embedFiles': []}
                             for name in ('crypto/rand', 'syscall')] + [
            {'importPath': fixture.CHILD, 'standard': False, 'embedFiles': ['message.txt']}]}
        qualification.selected_packages(value)
        for mode in ('nonstandard', 'missing', 'duplicate', 'unselected-resource'):
            changed = copy.deepcopy(value)
            if mode == 'nonstandard': changed['packages'][0]['standard'] = False
            elif mode == 'missing': changed['packages'].pop(0)
            elif mode == 'duplicate': changed['packages'].append(changed['packages'][0])
            else: changed['packages'][-1]['embedFiles'] = []
            with self.subTest(mode=mode), self.assertRaisesRegex((RuntimeError, DevError), 'go-entropy-'):
                qualification.selected_packages(changed)

    def test_qualified_products_require_current_source_and_actual_companion_bytes(self):
        current = {'source': 'controlled current source'}
        with tempfile.TemporaryDirectory() as temporary, patch.object(qualification, 'inputs', return_value=current):
            base = Path(temporary); binaries = base / 'native-binaries'; binaries.mkdir()
            receipt = {'schemaVersion': 'latent.go-capsule.qualification.v1', 'status': 'passed', 'binaries': {}, 'builds': {}}
            for name in qualification.PRODUCTS:
                path = binaries / name.replace('/', '-'); path.write_bytes(name.encode())
                receipt['binaries'][name] = file_identity(path)
            for name in TEMPLATES:
                if name == 'greeting': continue
                path = base / 'builds' / name; path.mkdir(parents=True)
                marker = {}
                for filename, field in (('component.wasm', 'componentDigest'), ('source-inputs.json', 'sourceDigest'),
                                         ('build-observation.json', 'observationDigest')):
                    raw = (name + filename).encode(); (path / filename).write_bytes(raw); marker[field] = digest(raw)
                (path / 'BUILD-COMPLETE.json').write_text(json.dumps(marker), encoding='utf-8'); receipt['builds'][name] = marker
            source = base / 'source-inputs.json'; source.write_text(json.dumps(current), encoding='utf-8')
            receipt['sourceIdentityDigest'] = digest(source.read_bytes())
            (base / 'qualification.json').write_text(json.dumps(receipt), encoding='utf-8')
            first = qualification.prepared(base)
            self.assertEqual(len(first[0]), 5); self.assertEqual(len(first[1]), 4)
            changed = first[1]['shipping'] / 'component.wasm'; raw = changed.read_bytes(); changed.write_bytes(b'changed')
            with self.assertRaisesRegex((RuntimeError, DevError), 'companion-bytes-mismatch'): qualification.prepared(base)
            changed.write_bytes(raw); first[0]['latent'].write_bytes(b'changed')
            with self.assertRaisesRegex((RuntimeError, DevError), 'native-mismatch'): qualification.prepared(base)
            first[0]['latent'].write_bytes(b'latent'); source.write_text('{"source":"foreign"}', encoding='utf-8')
            with self.assertRaisesRegex((RuntimeError, DevError), 'source-mismatch'): qualification.prepared(base)

    def test_omitting_random_keeps_both_clocks_then_restores_exact_original_grants(self):
        with tempfile.TemporaryDirectory() as temporary:
            client = SimpleNamespace(directory=Path(temporary))
            grants = [{'capability': name, 'policy': 'original'} for name in sorted(probe.CLOCKS | {probe.RANDOM})]
            target = {'generation': '4', 'grants': grants}; targets = {'greeting': target}
            denied = {'exitCode': 4, 'processReaped': True, 'response': {'outcomeKnown': True,
                'error': {'code': 'permission-denied'}, 'data': {'terminalState': 'rejected',
                'consumption': {'cpuFuel': '0', 'peakMemoryBytes': '0', 'effectCount': 0}}}}
            for effects in (0, 1):
                denied['response']['data']['consumption']['effectCount'] = effects
                result = {'invocations': [], 'providerIdle': []}
                with patch('tools.rust_capsule_node.deploy', side_effect=[{'generation': '5'}, {'generation': '6'}]) as deployed, \
                        patch('tools.rust_capsule_node.call', return_value=denied), patch('tools.rust_capsule_node.provider_idle', return_value={}):
                    if effects:
                        with self.assertRaisesRegex((RuntimeError, DevError), 'pre-admission-process-or-effects'):
                            probe.admission(client, Path(temporary), {'greeting': target}, {'greeting': 'publication'}, result)
                    else:
                        probe.admission(client, Path(temporary), targets, {'greeting': 'publication'}, result)
                        self.assertEqual(deployed.call_args_list[0].kwargs['grants'], [g for g in grants if g['capability'] != probe.RANDOM])
                        self.assertEqual(deployed.call_args_list[1].kwargs['grants'], grants)
                        self.assertEqual(len(result['invocations']), 2)

    def test_eight_values_and_three_failure_fresh_pairs_keep_original_bounds(self):
        def observe(*, reaped=True, leaked_network=0, budget_succeeded=False, fuel=1000):
            def invoke(_client, _target, _template, _function, args, label):
                mode = args[0].removeprefix('entropy:')
                consumed = {'cpuFuel': str(fuel if mode == 'fuel' else 20), 'peakMemoryBytes': '100',
                            'outboundRequests': str(leaked_network), 'logBytes': '0'}
                if mode in {'budget', 'trap', 'fuel'} and not (mode == 'budget' and budget_succeeded):
                    code = 'resource-exhausted' if mode == 'fuel' else 'guest-trap'
                    return {'exitCode': 4, 'processReaped': reaped, 'response': {'outcomeKnown': True,
                        'error': {'code': code}, 'data': {'terminalState': code.replace('-', '_'), 'consumption': consumed}}}
                value = 'entropy-budget-unexpected-success' if mode == 'budget' else fixture.expected(mode)
                return {'exitCode': 0, 'processReaped': reaped, 'decoded': [{'ok': value}],
                        'response': {'outcomeKnown': True, 'data': {'consumption': consumed}}}
            result = {'invocations': [], 'providerIdle': [], 'samples': []}
            with patch('tools.rust_capsule_node.call', side_effect=invoke), patch('tools.rust_capsule_node.provider_idle', return_value={}), \
                    patch('tools.rust_capsule_node.sample', return_value={}) as sampled:
                probe.probe(None, {'budget': {'cpuFuel': 1000, 'memoryBytes': 1024}}, None, result, 17)
                self.assertEqual(sampled.call_count, 14)
            return result
        result = observe()
        self.assertEqual([r['mode'] for r in result['goStandardEntropy']['cases']], list(fixture.CASES))
        self.assertEqual([r['mode'] for r in result['goStandardEntropy']['recovery']], ['budget', 'trap', 'fuel'])
        self.assertEqual(len(result['invocations']), 14)
        for kwargs, reason in (({'reaped': False}, 'not-reaped'), ({'leaked_network': 1}, 'consumption-bounds'),
                               ({'budget_succeeded': True}, 'terminal-shape'), ({'fuel': 999}, 'original-fuel-bound')):
            with self.subTest(kwargs=kwargs), self.assertRaisesRegex((RuntimeError, DevError), reason): observe(**kwargs)

    def test_selector_rejects_foreign_language_bool_alias_and_competing_campaign_before_output(self):
        from tools.run_rust_capsule_workflow import run
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / 'absent'
            for language, flag, recovery in (('dotnet', True, False), ('go', 1, False), ('go', True, True)):
                with self.assertRaisesRegex((RuntimeError, DevError), 'go-standard-entropy-language'):
                    run(Path('absent'), Path('absent'), Path('absent'), output, language=language,
                        go_standard_entropy=flag, captured_dependency_recovery=recovery)
                self.assertFalse(output.exists())


    def test_explicit_buffer_authority_is_greeting_only_and_preserves_other_bounds_and_policies(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            client = SimpleNamespace(directory=directory, call=Mock())
            original = [{'capability': name, 'policy': 'random-allow' if name == probe.RANDOM else 'clock-allow'}
                        for name in sorted(probe.CLOCKS | {probe.RANDOM})]
            target = {'generation': '6', 'service': 'examples/my-greeting', 'grants': original}
            companion = {'service': 'examples/my-shipping', 'grants': copy.deepcopy(original)}
            targets = {'greeting': target, 'shipping': companion}; result = {}
            before = (qualification.ROOT / 'tools/guest_runtime_grants.py').read_bytes()
            with patch('tools.rust_capsule_node.deploy', return_value={'generation': '7'}) as deployed:
                probe.buffer_authority(client, directory, targets, {'greeting': 'exact-publication'}, result)
            selected = json.loads((directory / 'go-entropy-buffer-policy.json').read_bytes())['rules'][0]
            self.assertEqual(selected['ceiling'], {'operations': 4096, 'inputBytes': 32768,
                'outputBytes': 32768, 'wallTimeMillis': 5000})
            self.assertEqual(selected['services'], ['examples/my-greeting'])
            self.assertEqual(selected['publications'], ['exact-publication'])
            self.assertEqual(selected['operations'], ['u64-value'])
            self.assertEqual(selected['resources'], {'kind': 'random'})
            grants = deployed.call_args.kwargs['grants']
            self.assertEqual([row for row in grants if row['capability'] != probe.RANDOM],
                             [row for row in original if row['capability'] != probe.RANDOM])
            self.assertEqual([row for row in grants if row['capability'] == probe.RANDOM],
                             [{'capability': probe.RANDOM, 'policy': 'go-entropy-buffer-allow'}])
            self.assertEqual(targets['shipping'], companion)
            self.assertEqual(target['grants'], original)
            self.assertEqual((qualification.ROOT / 'tools/guest_runtime_grants.py').read_bytes(), before)
            self.assertIn(b'"inputBytes": 8 if kind == "random" else 0', before)
            self.assertFalse(result['goStandardEntropyBufferAuthority']['genericRuntimePolicyChanged'])
            self.assertEqual(client.call.call_args.args[-2:], ('--expected-generation', '0'))

    def test_unmodified_standard_apis_have_no_reader_injection_or_recorded_entropy_payload(self):
        for spelling in ('rand.Read(', 'io.ReadFull(rand.Reader,', 'rand.Text()', 'syscall.RandomGet('):
            self.assertIn(spelling, fixture.LIBRARY)
        for spelling in ('rand.Reader =', 'go:linkname', 'go:wasmimport', 'unsafe', 'LSF'):
            self.assertNotIn(spelling, fixture.LIBRARY)
        self.assertIn('return "entropy-budget-unexpected-success"', fixture.LIBRARY)
        self.assertEqual(len(fixture.CASES), 8)


if __name__ == '__main__': unittest.main()
