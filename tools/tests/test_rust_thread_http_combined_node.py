"""Controls for the signed combined witness's explicit capability custody."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from tools import rust_thread_http_combined_node as node
from tools.phase2_operator_process import WorkflowError


def descriptors():
    return [{'id': identity, 'capability': capability, 'tenant': 'examples',
             'profile': profile, 'configurationEpoch': '1', 'configurationDigest': 'sha256:' + '1' * 64}
            for identity, capability, _ops, profile, _kind in node.PROVIDERS]


class CombinedGrantControls(unittest.TestCase):
    def test_diagnostic_host_optimization_preserves_guest_features_and_verifier(self):
        from unittest.mock import Mock
        from tools import qualify_rust_thread_http_combined as qualification

        commands = Mock()
        qualification.build_native(commands)
        commands.run.assert_called_once()
        argv = commands.run.call_args.args
        self.assertEqual(argv[:2], ('build-current-feature-selected-host', 'cargo'))
        configurations = [argv[index + 1] for index, word in enumerate(argv) if word == '--config']
        self.assertEqual(configurations, [qualification.ROOT / '.cargo/managed-guest.toml',
                         'profile.dev.opt-level=1',
                         'profile.dev.package.latent-component-threading.opt-level=3'])
        self.assertIn('--locked', argv)
        self.assertNotIn('--release', argv)
        self.assertEqual(argv[argv.index('--features') + 1],
                         'latentd/development-rust-http-combined,latent-packaging/development-rust-http-combined')

    def test_peer_refusal_keeps_the_original_error_and_the_existing_call_result(self):
        import json
        from pathlib import Path
        import tempfile
        import time
        from unittest.mock import Mock
        from tools import rust_thread_http_sibling_node as sibling

        digest = 'sha256:' + '2' * 64
        target = {'budget': {'outboundRequests': 8, 'memoryBytes': 16_777_216,
                             'cpuFuel': 1_000_000_000, 'wallTimeLimitMillis': 5000}}
        observed = {'generation': 'a' * 32, 'failure': None, 'acceptedConnections': 1,
                    'requests': [{'request': 1, 'role': 'primary', 'state': 'closed',
                                  'responseBytesWritten': 0, 'closeReason': 'remote-write-half-ended'}],
                    'events': []}
        peer = SimpleNamespace(gates=lambda: [], poll=Mock(), release=Mock(),
                               observation=Mock(side_effect=[{'acceptedConnections': 0}, observed]),
                               origin=lambda: {'scheme': 'http', 'host': '127.0.0.1', 'port': 1234})
        terminal = {'exitCode': 4, 'decoded': None, 'processReaped': True,
                    'response': {'category': 'platform-failure'}}
        for result_error in (None, WorkflowError('terminal-observation-failed')):
            with self.subTest(terminal_failure=result_error), tempfile.TemporaryDirectory() as directory:
                process = SimpleNamespace(owner=SimpleNamespace(exited=Mock(side_effect=[False, False, True])),
                                          drain=Mock(), close=Mock())
                peer.observation = Mock(side_effect=[{'acceptedConnections': 0}, observed])
                with patch.object(sibling, 'selected_revision', return_value={'releaseDigest': digest}), \
                        patch.object(sibling, 'start_call', return_value=process) as start, \
                        patch.object(sibling, 'finish_call', return_value=terminal, side_effect=result_error) as finish:
                    with self.assertRaisesRegex(WorkflowError, '^rust-thread-http-peer-request-shape$'):
                        sibling.invoke(SimpleNamespace(deadline=time.monotonic() + 10),
                                       SimpleNamespace(drain=Mock()), target, peer, object(), Path(directory), digest)
                start.assert_called_once()
                finish.assert_called_once()
                process.close.assert_called_once()
                peer.release.assert_not_called()
                self.assertTrue((Path(directory) / 'rust-thread-http-peer-refusal.json').is_file())
                if result_error is None:
                    self.assertEqual(json.loads((Path(directory) / 'rust-thread-http-terminal.json').read_bytes()), terminal)

    def test_refusal_observation_does_not_extend_the_original_deadline(self):
        from pathlib import Path
        from unittest.mock import Mock
        from tools import rust_thread_http_sibling_node as sibling
        process = SimpleNamespace(owner=SimpleNamespace(exited=lambda: False), drain=Mock())
        node, peer = SimpleNamespace(drain=Mock()), SimpleNamespace(poll=Mock(), release=Mock())
        with patch.object(sibling.time, 'monotonic', return_value=100), \
                patch.object(sibling, 'finish_call') as finish:
            sibling.retain_refused_call(SimpleNamespace(deadline=110), node, peer, process, Path('unused'), 99)
        finish.assert_not_called()
        process.drain.assert_not_called()
        peer.poll.assert_not_called()
        peer.release.assert_not_called()

    def test_transport_wait_is_separate_from_the_original_guest_budget(self):
        import json
        from pathlib import Path
        import tempfile
        import time
        from tools import rust_capsule_node as calls

        budget = {'outboundRequests': 8, 'memoryBytes': 16_777_216,
                  'cpuFuel': 1_000_000_000, 'wallTimeLimitMillis': 5000}
        target = {'name': 'combined', 'service': 'my-greeting', 'budget': budget}
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            client = node.witness_client('latent', root, object(), time.monotonic() + 300,
                                         root / 'evidence')
            ordinary = calls.RecordingClient('latent', root, object(), client.deadline,
                                             evidence=root / 'ordinary-evidence')
            self.assertEqual(ordinary.invocation_timeout_millis, 5000)
            self.assertEqual(client.invocation_timeout_millis, 120_000)
            self.assertEqual(client.control_timeout_millis, ordinary.control_timeout_millis)
            process = SimpleNamespace()
            with patch.object(calls, 'Process', return_value=process) as launch:
                self.assertIs(calls.start_call(client, target, 'greeting', 'greet',
                                               ['thread-http|http://127.0.0.1:1234'], 'bounded'), process)
            argv = launch.call_args.args[0]
            self.assertEqual(argv[argv.index('--rpc-timeout-ms') + 1], '120000')
            self.assertEqual(json.loads((root / 'bounded-budget.json').read_bytes()), budget)
            self.assertEqual(target['budget']['wallTimeLimitMillis'], 5000)
            launch.assert_called_once()

    def test_shared_provider_identity_still_requires_four_distinct_capabilities(self):
        observed = []
        peer = SimpleNamespace(origin=lambda role: {'scheme': 'http', 'host': '127.0.0.1', 'port': 1234})
        owner = SimpleNamespace(startup_record={'providers': descriptors()})
        with patch.object(node, 'policy', side_effect=lambda *args: observed.append(args)):
            grants = node.grant(object(), owner, 'signed-publication', peer)
        self.assertEqual({row['capability'] for row in grants}, set(node.IMPORTS))
        self.assertEqual(len(observed), 8)
        native = [args for args in observed if args[2] == 'native-examples-allow']
        self.assertEqual(len(native), 1)
        self.assertEqual(native[0][3]['rules'][0]['operations'], ['start'])
        self.assertEqual(native[0][3]['rules'][0]['resources'], {'kind': 'context'})

    def test_missing_native_descriptor_refuses_before_any_policy_write(self):
        owner = SimpleNamespace(startup_record={'providers': descriptors()[:-2] + descriptors()[-1:]})
        peer = SimpleNamespace(origin=lambda role: None)
        with patch.object(node, 'policy') as mutation:
            with self.assertRaises(WorkflowError):
                node.grant(object(), owner, 'signed-publication', peer)
        mutation.assert_not_called()


    def test_failed_sibling_order_retains_the_actual_terminal_result(self):
        import json
        from pathlib import Path
        import tempfile
        import time
        from tools import rust_thread_http_sibling_node as sibling
        digest = 'sha256:' + '2' * 64
        target = {'budget': {'outboundRequests': 8, 'memoryBytes': 16_777_216,
                             'cpuFuel': 1_000_000_000, 'wallTimeLimitMillis': 5000}}
        peer = SimpleNamespace(gates=lambda: [], observation=lambda: {'acceptedConnections': 0},
                               origin=lambda: {'scheme': 'http', 'host': '127.0.0.1', 'port': 1234})
        process = SimpleNamespace(owner=SimpleNamespace(exited=lambda: True), close=lambda: None)
        terminal = {'exitCode': 4, 'decoded': None, 'processReaped': True,
                    'response': {'category': 'platform-failure'}}
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(sibling, 'selected_revision', return_value={'releaseDigest': digest}), \
                patch.object(sibling, 'start_call', return_value=process), \
                patch.object(sibling, 'finish_call', return_value=terminal):
            with self.assertRaises(WorkflowError):
                sibling.invoke(SimpleNamespace(deadline=time.monotonic() + 10), object(), target,
                               peer, object(), Path(directory), digest)
            retained = json.loads((Path(directory) / 'rust-thread-http-terminal.json').read_bytes())
            self.assertEqual(retained, terminal)


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


class CorrectedCompilerControls(unittest.TestCase):
    def retained(self):
        from tools import rust_thread_http_combined_package as package
        return json.loads((package.CATALOGUE / 'compiler-control.json').read_bytes())

    def validate(self, record):
        from tools import rust_thread_http_combined_package as package
        package.validate_producer(record['observation'], record['composition'], record['recipe'],
            record['recipeInputs'], record['sourceInventoryUtf8'].encode(), record['runtimeUtf8'].encode())

    def test_corrected_event_retains_real_source_lineage_without_reclassifying_old_failure(self):
        from tools import rust_thread_http_combined_package as package
        from tools import rust_combined_diagnostic_envelope as envelope, rust_original_delta as delta
        record = self.retained()
        self.validate(record)
        self.assertEqual(record['recipe']['head'], package.SOURCE)
        self.assertEqual(package.ORIGIN['producerJobConclusion'], 'success')
        self.assertEqual(package.ORIGIN['workflowConclusion'], 'success')
        self.assertEqual(package.ORIGIN['historicalCompiler']['outcome'], 'failure')
        self.assertFalse(package.ORIGIN['historicalCompiler']['reclassified'])
        original = (package.CATALOGUE / 'combined-original-core.wasm').read_bytes()
        component = (package.CATALOGUE / 'combined-final-component.wasm').read_bytes()
        material = delta.encode(original, component)
        self.assertEqual(material, (package.CATALOGUE / 'combined-original-delta.bin').read_bytes())
        wrapped = envelope.frame(component, material)
        self.assertEqual({'bytes': len(wrapped), 'sha256': package.digest(wrapped)}, package.WRAPPED)
        self.assertNotEqual(component, (package.CATALOGUE.parent / 'combined-final-component.wasm').read_bytes())

    def test_incomplete_relabelled_crossed_or_mutated_compiler_evidence_refuses(self):
        original = self.retained()
        changes = [
            ('observation', 'status', 'passed'), ('observation', 'stage', 'compile'),
            ('observation', 'actualApplicationCoreCompiled', False),
            ('observation', 'normalBuildComplete', True),
            ('observation', 'normalComponentGateRefused', False),
            ('observation', 'actualGuestExecuted', True),
            ('observation', 'httpCompositionIncluded', False),
            ('composition', 'librarySourceRewritten', True),
            ('composition', 'publicGraphUnchanged', False),
            ('composition', 'signedExecutionQualification', True),
            ('recipe', 'head', '0' * 40), ('recipe', 'tree', '0' * 40),
        ]
        for section, key, value in changes:
            with self.subTest(section=section, key=key):
                changed = deepcopy(original)
                changed[section][key] = value
                with self.assertRaises(WorkflowError):
                    self.validate(changed)
        for field in ('sourceInventoryUtf8', 'runtimeUtf8'):
            changed = deepcopy(original)
            changed[field] += ' '
            with self.subTest(field=field), self.assertRaises(WorkflowError):
                self.validate(changed)
        changed = deepcopy(original)
        changed['observation']['commands'][5]['exitCode'] = 1
        with self.assertRaises(WorkflowError):
            self.validate(changed)
        changed = deepcopy(original)
        changed['recipe']['files'].append(changed['recipe']['files'][0])
        with self.assertRaises(WorkflowError):
            self.validate(changed)

    def test_signed_node_requires_current_event_and_separate_compiler_job_result(self):
        from tools import rust_thread_http_combined_package as package
        record = {'componentDigest': package.WRAPPED['sha256'],
            'selectedHostProfile': package.PROFILE, 'compilerSource': package.SOURCE,
            'compilerRun': package.RUN, 'compilerJob': package.JOB, 'compilerArtifact': package.ARTIFACT,
            'compilerRunConclusion': package.ORIGIN['workflowConclusion'],
            'compilerJobConclusion': package.ORIGIN['producerJobConclusion'],
            'compilerWorkflowSource': package.ORIGIN['workflowSource'],
            'compilerObservationStatus': package.ORIGIN['compilerObservationStatus'],
            'applicationRecompiled': True, 'applicationRecompiledDuringAssembly': False,
            'originalCompilerObservationRewritten': False, 'normalRustBuilderRouteOpened': False}
        node.require_current_projection(record, package.WRAPPED)
        for key, value in (('compilerSource', '0' * 40), ('compilerWorkflowSource', package.SOURCE),
                           ('compilerJob', 0), ('compilerArtifact', 0), ('compilerRunConclusion', 'failure'),
                           ('compilerJobConclusion', 'failure'), ('applicationRecompiled', False),
                           ('applicationRecompiledDuringAssembly', True),
                           ('originalCompilerObservationRewritten', True),
                           ('normalRustBuilderRouteOpened', True)):
            changed = {**record, key: value}
            with self.subTest(key=key), self.assertRaises(WorkflowError):
                node.require_current_projection(changed, package.WRAPPED)

    def test_framing_rejects_crossed_original_and_final_images(self):
        from tools import rust_thread_http_combined_package as package
        original = (package.CATALOGUE / 'combined-original-core.wasm').read_bytes()
        final = (package.CATALOGUE / 'combined-final-component.wasm').read_bytes()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'raw-core.wasm').write_bytes(original)
            (root / 'combined-component.wasm').write_bytes(final)
            self.assertEqual(len(package.framed(root, package.CATALOGUE)), package.WRAPPED['bytes'])
            for filename, content in (('raw-core.wasm', original), ('combined-component.wasm', final)):
                altered = bytearray(content)
                altered[-1] ^= 1
                (root / filename).write_bytes(altered)
                with self.subTest(filename=filename), self.assertRaises(WorkflowError):
                    package.framed(root, package.CATALOGUE)
                (root / filename).write_bytes(content)


if __name__ == '__main__':
    unittest.main()
