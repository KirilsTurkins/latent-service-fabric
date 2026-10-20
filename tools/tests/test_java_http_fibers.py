"""Source/peer controls only; hosted Java components supply execution evidence."""
from copy import deepcopy
from pathlib import Path
import socket
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest import mock

from tools import java_http_fiber_node as node
from tools import qualify_java_http_fibers as campaign
from tools.java_capsule_build import FIBER_IO_PROFILE
from tools.phase2_operator_process import WorkflowError
from tools.rust_capsule_project import digest, read_file, read_json
from tools.standard_http.peer import Peer, Gate


class JavaHttpFiberSource(unittest.TestCase):
    def test_actual_normal_project_retains_sdk_and_published_lock_with_explicit_world(self):
        with tempfile.TemporaryDirectory() as temporary:
            app = campaign.project(Path(temporary)/'application')
            descriptor = read_json(app/'capsule-project.json')
            lock = read_json(app/'sdk-lock.json')
            source, wit = read_file(campaign.ROOT/campaign.SOURCE), read_file(campaign.ROOT/campaign.WORLD)
            self.assertEqual(descriptor['service'], 'examples/java-standard-http')
            self.assertEqual(descriptor['limits']['outboundRequests'], 8)
            self.assertEqual(descriptor['limits']['cpuFuel'], 1_000_000_000)
            self.assertEqual(descriptor['limits']['wallTimeLimitMillis'], 120000)
            self.assertEqual(lock['template']['sourceDigest'], digest(source))
            self.assertEqual(lock['template']['witDigest'], digest(wit))
            self.assertEqual(read_file(app/'src/dev/latent/app/Capsule.java'), source)
            self.assertEqual(read_file(app/'wit/deps/activation-runtime/package.wit'),
                read_file(app/'vendor/lsf/wit/platform/activation-runtime/package.wit'))
            self.assertIn(b'import latent:runtime/activation@0.1.0;', wit)
            declaration = read_json(app/'java-dependencies.json')
            self.assertIn('http-request', str(declaration))
            for name, identity in lock['sdk'].items():
                self.assertEqual(digest(read_file(app/'vendor/lsf'/name)), identity['digest'])

    def test_only_existing_qualified_profile_and_normal_apis_are_selected(self):
        self.assertEqual(FIBER_IO_PROFILE, 'teavm-activation-fibers-io-v1')
        text = (campaign.ROOT/campaign.SOURCE).read_text(encoding='utf-8')
        for operation in ('HttpRequest.get(', 'new Thread(', 'new Timer(',
                          'Executors.newSingleThreadExecutor()', 'child.join()',
                          'Thread.yield()', 'new ThreadLocal<>()'):
            self.assertIn(operation, text)
        for forbidden in ('ConnectionFactory', 'setConnectionFactory', 'dev.latent.guest.runtime',
                          '.connectTimeout(', '.readTimeout(', 'System.gc(', 'Runtime.getRuntime'):
            self.assertNotIn(forbidden, text)
        self.assertIn('if (which == 2) return invocation + ":root-return:" + completed;', text)
        self.assertIn('if (which == 3) throw new IllegalStateException("owned-root-failure");', text)

    def test_budget_narrowing_never_mutates_or_elevates_original(self):
        target = {'budget': {'cpuFuel': 1_000_000_000, 'wallTimeLimitMillis': 120000, 'outboundRequests': 8}}
        original = deepcopy(target)
        self.assertEqual(node.narrowed_target(target, 5)['budget']['wallTimeLimitMillis'], 3000)
        self.assertEqual(node.narrowed_target(target, 6)['budget']['cpuFuel'], 100_000_000)
        self.assertEqual(target, original)
        for mode in (True, -1, 8, '1'):
            with self.subTest(mode=mode), self.assertRaisesRegex(WorkflowError, 'unknown-case'):
                node.narrowed_target(target, mode)
        for key, value, mode in (('cpuFuel', 99_999_999, 6), ('wallTimeLimitMillis', 2999, 5)):
            changed = deepcopy(target); changed['budget'][key] = value
            with self.subTest(key=key), self.assertRaises(WorkflowError):
                node.narrowed_target(changed, mode)

    def test_real_peer_requires_completed_independent_primary_response(self):
        from contextlib import closing
        credential = ('Bearer ' + 'a'*64).encode('ascii')
        with closing(Peer(credential, maximum_seconds=5)) as peer:
            origin = peer.origin()
            host = f"127.0.0.1:{origin['port']}".encode('ascii')
            with socket.create_connection((origin['host'], origin['port']), timeout=1) as pending, \
                    socket.create_connection((origin['host'], origin['port']), timeout=1) as ready:
                pending.sendall(b'GET /conformance/hold/headers HTTP/1.1\r\nHost: ' + host + b'\r\nAuthorization: '
                                + credential + b'\r\n\r\n')
                for _ in range(64):
                    peer.poll(.005)
                    if peer.gates(): break
                self.assertEqual(len(peer.gates()), 1)
                gate = peer.gates()[0]
                self.assertFalse(node.ready_sibling(peer.observation(), 0, gate))
                ready.sendall(b'GET /conformance/json HTTP/1.1\r\nHost: ' + host + b'\r\nAuthorization: '
                              + credential + b'\r\n\r\n')
                for _ in range(64):
                    peer.poll(.005)
                    if node.ready_sibling(peer.observation(), 0, gate): break
                self.assertTrue(node.ready_sibling(peer.observation(), 0, gate))
                self.assertFalse(node.ready_sibling(peer.observation(), len(peer.observation()['requests']), gate))
                peer.release(gate)
                with self.assertRaises(ValueError): peer.release(gate)
            observation = peer.close()
            self.assertEqual(observation['startedRequests'], 2)
            self.assertEqual(observation['openConnections'], 0)
            self.assertEqual(observation['listeningOrigins'], 0)
            self.assertNotIn(credential.decode(), str(observation))

    def test_forged_or_stale_sibling_observation_does_not_release(self):
        for row in ({'vector': 'domain-json'}, {'vector': 'pending-headers', 'role': 'primary',
                    'closeReason': 'response-write-complete'}, {'vector': 'domain-json', 'role': 'secondary',
                    'closeReason': 'response-write-complete'}):
            with self.subTest(row=row): self.assertFalse(node.ready_sibling({'requests': [row]}, 0))

    def test_sibling_completion_before_pending_gate_cannot_prove_concurrent_progress(self):
        gate = Gate('a'*32, 1, 'headers')
        row = {'request': 2, 'vector': 'domain-json', 'role': 'primary',
               'closeReason': 'response-write-complete'}
        value = {'requests': [{'request': 1}, row], 'events': [
            {'sequence': 1, 'kind': 'response-write-complete', 'request': 2},
            {'sequence': 2, 'kind': 'gate-pending', 'request': 1, 'phase': 'headers'}]}
        self.assertFalse(node.ready_sibling(value, 0, gate))
        value['events'] = [{'sequence': 1, 'kind': 'gate-pending', 'request': 1, 'phase': 'headers'},
                           {'sequence': 2, 'kind': 'response-write-complete', 'request': 2}]
        self.assertTrue(node.ready_sibling(value, 0, gate))

    def test_result_checks_actual_full_resolved_revision_and_known_reaped_outcome(self):
        selected = {'publicationId': 'p', 'releaseDigest': 'sha256:'+'1'*64,
                    'revisionId': 'r', 'routeGeneration': '7'}
        row = {'processReaped': True, 'exitCode': 0, 'decoded': [node.EXPECTED[2]],
               'response': {'outcomeKnown': True, 'data': {'resolvedRevision': selected}}}
        node.validate_result(row, 2, selected)
        changes = []
        for key in selected:
            v = deepcopy(row);v['response']['data']['resolvedRevision'][key] += '-other';changes.append(v)
        v = deepcopy(row);v['response']['outcomeKnown'] = False;changes.append(v)
        v = deepcopy(row);v['processReaped'] = False;changes.append(v)
        v = deepcopy(row);v['decoded'] = ['1:root-return:1'];changes.append(v)
        for value in changes:
            with self.subTest(value=value), self.assertRaises(WorkflowError): node.validate_result(value, 2, selected)

    def test_terminal_codes_cannot_replace_cancellation_deadline_or_fuel(self):
        selected = {'publicationId': 'p'}
        for mode, code in node.FAILURES.items():
            row = {'processReaped': True, 'exitCode': 4, 'decoded': None, 'response': {
                'outcomeKnown': True, 'category': 'platform-failure', 'error': {'code': code},
                'data': {'resolvedRevision': selected, 'terminalState': code.replace('-', '_')}}}
            node.validate_result(row, mode, selected)
            for other in set(node.FAILURES.values()) - {code}:
                changed = deepcopy(row);changed['response']['error']['code'] = other
                with self.subTest(mode=mode, other=other), self.assertRaisesRegex(WorkflowError, 'terminal-result'):
                    node.validate_result(changed, mode, selected)


class JavaHttpFiberControlBoundaries(unittest.TestCase):
    def test_supervisor_releases_once_only_after_pending_owner_and_later_sibling(self):
        with tempfile.TemporaryDirectory() as temporary:
            state = {'done': False, 'started': False, 'released': 0}
            gate = Gate('a'*32, 1, 'headers')
            def observation():
                if not state['started']: return {'requests': []}
                return {'failure': None, 'openConnections': 0, 'requests': [
                    {'request': 1, 'role': 'primary', 'vector': 'pending-headers'},
                    {'request': 2, 'role': 'primary', 'vector': 'domain-json',
                     'closeReason': 'response-write-complete'}], 'events': [
                    {'sequence': 1, 'kind': 'gate-pending', 'request': 1, 'phase': 'headers'},
                    {'sequence': 2, 'kind': 'response-write-complete', 'request': 2}]}
            def release(selected):
                self.assertEqual(selected, gate)
                self.assertTrue(state['started'])
                state['released'] += 1;state['done'] = True
            peer = SimpleNamespace(origin=lambda: {'host': '127.0.0.1', 'port': 1234},
                observation=observation, gates=lambda: [gate] if not state['done'] else [],
                poll=lambda delay: state.update(started=True), release=release)
            client = SimpleNamespace(deadline=time.monotonic()+10, evidence=Path(temporary),
                call=mock.Mock(return_value={'data': {'nodeUsage': {'unavailable': False,
                    'counters': {name: '0' for name in node.ACTIVE_COUNTERS}}}}))
            process = SimpleNamespace(owner=SimpleNamespace(exited=lambda: state['done']),
                                      drain=mock.Mock(), close=mock.Mock())
            row = {'processReaped': True, 'exitCode': 0, 'decoded': [node.EXPECTED[0]],
                   'response': {'outcomeKnown': True, 'data': {'resolvedRevision': {'p': 1}}}}
            with mock.patch.object(node, 'start_call', return_value=process), \
                    mock.patch.object(node, 'selected_revision', return_value={'p': 1}), \
                    mock.patch.object(node, 'finish_call', return_value=row), \
                    mock.patch.object(node, 'sample', side_effect=[{'held': True}, {'idle': True}]) as samples:
                result = node.invoke(client, SimpleNamespace(drain=mock.Mock()), {'name': 'route', 'budget': {}},
                                     peer, None, 0, 'pending-progress')
            self.assertEqual(state['released'], 1)
            self.assertTrue(result['releasedOnce'])
            self.assertEqual(result['pendingOwner'], {'held': True})
            self.assertEqual(result['retired'], {'idle': True})
            self.assertEqual(samples.call_count, 2)
            self.assertTrue(samples.call_args_list[0].kwargs['active'])
            process.close.assert_called_once()

    def test_missing_pending_witness_cannot_pass_an_early_root_return(self):
        process = SimpleNamespace(owner=SimpleNamespace(exited=lambda: True), close=mock.Mock())
        peer = SimpleNamespace(origin=lambda: {'host': '127.0.0.1', 'port': 1234},
                               observation=lambda: {'requests': []})
        client = SimpleNamespace(deadline=time.monotonic()+10)
        row = {'processReaped': True, 'exitCode': 0, 'decoded': [node.EXPECTED[2]],
               'response': {'outcomeKnown': True, 'data': {'resolvedRevision': {'p': 1}}}}
        with mock.patch.object(node, 'start_call', return_value=process), \
                mock.patch.object(node, 'selected_revision', return_value={'p': 1}), \
                mock.patch.object(node, 'finish_call', return_value=row), \
                self.assertRaisesRegex(WorkflowError, 'no-actual-pending-witness'):
            node.invoke(client, None, {'budget': {}}, peer, None, 2, 'root-return')
        process.close.assert_called_once()

    def test_uncertain_cancellation_preserves_original_exception_without_replay(self):
        failure = RuntimeError('synthetic control failure')
        cancel = mock.Mock(side_effect=failure)
        client = SimpleNamespace(deadline=time.monotonic()+10, call=cancel)
        process = SimpleNamespace(owner=SimpleNamespace(exited=lambda: False), drain=mock.Mock(), close=mock.Mock())
        gate = Gate('a'*32, 1, 'headers')
        observations = iter([{'requests': []}, {'requests': [{'vector': 'pending-headers'}], 'failure': None}])
        peer = SimpleNamespace(origin=lambda: {'host': '127.0.0.1', 'port': 1234},
            observation=lambda: next(observations), gates=lambda: [gate], poll=mock.Mock(), release=mock.Mock())
        with mock.patch.object(node, 'start_call', return_value=process), \
                mock.patch.object(node, 'selected_revision', return_value={}), \
                mock.patch.object(node, 'sample', return_value={'active': True}), \
                self.assertRaises(RuntimeError) as caught:
            node.invoke(client, SimpleNamespace(drain=mock.Mock()), {'budget': {}}, peer, None, 4, 'cancel')
        self.assertIs(caught.exception, failure)
        cancel.assert_called_once()
        peer.release.assert_not_called()
        process.close.assert_called_once()

    def test_changed_candidate_refuses_before_review_cache_or_compilation(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            binaries = {}
            for name in ('latent', 'latentd', 'capsule_authoring', 'capsule_contracts', 'package'):
                path=root/name;path.write_bytes(name.encode());binaries[name]=path
            def resolve(label, *argv):
                Path(argv[argv.index('--candidate')+1]).write_bytes(b'changed reviewed graph')
            commands = SimpleNamespace(run=mock.Mock(side_effect=resolve), deadline=time.monotonic()+30)
            with mock.patch.object(campaign, 'project', return_value=root/'application'), \
                    mock.patch.object(campaign, 'compiler_cache') as cache, \
                    mock.patch.object(campaign, 'build') as build, \
                    self.assertRaisesRegex(WorkflowError, 'original-client-closure'):
                campaign.execute(commands, binaries, root/'sdk', root/'evidence')
            commands.run.assert_called_once()
            cache.assert_not_called();build.assert_not_called()
            self.assertEqual(read_json(root/'evidence/FAILED.json')['stage'], 'normal-resolve')

    def test_failure_observer_preserves_original_exception(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);binary=root/'binary';binary.write_bytes(b'controlled')
            failure=RuntimeError('fixture boundary')
            with mock.patch.object(campaign, 'project', side_effect=failure), \
                    mock.patch.object(campaign, 'write_json', side_effect=OSError('observer')), \
                    self.assertRaises(RuntimeError) as caught:
                campaign.execute(SimpleNamespace(), {'latent': binary}, root/'sdk', root/'evidence')
            self.assertIs(caught.exception, failure)

    def test_nonlinux_refuses_before_prepared_read_or_output_creation(self):
        with mock.patch.object(campaign.sys, 'platform', 'win32'), \
                mock.patch.object(campaign, 'verify_prepared') as verify, \
                mock.patch.object(campaign, 'fresh') as fresh, \
                self.assertRaisesRegex(WorkflowError, 'linux-required'):
            campaign.run(Path('output'), Path('prepared'), Path('sdk'))
        verify.assert_not_called();fresh.assert_not_called()
