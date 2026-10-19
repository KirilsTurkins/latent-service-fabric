"""Historical products remain historical; current host and entropy are fresh."""
import copy
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from tools import qualify_go_entropy_retained as qualification, go_entropy_replay_inputs as acquisition
from tools.phase3_resource_identity import file_identity
from tools.rust_capsule_project import ROOT, TEMPLATES, digest, inventory


class RetainedEntropy(unittest.TestCase):
    def fixture(self, base):
        def write(path, value):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes((json.dumps(value)+'\n').encode())
        write(base/'acquisition.json', {'artifactId': acquisition.ARTIFACT, 'testedSource': acquisition.TESTED,
            'normalGreetingIncluded': True, 'completeArchiveDownloaded': False, 'credentialsRetained': False})
        normal = base/'go-capsule-dependencies';normal.mkdir()
        write(normal/'source-inputs.json', {'historical': True})
        node = {'status': 'passed', 'invocations': [{'processReaped': True} for _ in range(27)],
                'nodeShutdown': {'reaped': True, 'record': {'clean': True}}}
        write(normal/'node/workflow.json', node)
        binaries = {}
        for name in qualification.PRODUCTS:
            path = normal/'native-binaries'/name.replace('/', '-')
            path.parent.mkdir(exist_ok=True);path.write_bytes(name.encode())
            binaries[name] = file_identity(path)
        markers = {}
        for name in TEMPLATES:
            location = normal/'builds'/name;location.mkdir(parents=True)
            (location/'component.wasm').write_bytes(name.encode())
            (location/'source-inputs.json').write_bytes(b'{}')
            (location/'build-observation.json').write_bytes(b'{}')
            (location/'package-source.json').write_bytes(b'{"layers":[{"source":"component.wasm"}]}')
            (location/'package-inputs.json').write_bytes(inventory({part: (location/part).read_bytes()
                for part in ('package-source.json', 'component.wasm')}))
            markers[name] = {'componentDigest': digest(name.encode()), 'sourceDigest': digest(b'{}'),
                             'observationDigest': digest(b'{}')}
            write(location/'BUILD-COMPLETE.json', markers[name])
        write(normal/'qualification.json', {'schemaVersion': 'latent.go-capsule.qualification.v1', 'status': 'passed',
            'sourceIdentityDigest': digest((normal/'source-inputs.json').read_bytes()), 'binaries': binaries,
            'node': {'receiptDigest': digest((normal/'node/workflow.json').read_bytes())}, 'builds': markers})
        return normal

    def test_historical_normal_proof_checks_all_five_packages_and_never_becomes_current(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary);normal = self.fixture(base)
            before = (normal/'qualification.json').read_bytes()
            binaries, builds, proof = qualification.historical(base)
            self.assertEqual(set(builds), set(TEMPLATES))
            self.assertEqual(set(binaries), set(qualification.PRODUCTS))
            self.assertEqual(proof['compiledSource'], acquisition.TESTED)
            self.assertFalse(proof['currentNormalReceiptFabricated'])
            self.assertEqual((normal/'qualification.json').read_bytes(), before)

    def test_unselected_native_probe_metadata_does_not_expand_the_exact_selected_five(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary);normal = self.fixture(base)
            path = normal/'qualification.json';receipt = json.loads(path.read_bytes())
            receipt['binaries']['examples/go_runtime_probe'] = {'sha256': 'sha256:'+'7'*64, 'bytes': 17}
            path.write_bytes(json.dumps(receipt).encode())
            binaries, _builds, proof = qualification.historical(base)
            self.assertEqual(set(binaries), set(qualification.PRODUCTS))
            self.assertEqual(set(proof['nativeBinaries']), set(qualification.PRODUCTS))
            self.assertFalse((normal/'native-binaries/examples-go_runtime_probe').exists())

    def test_changed_original_component_package_input_and_native_binary_are_refused(self):
        for changed in ('builds/greeting/component.wasm', 'builds/word-count/package-inputs.json', 'native-binaries/latent'):
            with self.subTest(changed=changed), tempfile.TemporaryDirectory() as temporary:
                base = Path(temporary);normal = self.fixture(base)
                (normal/changed).write_bytes(b'changed')
                with self.assertRaisesRegex(RuntimeError, 'go-entropy-retained-'):
                    qualification.historical(base)

    def test_wrong_acquisition_identity_or_missing_normal_greeting_refuses_before_inputs(self):
        original = {'artifactId': acquisition.ARTIFACT, 'testedSource': acquisition.TESTED,
            'normalGreetingIncluded': True, 'completeArchiveDownloaded': False, 'credentialsRetained': False}
        for field, value in (('artifactId', 1), ('testedSource', 'f'*40), ('normalGreetingIncluded', False),
                             ('credentialsRetained', True)):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as temporary:
                base = Path(temporary);current = {**original, field: value}
                (base/'acquisition.json').write_bytes(json.dumps(current).encode())
                with self.assertRaisesRegex(RuntimeError, 'retained-acquisition'):
                    qualification.historical(base)

    def test_new_host_requires_actual_success_single_default_product_and_stable_source(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary);binary = base/'compiled-latentd';binary.write_bytes(b'actual new host')
            rows = [{'reason': 'compiler-artifact', 'target': {'name': 'latentd', 'kind': ['bin']},
                     'executable': str(binary), 'features': [],
                     'profile': {'opt_level': '0', 'debuginfo': 0, 'debug_assertions': True,
                                 'overflow_checks': True, 'test': False}},
                    {'reason': 'build-finished', 'success': True}]
            calls = []
            def command(*arguments):
                calls.append(arguments)
                return b'\n'.join(json.dumps(row).encode() for row in rows)
            commands = SimpleNamespace(run=command)
            with patch.object(qualification, 'source_identity', return_value={'actual source': True}), \
                    patch.object(qualification.subprocess, 'check_output', return_value=b'a'*40+b'\n'):
                output = base/'passed';output.mkdir()
                actual, proof = qualification.current_host(output, commands)
                self.assertEqual(actual.read_bytes(), binary.read_bytes())
                self.assertEqual(proof['compiledSource'], 'a'*40)
                self.assertTrue(proof['ordinaryDefaults'])
                self.assertEqual(proof['profile'], rows[0]['profile'])
                self.assertEqual(calls[0][1:], ('cargo', 'build', '--locked', '-p', 'latentd', '--bin', 'latentd', '--message-format=json'))
                for mode in ('features', 'incomplete', 'source-drift', 'debug-info'):
                    original = copy.deepcopy(rows)
                    destination = base/mode;destination.mkdir()
                    if mode == 'features': rows[0]['features'] = ['development-test-node']
                    elif mode == 'incomplete': rows[1]['success'] = False
                    elif mode == 'debug-info': rows[0]['profile']['debuginfo'] = 2
                    with patch.object(qualification, 'source_identity', side_effect=[{'before': True}, {'after': True}]
                                      if mode == 'source-drift' else None,
                                      return_value={'same': True}), self.assertRaisesRegex(RuntimeError, 'go-entropy-retained-'):
                        qualification.current_host(destination, commands)
                    rows[:] = original

    def test_sanitized_native_build_restores_debug_zero_and_original_correctness_settings(self):
        # The workflow environment is deliberately stripped by build_environment.
        # Capture the real Commands constructor before any native work begins.
        from tools import build_observation
        ambient = {'CARGO_PROFILE_DEV_DEBUG': '2', 'CARGO_INCREMENTAL': '1',
                   'RUSTFLAGS': '--unreviewed-native-flags'}
        with tempfile.TemporaryDirectory() as temporary, \
                patch.dict(build_observation.os.environ, ambient), \
                patch.object(qualification.sys, 'platform', 'linux'), \
                patch.object(qualification.sys, 'version_info', (3, 13)), \
                patch.object(qualification, 'Commands', side_effect=RuntimeError('constructor captured')) as command:
            base = Path(temporary)
            with self.assertRaisesRegex(RuntimeError, 'constructor captured'):
                qualification.qualify(base/'unused-inputs', base/'owned-output')
            environment = command.call_args.args[2]
            for key, expected in {'CARGO_INCREMENTAL': '0', 'CARGO_PROFILE_DEV_DEBUG': '0',
                    'CARGO_PROFILE_TEST_DEBUG': '0', 'CARGO_PROFILE_DEV_DEBUG_ASSERTIONS': 'true',
                    'CARGO_PROFILE_TEST_DEBUG_ASSERTIONS': 'true', 'CARGO_PROFILE_DEV_OVERFLOW_CHECKS': 'true',
                    'CARGO_PROFILE_TEST_OVERFLOW_CHECKS': 'true'}.items():
                self.assertEqual(environment.get(key), expected, key)
            self.assertNotIn('RUSTFLAGS', environment)
            self.assertEqual(command.call_args.kwargs, {'deadline_seconds': 1950, 'command_seconds': 1800})

    def test_manual_cpu_scalar_and_entropy_jobs_are_independent_and_original_deadline_is_unchanged(self):
        from tools import ci_lane_inventory
        jobs = ci_lane_inventory.workflow_model((ROOT/'.github/workflows/go-guest.yml').read_text())['jobs']
        self.assertEqual(jobs['upstream-probe']['timeout-minutes'], 45)
        for name in ('retained-cpu-checkpoints', 'retained-scalar-ownership', 'retained-entropy'):
            self.assertNotIn('needs', jobs[name])
            self.assertIn('inputs.qualify-entropy-retained', jobs[name]['if'])
        self.assertEqual(jobs['retained-entropy']['timeout-minutes'], 35)
        cpu = '\n'.join(step.get('run', '') for step in jobs['retained-cpu-checkpoints']['steps'])
        self.assertIn('signed_compiler_checkpoints_progress_cpu_siblings_and_cancel_original_activation', cpu)
        self.assertNotIn('qualify_go_activation.py', cpu)

    def test_extra_public_greeting_does_not_widen_default_artifact_scope_or_request_limit(self):
        self.assertFalse(acquisition.selected('go-capsule-dependencies/builds/greeting/component.wasm'))
        self.assertEqual(acquisition.Remote('https://example.invalid', 1).maximum_requests, 512)
        for value in (True, 0, 641):
            with self.assertRaisesRegex(RuntimeError, 'request-bound'):
                acquisition.Remote('https://example.invalid', 1, maximum_requests=value)
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)/'not-created'
            with self.assertRaisesRegex(RuntimeError, 'greeting-selector'):
                acquisition.acquire(output, include_normal_greeting='true')
            self.assertFalse(output.exists())


if __name__ == '__main__':
    unittest.main()
