"""Source/data controls for the unqualified combined Rust HTTP witness."""
from pathlib import Path
import copy
import json
import tempfile
import unittest

from tools.phase2_operator_process import WorkflowError
from tools.standard_http.peer import Gate
from tools import rust_owned_thread_component, rust_thread_http_sibling_fixture as fixture
from tools import rust_thread_http_sibling_gate as witness


class RustThreadHttpSiblingTests(unittest.TestCase):
    def test_composer_receipt_is_preserved_and_diagnostic_is_separate(self):
        from tools.compile_rust_thread_http_sibling import (
            THREAD_PREVIEW_FEATURES, record_diagnostic_composition,
        )
        from tools.rust_capsule_project import read_json, write_json
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            original = {'status': 'composed', 'originalCoreModulesRetained': 3}
            write_json(output / 'rust-http-composition.json', original)
            before = (output / 'rust-http-composition.json').read_bytes()
            result = record_diagnostic_composition(output, original, {'digest': 'fixed'})
            self.assertEqual((output / 'rust-http-composition.json').read_bytes(), before)
            self.assertEqual(read_json(output / 'rust-http-composition-diagnostic.json'), result)
            self.assertTrue(result['diagnosticOnly'])
            self.assertEqual(result['diagnosticValidationFeatures'], THREAD_PREVIEW_FEATURES)
            with self.assertRaises((ValueError, RuntimeError)):
                record_diagnostic_composition(output, {'status': 'different'}, {'digest': 'fixed'})
            self.assertEqual((output / 'rust-http-composition.json').read_bytes(), before)

    def test_only_diagnostic_final_validation_selects_threading(self):
        from unittest.mock import Mock
        from tools.compile_rust_thread_http_sibling import (
            DiagnosticThreadingValidation, HTTP_ASYNC_FEATURES, THREAD_PREVIEW_FEATURES,
        )
        commands = Mock()
        wrapped = DiagnosticThreadingValidation(commands)
        wrapped.run('unrelated', 'value')
        commands.run.assert_called_with('unrelated', 'value')
        wrapped.run('rust-http-final-validation', 'wasm-tools', 'validate', 'selected.wasm',
                    '--features', HTTP_ASYNC_FEATURES)
        commands.run.assert_called_with('rust-http-final-validation', 'wasm-tools', 'validate',
                                        'selected.wasm', '--features', THREAD_PREVIEW_FEATURES)
        self.assertTrue(wrapped.validated)
        with self.assertRaises((ValueError, RuntimeError)):
            wrapped.run('rust-http-final-validation', 'wasm-tools', 'validate', 'selected.wasm',
                        '--features', HTTP_ASYNC_FEATURES)
        with self.assertRaises((ValueError, RuntimeError)):
            DiagnosticThreadingValidation(commands).run('rust-http-final-validation', 'wasm-tools',
                                                        'validate', 'selected.wasm', '--features', 'all')

    def observation(self):
        events = [
            ('connection-accepted', 1, {}),
            ('request-started', 1, {'vector': 'pending-headers'}),
            ('request-complete', 1, {'bodyBytes': 0}),
            ('gate-pending', 1, {'phase': 'headers'}),
            ('connection-accepted', 2, {}),
            ('request-started', 2, {'vector': 'partial-body'}),
            ('request-complete', 2, {'bodyBytes': 0}),
            ('gate-pending', 2, {'phase': 'body'}),
        ]
        rows = [
            {'request': 1, 'role': 'primary', 'vector': 'pending-headers', 'responseBytesWritten': 0},
            {'request': 2, 'role': 'primary', 'vector': 'partial-body', 'responseBytesWritten': 99},
        ]
        return {'generation': 'a' * 32, 'failure': None, 'requests': rows,
                'events': [{'sequence': index, 'kind': kind, 'request': request, **extra}
                           for index, (kind, request, extra) in enumerate(events, 1)]}

    def test_real_fixture_source_keeps_ordinary_clients_and_original_limits(self):
        with tempfile.TemporaryDirectory() as directory:
            app, outside, specs = fixture.prepare(Path(directory) / 'fresh', '0123456789abcdef')
            project = fixture.read_json(app / 'capsule-project.json')
            self.assertEqual(project['runtimeProfile'], fixture.standard.THREAD)
            self.assertEqual((project['limits']['outboundRequests'], project['limits']['memoryBytes'],
                              project['limits']['cpuFuel'], project['limits']['wallTimeLimitMillis']),
                             (8, 16_777_216, 1_000_000_000, 5000))
            source = (app / 'src/lib.rs').read_text()
            world = (app / 'wit/world.wit').read_text()
            self.assertEqual(source.count('futures_executor::ThreadPool::new()'), 2)
            self.assertIn('thread_http_sibling(&endpoint)', source)
            self.assertNotIn('yield_now(', source)
            self.assertEqual(world.count('latent:runtime-native/threads@0.1.0'), 1)
            self.assertEqual(world.count('latent:http/streaming@0.3.0'), 1)
            self.assertEqual((outside[0] / 'src/lib.rs').read_bytes(), fixture.http.LIBRARY.encode())
            self.assertEqual((outside[1] / 'src/lib.rs').read_bytes(),
                             fixture.http.LIBRARY.encode() + fixture.SIBLING.encode())
            self.assertEqual(len(specs), 2)
            self.assertEqual(source.count('applicationTransportInjected'), 0)

    def test_peer_refusal_retains_bounded_observation_without_masking_refusal(self):
        from tools import rust_thread_http_sibling_node as node
        observation = {'generation': 'a' * 32, 'failure': None,
                       'requests': [{'request': 1, 'role': 'secondary', 'state': 'accepted'}],
                       'events': []}
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            with self.assertRaisesRegex(WorkflowError, 'rust-thread-http-peer-request-shape'):
                node.decision_with_failure_evidence(observation, [], output, body_released=False)
            path = output / 'rust-thread-http-peer-refusal.json'
            self.assertEqual(json.loads(path.read_bytes()),
                             {'observation': observation, 'bodyReleased': False})
            before = path.read_bytes()
            with self.assertRaisesRegex(WorkflowError, 'rust-thread-http-peer-request-shape'):
                node.decision_with_failure_evidence(observation, [], output, body_released=False)
            self.assertEqual(path.read_bytes(), before)

    def test_only_release_body_when_both_real_http_gates_are_held(self):
        accepted = {'generation': 'a' * 32, 'failure': None,
                    'requests': [{'request': 1, 'role': 'primary', 'state': 'accepted'}],
                    'events': []}
        self.assertIsNone(witness.decision(accepted, [], body_released=False))
        value = self.observation()
        original, sibling = Gate('a' * 32, 1, 'headers'), Gate('a' * 32, 2, 'body')
        self.assertIsNone(witness.decision(value, [original], body_released=False))
        self.assertEqual(witness.decision(value, [original, sibling], body_released=False),
                         {'action': 'release-sibling-body', 'gate': sibling})
        value['requests'].append({'request': 3, 'role': 'primary', 'state': 'accepted'})
        self.assertEqual(witness.decision(value, [original, sibling], body_released=False),
                         {'action': 'release-sibling-body', 'gate': sibling})
        for changed in ('generation', 'bytes', 'phase'):
            peer = copy.deepcopy(value)
            gates = [original, sibling]
            if changed == 'generation': gates[1] = Gate('b' * 32, 2, 'body')
            if changed == 'bytes': peer['requests'][0]['responseBytesWritten'] = 1
            if changed == 'phase': gates[1] = Gate('a' * 32, 2, 'headers')
            with self.subTest(changed=changed), self.assertRaises((ValueError, RuntimeError)):
                witness.decision(peer, gates, body_released=False)

    def test_original_is_released_only_after_sibling_parses_and_reissues(self):
        value = self.observation()
        original = Gate('a' * 32, 1, 'headers')
        events = value['events']
        def add(kind, request, **extra):
            events.append({'sequence': len(events) + 1, 'kind': kind, 'request': request, **extra})
        add('gate-released', 2, phase='body')
        self.assertIsNone(witness.decision(value, [original], body_released=True))
        value['requests'].append({'request': 3, 'role': 'primary', 'vector': 'domain-json'})
        add('request-started', 3, vector='domain-json')
        add('response-write-complete', 3)
        self.assertIsNone(witness.decision(value, [original], body_released=True))
        value['requests'].append({'request': 4, 'role': 'primary', 'vector': 'domain-json'})
        add('request-started', 4, vector='domain-json')
        result = witness.decision(value, [original], body_released=True)
        self.assertEqual(result['action'], 'release-original-headers')
        self.assertEqual(result['gate'], original)
        self.assertLess(result['pendingSequence'], result['secondRequestSequence'])
        self.assertLess(result['firstResponseSequence'], result['secondRequestSequence'])
        changed = copy.deepcopy(value)
        changed['events'][3]['kind'] = 'not-held'
        with self.assertRaises((ValueError, RuntimeError)):
            witness.decision(changed, [original], body_released=True)
        changed = copy.deepcopy(value)
        changed['events'][-1]['sequence'] -= 1
        with self.assertRaises((ValueError, RuntimeError)):
            witness.decision(changed, [original], body_released=True)

    def test_normal_builder_stays_closed_without_an_authenticated_thread_route(self):
        with self.assertRaisesRegex(ValueError, 'rust-thread-private-executor-and-canonical-graph-unqualified'):
            rust_owned_thread_component.select(None, Path('unused-rustc'))

    def test_supervisor_never_releases_original_before_the_observed_sibling(self):
        import time
        from types import SimpleNamespace
        from unittest.mock import Mock, patch
        from tools import rust_thread_http_sibling_node as node

        state = {'started': False, 'phase': 0, 'releases': []}
        held, partial = Gate('a' * 32, 1, 'headers'), Gate('a' * 32, 2, 'body')
        def observe():
            if not state['started']:
                return {'acceptedConnections': 0, 'generation': 'a' * 32, 'failure': None,
                        'requests': [], 'events': [], 'openConnections': 0}
            value = self.observation()
            value.update(acceptedConnections=4 if state['phase'] else 2,
                         openConnections=0 if state['phase'] == 2 else 2)
            def add(kind, request, **extra):
                value['events'].append({'sequence': len(value['events']) + 1,
                                        'kind': kind, 'request': request, **extra})
            if state['phase']:
                add('gate-released', 2, phase='body')
                value['requests'].append({'request': 3, 'role': 'primary', 'vector': 'domain-json'})
                add('request-started', 3, vector='domain-json')
                add('response-write-complete', 3)
                value['requests'].append({'request': 4, 'role': 'primary', 'vector': 'domain-json'})
                add('request-started', 4, vector='domain-json')
            if state['phase'] == 2:
                add('gate-released', 1, phase='headers')
            return value
        def gates():
            if not state['started'] or state['phase'] == 2: return []
            return [held, partial] if state['phase'] == 0 else [held]
        def release(gate):
            self.assertEqual(gate, partial if state['phase'] == 0 else held)
            state['releases'].append(gate)
            state['phase'] += 1
        peer = SimpleNamespace(observation=observe, gates=gates, release=release, poll=Mock(),
                               origin=lambda: {'scheme': 'http', 'host': '127.0.0.1', 'port': 1234})
        process = SimpleNamespace(owner=SimpleNamespace(exited=lambda: state['phase'] == 2),
                                  drain=Mock(), close=Mock())
        client = SimpleNamespace(deadline=time.monotonic() + 30)
        selected = {'releaseDigest': 'sha256:' + '1' * 64}
        budget = {'outboundRequests': 8, 'memoryBytes': 16_777_216,
                  'cpuFuel': 1_000_000_000, 'wallTimeLimitMillis': 5000}
        row = {'processReaped': True, 'exitCode': 0, 'decoded': [{'ok': node.EXPECTED}],
               'response': {'outcomeKnown': True, 'requestDispatched': True,
                            'data': {'resolvedRevision': selected, 'consumption': {
                                'outboundRequests': 4, 'cpuFuel': 1, 'peakMemoryBytes': 1}}}}
        def start(*args, **kwargs):
            state['started'] = True
            return process
        usage = {'nodeUsage': {'counters': {name: 0 for name in node.ACTIVE_COUNTERS}}}
        with tempfile.TemporaryDirectory() as temporary, \
                patch.object(node, 'selected_revision', return_value=selected), \
                patch.object(node, 'start_call', side_effect=start), \
                patch.object(node, 'finish_call', return_value=row), \
                patch.object(node, 'active_owner', return_value={'realOwnerObservation': True}), \
                patch.object(node, 'sample', return_value={'retired': True}), \
                patch.object(node, 'usage', return_value=usage):
            result = node.invoke(client, SimpleNamespace(drain=Mock()), {'budget': budget}, peer,
                                 object(), Path(temporary), selected['releaseDigest'])
        self.assertEqual(state['releases'], [partial, held])
        self.assertEqual(result['status'], 'passed')
        self.assertFalse(result['applicationYieldInserted'])

    def test_native_grant_refusal_requires_known_terminal_zero_work(self):
        from tools.resource_tenant_node import require_denied_before_guest

        counters = ('cpuFuel', 'peakMemoryBytes', 'childCalls', 'outboundRequests',
                    'logBytes', 'effectCount', 'stateReadBytes', 'stateWriteBytes',
                    'blobReadBytes', 'blobWriteBytes')
        denied = {'exitCode': 4, 'processReaped': True, 'response': {
            'schemaVersion': 'latent.cli.result.v1', 'command': 'invoke',
            'outcomeKnown': True, 'requestDispatched': True, 'category': 'platform-failure',
            'error': {'code': 'permission-denied'},
            'data': {'terminalState': 'rejected', 'consumption': dict.fromkeys(counters, '0')}}}
        for zero in (0, '0'):
            row = copy.deepcopy(denied)
            row['response']['data']['consumption'] = dict.fromkeys(counters, zero)
            before = copy.deepcopy(row)
            require_denied_before_guest(row)
            self.assertEqual(row, before)

        # The retained signed witness returned this result shape. It has no
        # terminalState or consumption; neither may be fabricated or dereferenced.
        unknown = {'exitCode': 5, 'processReaped': True, 'response': {
            'schemaVersion': 'latent.cli.result.v1', 'command': 'invoke',
            'outcomeKnown': False, 'requestDispatched': True, 'category': 'transport-failure',
            'data': {'activationId': 'rust-combined-native-denied'},
            'error': {'code': 'rpc-failed', 'grpcCode': 'cancelled'}}}
        for certainty in (False, None, 0, 'true'):
            for data in (unknown['response']['data'], None, {}):
                row = copy.deepcopy(unknown)
                row['response'].update(outcomeKnown=certainty, data=data)
                before = copy.deepcopy(row)
                with self.subTest(certainty=certainty, data=data), self.assertRaisesRegex(
                        WorkflowError, 'resource-tenant-invocation-outcome-unknown'):
                    require_denied_before_guest(row)
                self.assertEqual(row, before)
        row = copy.deepcopy(unknown)
        del row['response']['outcomeKnown']
        with self.assertRaisesRegex(WorkflowError, 'resource-tenant-invocation-outcome-unknown'):
            require_denied_before_guest(row)

        for key in counters:
            for invalid in (1, '1', -1, '-1', False, 0.0, 0.5, '00', '0.0', None, [], {}):
                row = copy.deepcopy(denied)
                row['response']['data']['consumption'][key] = invalid
                with self.subTest(counter=key, value=invalid), self.assertRaises(WorkflowError):
                    require_denied_before_guest(row)
            row = copy.deepcopy(denied)
            del row['response']['data']['consumption'][key]
            with self.subTest(missing=key), self.assertRaises(WorkflowError):
                require_denied_before_guest(row)

        for path, value in (
                (('exitCode',), 0), (('exitCode',), '4'), (('exitCode',), 4.0),
                (('processReaped',), False), (('processReaped',), 1),
                (('response', 'requestDispatched'), False),
                (('response', 'category'), 'success'),
                (('response', 'error'), None), (('response', 'error', 'code'), 'guest-trap'),
                (('response', 'data'), None), (('response', 'data', 'terminalState'), 'completed'),
                (('response', 'data', 'consumption'), None)):
            row = copy.deepcopy(denied)
            target = row
            for part in path[:-1]:
                target = target[part]
            target[path[-1]] = value
            with self.subTest(path=path, value=value), self.assertRaises(WorkflowError):
                require_denied_before_guest(row)
        for row in (None, [], {}, {'response': None}, {'response': []}):
            with self.subTest(row=row), self.assertRaisesRegex(
                    WorkflowError, 'resource-tenant-invocation-result-shape'):
                require_denied_before_guest(row)
