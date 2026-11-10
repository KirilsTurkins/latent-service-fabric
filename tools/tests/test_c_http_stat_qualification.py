"""Local qualification-harness controls; no guest or provider is executed."""
from contextlib import ExitStack, contextmanager
import socket
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from tools import c_http_stat_qualification as stat
from tools.phase2_operator_process import WorkflowError
from tools.standard_http.vectors import DOMAIN, json_bytes


class StatQualificationControls(unittest.TestCase):
    def test_fixture_uses_the_existing_captured_http_profile(self):
        from tools import c_capsule_project, c_thread_runtime_fixture
        from tools.c_guest.standard_facilities import FETCH_PROFILE
        from tools.rust_capsule_project import read_json, snapshot
        with tempfile.TemporaryDirectory() as tmp:
            project = c_thread_runtime_fixture.prepare_http(Path(tmp) / 'project')
            (project / 'src/main.c').write_bytes((stat.ROOT / stat.PROBE).read_bytes())
            c_capsule_project.validate(snapshot(project))
            self.assertEqual(read_json(project / 'capsule-project.json')['runtimeProfile'], FETCH_PROFILE)
            self.assertEqual(stat.CASES, ('missing-grant', 'normal', 'denied', 'not-found', 'redirect', 'fresh',
                                          'range', 'range-ignored', 'range-denied',
                                          'range-unsolicited', 'range-before'))

    def test_policy_separates_head_and_get_and_refuses_wrong_provider(self):
        descriptor = {'capability': stat.owner.HTTP, 'profile': 'bounded-streaming-http-identity-v1',
                      'tenant': 'examples', 'service': 'http-host', 'configurationEpoch': '1',
                      'configurationDigest': 'sha256:' + 'a' * 64}
        node = SimpleNamespace(startup_record={'providers': [descriptor]})
        target = {'service': 'examples/c-thread-runtime', 'publication': 'pub'}
        origin = {'scheme': 'http', 'host': '127.0.0.1', 'port': 1234}
        with patch.object(stat.owner, 'install', return_value=[{'capability': 'runtime'}]), \
                patch.object(stat, 'policy') as policy:
            grants = stat.install(object(), node, target, origin)
            self.assertEqual(grants[-1], {'capability': stat.owner.HTTP, 'policy': 'http-allow'})
            rules = policy.call_args_list[1].args[3]['rules']
            self.assertEqual([row['resources']['methods'] for row in rules], [['HEAD'], ['GET']])
            self.assertEqual(rules[0]['resources']['paths'],
                             ['/conformance/json', '/conformance/status/404', '/conformance/redirect'])
            self.assertEqual(rules[1]['resources']['paths'],
                             ['/conformance/echo', '/conformance/json', '/conformance/body/boundary'])
            self.assertTrue(all(row['resources']['origins'] == [origin] for row in rules))
        node.startup_record['providers'][0]['profile'] = 'wrong'
        with patch.object(stat.owner, 'install', return_value=[]), patch.object(stat, 'policy') as policy:
            with self.assertRaisesRegex(WorkflowError, 'c-stat-installed-http-provider'):
                stat.install(object(), node, target, origin)
            policy.assert_not_called()

    def test_range_peer_requires_exact_request_and_emits_actual_partial_bytes(self):
        full = json_bytes(DOMAIN)
        request = SimpleNamespace(method=b'GET', headers={b'range': b'bytes=5-'})
        response = stat.partial_response(request)
        self.assertEqual(response, stat.head(206, len(full) - 5,
            headers=((b'Content-Range', f'bytes 5-{len(full)-1}/{len(full)}'.encode()),)) + full[5:])
        for method, value in ((b'HEAD', b'bytes=5-'), (b'GET', b'bytes=6-'), (b'GET', None)):
            with self.subTest(method=method, value=value):
                request.method = method; request.headers = {} if value is None else {b'range': value}
                with self.assertRaisesRegex(WorkflowError, 'c-range-exact-request'):
                    stat.partial_response(request)

    def test_range_peer_serves_real_partial_and_ignored_requests(self):
        token = b'Bearer ' + b'a' * 64
        peer = stat.RangePeer(token, maximum_seconds=10)
        try:
            def exchange(path, *, send_range=True):
                origin = peer.origin()
                client = socket.create_connection(('127.0.0.1', origin['port']), timeout=2)
                try:
                    client.sendall(b'GET ' + path + b' HTTP/1.1\r\nHost: 127.0.0.1:' +
                        str(origin['port']).encode() + b'\r\nAuthorization: ' + token +
                        b'\r\n' + (b'Range: bytes=5-\r\n' if send_range else b'') +
                        b'Connection: close\r\n\r\n')
                    client.setblocking(False); data = bytearray(); deadline = time.monotonic() + 3
                    while time.monotonic() < deadline:
                        peer.poll(0.01)
                        try: block = client.recv(16384)
                        except BlockingIOError: continue
                        if not block: return bytes(data)
                        data.extend(block)
                    self.fail('controlled peer did not close')
                finally:
                    client.close()
            full = json_bytes(DOMAIN)
            partial = exchange(b'/conformance/json')
            self.assertEqual(partial, stat.head(206, len(full) - 5,
                headers=((b'Content-Range', f'bytes 5-{len(full)-1}/{len(full)}'.encode()),)) + full[5:])
            ignored = exchange(b'/conformance/body/boundary')
            self.assertTrue(ignored.startswith(b'HTTP/1.1 200 '))
            self.assertEqual(ignored.split(b'\r\n\r\n', 1)[1], b'x' * 8192)
            unsolicited = exchange(b'/conformance/json', send_range=False)
            self.assertEqual(unsolicited, stat.head(206, 4,
                headers=((b'Content-Range', b'bytes 0-3/*'),)) + b'abcd')
            before = exchange(b'/conformance/echo')
            self.assertEqual(before, stat.head(206, 4,
                headers=((b'Content-Range', b'bytes 0-3/4'),)) + b'abcd')
            self.assertEqual(peer.range_requests, 3)
            self.assertEqual(peer.unsolicited_requests, 1)
            self.assertEqual(peer.early_range_requests, 1)
            self.assertEqual(peer.observation()['openConnections'], 0)
        finally:
            peer.close()

    def test_redirect_peer_returns_location_to_live_secondary_without_contact(self):
        token = b'Bearer ' + b'a' * 64
        peer = stat.RangePeer(token, maximum_seconds=10)
        try:
            before = peer.observation()
            origin, secondary = peer.origin(), peer.origin('secondary')
            client = socket.create_connection(('127.0.0.1', origin['port']), timeout=2)
            try:
                client.sendall(b'HEAD /conformance/redirect HTTP/1.1\r\nHost: 127.0.0.1:' +
                    str(origin['port']).encode() + b'\r\nAuthorization: ' + token +
                    b'\r\nConnection: close\r\n\r\n')
                client.setblocking(False); data = bytearray(); deadline = time.monotonic() + 3
                while time.monotonic() < deadline:
                    peer.poll(0.01)
                    try: block = client.recv(16384)
                    except BlockingIOError: continue
                    if not block: break
                    data.extend(block)
                else:
                    self.fail('controlled redirect peer did not close')
            finally:
                client.close()
            location = f"http://127.0.0.1:{secondary['port']}/conformance/redirect-target".encode()
            self.assertEqual(bytes(data), stat.head(302, 0, headers=((b'Location', location),)))
            change = stat.delta(before, peer.observation())
            self.assertEqual((change['acceptedConnections'], change['startedRequests']), (1, 1))
            self.assertEqual([(row['role'], row['vector']) for row in change['requests']],
                             [('primary', 'redirect')])
            self.assertTrue(change['requests'][0]['authorizationPresent'])
        finally:
            peer.close()

    def test_redirect_cell_requires_exact_failure_and_no_secondary_contact(self):
        consumed = {k: '0' for k in ('stateReadBytes', 'stateWriteBytes', 'blobReadBytes',
                    'blobWriteBytes', 'logBytes', 'effectCount', 'childCalls')}
        consumed.update(cpuFuel='1', peakMemoryBytes='1')
        row = {'processReaped': True, 'exitCode': 3, 'decoded': [{'err': 'redirect-unsupported'}],
               'response': {'outcomeKnown': True, 'requestDispatched': True,
                            'data': {'resolvedRevision': 'revision', 'consumption': consumed}}}
        change = {'acceptedConnections': 1, 'startedRequests': 1,
                  'requests': [{'vector': 'redirect', 'method': 'HEAD', 'role': 'primary',
                                'authorizationPresent': True}],
                  'rejectedRequests': 0, 'connectionBoundRejections': 0}
        peer = Mock(); peer.url.return_value = 'http://peer/redirect'
        peer.observation.return_value = {'openConnections': 0}
        client = SimpleNamespace(deadline=10**12)
        process = SimpleNamespace(owner=SimpleNamespace(exited=lambda: True))
        with tempfile.TemporaryDirectory() as tmp, \
                patch.object(stat.owner, 'selected_revision', return_value='revision'), \
                patch.object(stat.owner, 'start_http_call', return_value=process) as start, \
                patch.object(stat.owner, 'finish_call', return_value=row), \
                patch.object(stat.owner, 'retire', return_value={'physicalOwnersAfter': 0}) as retire, \
                patch.object(stat.owner, 'close_call'), patch.object(stat, 'validate'), \
                patch.object(stat, 'delta', return_value=change), \
                patch.object(stat, 'require_zero_contact') as no_late:
            def output(name):
                path = Path(tmp) / name
                path.mkdir()
                return path
            result = stat.cell(client, object(), {}, peer, output('good'), 'redirect')
            self.assertEqual(start.call_args.args[2], 'redirect\nhttp://peer/redirect')
            self.assertEqual(result['retirement']['physicalOwnersAfter'], 0)
            no_late.assert_called_once(); peer.poll.assert_called_once_with(0.05)
            row['decoded'] = [{'err': 'unexpected-stat-error'}]
            with self.assertRaisesRegex(WorkflowError, 'c-stat-exact-ordinary-result'):
                stat.cell(client, object(), {}, peer, output('wrong-result'), 'redirect')
            row['decoded'] = [{'err': 'redirect-unsupported'}]
            change['acceptedConnections'] = 2
            change['requests'].append({'role': 'secondary'})
            with self.assertRaisesRegex(WorkflowError, 'c-stat-one-authenticated-head-no-replay'):
                stat.cell(client, object(), {}, peer, output('secondary-contact'), 'redirect')
            self.assertEqual(retire.call_count, 1)
            change['acceptedConnections'] = 1
            change['requests'].pop()
            no_late.side_effect = WorkflowError('late-secondary-contact')
            with self.assertRaisesRegex(WorkflowError, 'late-secondary-contact'):
                stat.cell(client, object(), {}, peer, output('late-contact'), 'redirect')
            self.assertEqual(retire.call_count, 2)

    def test_invalid_response_requires_the_selected_request_shape(self):
        request = SimpleNamespace(method=b'GET', headers={})
        self.assertEqual(stat.invalid_partial_response(request, unsolicited=True), stat.head(206, 4,
            headers=((b'Content-Range', b'bytes 0-3/*'),)) + b'abcd')
        with self.assertRaisesRegex(WorkflowError, 'c-before-exact-range-request'):
            stat.invalid_partial_response(request, unsolicited=False)
        request.headers = {b'range': b'bytes=5-'}
        self.assertEqual(stat.invalid_partial_response(request, unsolicited=False), stat.head(206, 4,
            headers=((b'Content-Range', b'bytes 0-3/4'),)) + b'abcd')
        with self.assertRaisesRegex(WorkflowError, 'c-unsolicited-request-has-range'):
            stat.invalid_partial_response(request, unsolicited=True)
        request.method = b'HEAD'
        with self.assertRaisesRegex(WorkflowError, 'c-invalid-partial-method'):
            stat.invalid_partial_response(request, unsolicited=False)

    def test_invalid_cells_require_exact_error_peer_and_retirement(self):
        consumed = {k: '0' for k in ('stateReadBytes', 'stateWriteBytes', 'blobReadBytes',
                    'blobWriteBytes', 'logBytes', 'effectCount', 'childCalls')}
        consumed.update(cpuFuel='1', peakMemoryBytes='1')
        row = {'processReaped': True, 'exitCode': 3, 'decoded': [{'err': 'invalid-content-range'}],
               'response': {'outcomeKnown': True, 'requestDispatched': True,
                            'data': {'resolvedRevision': 'revision', 'consumption': consumed}}}
        change = {'startedRequests': 1, 'requests': [{'vector': 'domain-json', 'method': 'GET',
                   'role': 'primary', 'authorizationPresent': True}],
                  'rejectedRequests': 0, 'connectionBoundRejections': 0}
        peer = Mock(); peer.url.side_effect = lambda vector: 'http://peer/' + vector
        peer.observation.return_value = {'openConnections': 0}
        client = SimpleNamespace(deadline=10**12)
        process = SimpleNamespace(owner=SimpleNamespace(exited=lambda: True))
        with tempfile.TemporaryDirectory() as tmp, \
                patch.object(stat.owner, 'selected_revision', return_value='revision'), \
                patch.object(stat.owner, 'start_http_call', return_value=process) as start, \
                patch.object(stat.owner, 'finish_call', return_value=row), \
                patch.object(stat.owner, 'retire', return_value={'physicalOwnersAfter': 0}) as retire, \
                patch.object(stat.owner, 'close_call'), patch.object(stat, 'validate'), \
                patch.object(stat, 'delta', return_value=change):
            def output(name):
                path = Path(tmp) / name
                path.mkdir()
                return path
            for case, vector in (('range-unsolicited', 'domain-json'), ('range-before', 'method-bytes')):
                change['requests'][0]['vector'] = vector
                result = stat.cell(client, object(), {}, peer, output(case), case)
                self.assertEqual(result['case'], case)
                self.assertEqual(start.call_args.args[2], case + '\nhttp://peer/' + vector)
                self.assertEqual(result['retirement']['physicalOwnersAfter'], 0)
            self.assertEqual(retire.call_count, 2)
            row['decoded'] = [{'err': 'unexpected-range-error'}]
            with self.assertRaisesRegex(WorkflowError, 'c-stat-exact-ordinary-result'):
                stat.cell(client, object(), {}, peer, output('bad-result'), 'range-before')
            row['decoded'] = [{'err': 'invalid-content-range'}]
            change['requests'][0]['authorizationPresent'] = False
            with self.assertRaisesRegex(WorkflowError, 'c-stat-one-authenticated-head-no-replay'):
                stat.cell(client, object(), {}, peer, output('bad-peer'), 'range-before')
            self.assertEqual(retire.call_count, 2)

    def test_exact_result_and_peer_head_are_required(self):
        consumed = {k: '0' for k in ('stateReadBytes', 'stateWriteBytes', 'blobReadBytes',
                    'blobWriteBytes', 'logBytes', 'effectCount', 'childCalls')}
        consumed.update(cpuFuel='1', peakMemoryBytes='1')
        row = {'processReaped': True, 'exitCode': 0,
               'decoded': [{'ok': f'{len(json_bytes(DOMAIN))}:0:0'}],
               'response': {'outcomeKnown': True, 'requestDispatched': True,
                            'data': {'resolvedRevision': 'revision', 'consumption': consumed}}}
        change = {'startedRequests': 1, 'requests': [{'vector': 'domain-json', 'method': 'HEAD',
                   'role': 'primary', 'authorizationPresent': True}],
                  'rejectedRequests': 0, 'connectionBoundRejections': 0}
        peer = Mock(); peer.url.return_value = 'http://127.0.0.1:1234/conformance/json'
        peer.observation.return_value = {'openConnections': 0}
        client = SimpleNamespace(deadline=10**12)
        process = SimpleNamespace(owner=SimpleNamespace(exited=lambda: True))
        with tempfile.TemporaryDirectory() as tmp, \
                patch.object(stat.owner, 'selected_revision', return_value='revision'), \
                patch.object(stat.owner, 'start_http_call', return_value=process), \
                patch.object(stat.owner, 'finish_call', return_value=row), \
                patch.object(stat.owner, 'retire', return_value={'physicalOwnersAfter': 0}), \
                patch.object(stat.owner, 'close_call'), patch.object(stat, 'validate'), \
                patch.object(stat, 'delta', return_value=change):
            first, second = Path(tmp) / 'first', Path(tmp) / 'second'
            first.mkdir(); second.mkdir()
            result = stat.cell(client, object(), {}, peer, first, 'normal')
            self.assertEqual(result['case'], 'normal')
            change['requests'][0]['method'] = 'GET'
            with self.assertRaisesRegex(WorkflowError, 'c-stat-one-authenticated-head-no-replay'):
                stat.cell(client, object(), {}, peer, second, 'normal')

    def test_range_cell_requires_exact_payload_metadata_and_peer_method(self):
        consumed = {k: '0' for k in ('stateReadBytes', 'stateWriteBytes', 'blobReadBytes',
                    'blobWriteBytes', 'logBytes', 'effectCount', 'childCalls')}
        consumed.update(cpuFuel='1', peakMemoryBytes='1')
        data = json_bytes(DOMAIN); checksum = 0
        for byte in data[5:]: checksum = (checksum * 33 + byte) & 0xffffffff
        row = {'processReaped': True, 'exitCode': 0,
               'decoded': [{'ok': f'5:{len(data)-5}:{len(data)}:{len(data)-5}:{checksum}'}],
               'response': {'outcomeKnown': True, 'requestDispatched': True,
                            'data': {'resolvedRevision': 'revision', 'consumption': consumed}}}
        change = {'startedRequests': 1, 'requests': [{'vector': 'domain-json', 'method': 'GET',
                   'role': 'primary', 'authorizationPresent': True}],
                  'rejectedRequests': 0, 'connectionBoundRejections': 0}
        peer = Mock(); peer.url.return_value = 'http://127.0.0.1:1234/conformance/json'
        peer.observation.return_value = {'openConnections': 0}
        client = SimpleNamespace(deadline=10**12)
        process = SimpleNamespace(owner=SimpleNamespace(exited=lambda: True))
        with tempfile.TemporaryDirectory() as tmp, \
                patch.object(stat.owner, 'selected_revision', return_value='revision'), \
                patch.object(stat.owner, 'start_http_call', return_value=process), \
                patch.object(stat.owner, 'finish_call', return_value=row), \
                patch.object(stat.owner, 'retire', return_value={'physicalOwnersAfter': 0}), \
                patch.object(stat.owner, 'close_call'), patch.object(stat, 'validate'), \
                patch.object(stat, 'delta', return_value=change):
            first, second = Path(tmp) / 'first', Path(tmp) / 'second'
            first.mkdir(); second.mkdir()
            self.assertEqual(stat.cell(client, object(), {}, peer, first, 'range')['case'], 'range')
            change['requests'][0]['method'] = 'HEAD'
            with self.assertRaisesRegex(WorkflowError, 'c-stat-one-authenticated-head-no-replay'):
                stat.cell(client, object(), {}, peer, second, 'range')

    def test_followup_controls_and_single_invocation_are_bounded_before_dispatch(self):
        attempted = []
        def control(client, *args, **kwargs):
            client.control_attempts += 1
            attempted.append(args)
            return 'called'
        with tempfile.TemporaryDirectory() as tmp, patch.object(stat.RecordingClient, '_control_call', control):
            root = Path(tmp)
            first = stat.FollowupClient('latent', root, Mock(), time.monotonic() + 60,
                                        primary_attempts=382, evidence=root / 'first')
            self.assertEqual(first._control_call('node', 'get'), 'called')
            first.reserve_invocation()
            self.assertEqual(first._control_call('node', 'get'), 'called')
            with self.assertRaisesRegex(WorkflowError, 'c-stat-followup-control-bound'):
                first._control_call('node', 'get')
            with self.assertRaisesRegex(WorkflowError, 'c-stat-followup-invocation-bound'):
                first.reserve_invocation()
            self.assertEqual(len(attempted), 2)
            second = stat.FollowupClient('latent', root, Mock(), time.monotonic() + 60,
                                         primary_attempts=0, evidence=root / 'second')
            second.control_attempts = 127
            second.reserve_invocation()
            self.assertEqual(second._control_call('node', 'get'), 'called')
            with self.assertRaisesRegex(WorkflowError, 'c-stat-followup-control-bound'):
                second._control_call('node', 'get')
            self.assertEqual(len(attempted), 3)
            with self.assertRaisesRegex(WorkflowError, 'c-stat-followup-primary-control-bound'):
                stat.FollowupClient('latent', root, Mock(), time.monotonic() + 60,
                                    primary_attempts=384, evidence=root / 'third')

    def test_missing_provider_omits_only_exact_http_installation_and_binding(self):
        runtimes = [{'contract': capability, 'name': 'runtime'} for capability in stat.owner.PROVIDERS]
        http = {'contract': stat.owner.HTTP, 'name': 'http-standard'}
        settings = {'providers': {'httpStreaming': {'sentinel': 1},
                                  'bindings': [*runtimes, http], 'unrelated': {'retained': True}}}
        stat.omit_http_provider(settings)
        self.assertNotIn('httpStreaming', settings['providers'])
        self.assertEqual(settings['providers']['bindings'], runtimes)
        self.assertEqual(settings['providers']['unrelated'], {'retained': True})
        malformed = {'providers': {'httpStreaming': {}, 'bindings': [*runtimes, http, dict(http)]}}
        with self.assertRaisesRegex(WorkflowError, 'c-stat-exact-http-provider-to-omit'):
            stat.omit_http_provider(malformed)
        self.assertIn('httpStreaming', malformed['providers'])
        self.assertEqual(len(malformed['providers']['bindings']), len(runtimes) + 2)

    def test_missing_provider_orchestrates_original_component_and_runtime_only(self):
        runtimes = [{'capability': capability, 'policy': 'runtime'} for capability in stat.owner.PROVIDERS]
        consumed = {'cpuFuel': '0', 'peakMemoryBytes': '0', 'outboundRequests': '0'}
        row = {'exitCode': 4, 'processReaped': True, 'decoded': None,
               'response': {'outcomeKnown': True, 'error': {'code': 'incompatible-contract'},
                            'data': {'terminalState': 'rejected', 'consumption': consumed}}}
        ready = {'state': 'ready', 'acceptedConnections': 0, 'startedRequests': 0, 'requests': []}
        stopped = {**ready, 'state': 'stopped'}
        peer = Mock(); peer.origin.return_value = {'scheme': 'http', 'host': '127.0.0.1', 'port': 1234}
        peer.url.return_value = 'http://127.0.0.1:1234/conformance/json'
        peer.observation.return_value = ready; peer.close.return_value = stopped
        node = Mock(); node.startup_record = {'providers': [{'capability': cap} for cap in stat.owner.PROVIDERS]}
        process = SimpleNamespace(owner=SimpleNamespace(exited=lambda: True))
        cancellation = SimpleNamespace(check=Mock())
        @contextmanager
        def cancellation_scope():
            yield cancellation
        with tempfile.TemporaryDirectory() as tmp, ExitStack() as patches:
            base = Path(tmp); artifact = base / 'artifact'; artifact.mkdir()
            (artifact / 'capsule.json').write_text('{}')
            (artifact / 'component.wasm').write_bytes(b'original-component')
            binary = base / 'latentd'; binary.write_bytes(b'original-node')
            digest = stat.file_identity(artifact / 'component.wasm')['sha256']
            client = Mock(); client.deadline = time.monotonic() + 100; client.calls = 1
            client.control_attempts = 1; client.invocation_attempts = 1
            def client_call(*args, **kwargs):
                if args[:2] == ('release', 'publish-package'):
                    return {'outcomeKnown': True, 'data': {'release': {'digest': digest},
                            'operation': {'publication': {'id': 'same-publication'}}}}
                if args[:2] == ('capability', 'list'):
                    return {'data': {'nodeUsage': {'unavailable': ['http'], 'counters': {}}}}
                self.fail('unexpected client call')
            client.call.side_effect = client_call
            def configure(directory, signed, port, *, language):
                return directory / 'node.json', {'providers': {'bindings': []}}
            def configure_http(settings, capsule, current_peer, credential):
                settings['providers']['httpStreaming'] = {}
                settings['providers']['bindings'] = ([{'contract': cap} for cap in stat.owner.PROVIDERS]
                                                      + [{'contract': stat.owner.HTTP}])
            target = {'name': 'route', 'service': 'service', 'publication': 'same-publication',
                      'generation': '1', 'grants': []}
            def deploy(client, source, publication, *, generation='0', grants=None):
                return {**target, 'generation': str(int(generation) + 1),
                        'grants': [] if grants is None else list(grants)}
            pairs = [(stat, 'owned_cancellation', cancellation_scope), (stat, 'RangePeer', Mock(return_value=peer)),
                     (stat, 'FollowupClient', Mock(return_value=client)), (stat, 'configure_base', configure),
                     (stat.owner, 'configure_http', configure_http), (stat, 'connect', Mock(return_value=node)),
                     (stat, 'Probe', Mock()), (stat, 'deploy', Mock(side_effect=deploy)),
                     (stat.owner, 'install', Mock(return_value=runtimes)),
                     (stat.owner, 'start_http_call', Mock(return_value=process)),
                     (stat.owner, 'finish_call', Mock(return_value=row)), (stat.owner, 'close_call', Mock()),
                     (stat, 'validate', Mock()), (stat, 'require_zero_contact', Mock()),
                     (stat, 'sample', Mock(return_value={'physicalOwnersAfter': 0})),
                     (stat, 'delete_all', Mock()), (stat, 'stop', Mock()),
                     (stat, 'stopped_record', Mock(return_value={'reaped': True, 'record': {'clean': True}}))]
            for obj, name, replacement in pairs:
                patches.enter_context(patch.object(obj, name, replacement))
            result = stat.missing_provider(artifact, base / 'signed',
                {'latent': base / 'latent', 'latentd': binary}, base / 'result', time.monotonic() + 100, 200)
            self.assertEqual(result['status'], 'passed')
            self.assertFalse(result['unavailableCountersCountedAsZero'])
            self.assertEqual(result['providerObservation']['unavailable'], ['http'])
            self.assertEqual(stat.owner.start_http_call.call_args.args[2],
                             'normal\nhttp://127.0.0.1:1234/conformance/json')
            self.assertEqual(stat.owner.start_http_call.call_args.args[1]['grants'], runtimes)
            self.assertEqual(stat.require_zero_contact.call_count, 2)
            client.reserve_invocation.assert_called_once()
            self.assertIn('idleObservation', result)
            self.assertNotIn('physicalRetirement', result)
            self.assertEqual(result['cliCalls'], 1)
            self.assertEqual(result['controlAttempts'], 1)
            self.assertEqual(result['invocationAttempts'], 1)
            self.assertTrue((base / 'result' / 'qualified.json').is_file())

    def test_missing_provider_requires_pre_guest_rejection_and_zero_consumption(self):
        row = {'exitCode': 4, 'processReaped': True, 'decoded': None,
               'response': {'outcomeKnown': True, 'error': {'code': 'incompatible-contract'},
                            'data': {'terminalState': 'rejected', 'consumption':
                                     {'cpuFuel': '0', 'peakMemoryBytes': '0', 'outboundRequests': '0',
                                      'wallTimeMicros': '15'}}}}
        stat.require_missing_provider_result(row)
        for key, value in (('cpuFuel', '1'), ('peakMemoryBytes', '1'), ('outboundRequests', '1')):
            row['response']['data']['consumption'][key] = value
            with self.subTest(key=key), self.assertRaisesRegex(WorkflowError, 'c-stat-missing-provider-rejected-before-guest'):
                stat.require_missing_provider_result(row)
            row['response']['data']['consumption'][key] = '0'
        row['response']['error']['code'] = 'permission-denied'
        with self.assertRaisesRegex(WorkflowError, 'c-stat-missing-provider-rejected-before-guest'):
            stat.require_missing_provider_result(row)
        row['response']['error']['code'] = 'incompatible-contract'
        row['decoded'] = [{'err': 'something'}]
        with self.assertRaisesRegex(WorkflowError, 'c-stat-missing-provider-rejected-before-guest'):
            stat.require_missing_provider_result(row)

    def test_missing_http_grant_is_absent_for_first_cell_then_original_grants_return(self):
        grants = [{'capability': capability, 'policy': 'original-runtime'}
                  for capability in stat.owner.PROVIDERS]
        grants.append({'capability': stat.owner.HTTP, 'policy': 'http-allow'})
        target = {'name': 'route', 'service': 'service', 'publication': 'pub',
                  'generation': '1', 'grants': []}
        seen = []
        def deploy(client, source, publication, *, generation, grants):
            return {**target, 'generation': str(int(generation) + 1), 'grants': list(grants)}
        def cell(client, probe, current, peer, output, case):
            seen.append((case, tuple(grant['capability'] for grant in current['grants'])))
            return {'case': case}
        peer = Mock(); peer.origin.return_value = {'host': '127.0.0.1', 'port': 1234}
        with patch.object(stat, 'install', return_value=grants), \
                patch.object(stat, 'deploy', side_effect=deploy) as deployment, \
                patch.object(stat, 'cell', side_effect=cell):
            result, cases = stat.exercise_cells(object(), object(), object(), Path('/signed'),
                                                target, peer, Path('/out'))
            self.assertEqual([row['case'] for row in cases], list(stat.CASES))
            self.assertEqual(seen[0][0], 'missing-grant')
            self.assertEqual(set(seen[0][1]), set(stat.owner.PROVIDERS))
            self.assertNotIn(stat.owner.HTTP, seen[0][1])
            self.assertEqual(seen[1][0], 'normal')
            self.assertTrue(all(stat.owner.HTTP in capabilities for _, capabilities in seen[1:]))
            self.assertEqual(result['grants'], grants)
            self.assertEqual(deployment.call_count, 2)
        with patch.object(stat, 'install', return_value=grants[:-1]), \
                patch.object(stat, 'deploy') as deployment:
            with self.assertRaisesRegex(WorkflowError, 'c-stat-exact-runtime-only-grants'):
                stat.exercise_cells(object(), object(), object(), Path('/signed'), target, peer, Path('/out'))
            deployment.assert_not_called()

    def test_missing_grant_cell_uses_allowed_head_path_and_demands_zero_contact(self):
        consumed = {'cpuFuel': '0', 'peakMemoryBytes': '0', 'outboundRequests': '0'}
        row = {'processReaped': True, 'exitCode': 4, 'decoded': None,
               'response': {'outcomeKnown': True, 'error': {'code': 'permission-denied'},
                            'data': {'consumption': consumed}}}
        peer = Mock(); peer.url.return_value = 'http://peer/conformance/json'
        peer.observation.return_value = {'openConnections': 0}
        client = SimpleNamespace(deadline=10**12)
        process = SimpleNamespace(owner=SimpleNamespace(exited=lambda: True))
        with tempfile.TemporaryDirectory() as tmp, \
                patch.object(stat.owner, 'selected_revision', return_value='revision'), \
                patch.object(stat.owner, 'start_http_call', return_value=process) as start, \
                patch.object(stat.owner, 'finish_call', return_value=row), \
                patch.object(stat.owner, 'retire', return_value={'physicalOwnersAfter': 0}), \
                patch.object(stat.owner, 'close_call'), patch.object(stat, 'validate'), \
                patch.object(stat, 'delta', return_value={}), patch.object(stat, 'require_zero_contact') as zero:
            first, second = Path(tmp) / 'first', Path(tmp) / 'second'
            first.mkdir(); second.mkdir()
            result = stat.cell(client, object(), {}, peer, first, 'missing-grant')
            self.assertEqual(result['case'], 'missing-grant')
            peer.url.assert_called_once_with('domain-json')
            self.assertEqual(start.call_args.args[2], 'normal\nhttp://peer/conformance/json')
            zero.assert_called_once()
            zero.side_effect = WorkflowError('unexpected-contact')
            with self.assertRaisesRegex(WorkflowError, 'unexpected-contact'):
                stat.cell(client, object(), {}, peer, second, 'missing-grant')
            third = Path(tmp) / 'third'; third.mkdir()
            zero.side_effect = None
            consumed['cpuFuel'] = '1'
            with self.assertRaisesRegex(WorkflowError, 'c-stat-missing-http-grant-prevents-guest'):
                stat.cell(client, object(), {}, peer, third, 'missing-grant')

    def test_denied_head_requires_zero_contact_and_the_declared_error(self):
        consumed = {k: '0' for k in ('stateReadBytes', 'stateWriteBytes', 'blobReadBytes',
                    'blobWriteBytes', 'logBytes', 'effectCount', 'childCalls')}
        consumed.update(cpuFuel='1', peakMemoryBytes='1')
        row = {'processReaped': True, 'exitCode': 3, 'decoded': [{'err': 'permission-denied'}],
               'response': {'outcomeKnown': True, 'requestDispatched': True,
                            'data': {'resolvedRevision': 'revision', 'consumption': consumed}}}
        peer = Mock(); peer.url.return_value = 'http://127.0.0.1:1234/conformance/echo'
        peer.observation.return_value = {'openConnections': 0}
        client = SimpleNamespace(deadline=10**12)
        process = SimpleNamespace(owner=SimpleNamespace(exited=lambda: True))
        with tempfile.TemporaryDirectory() as tmp, \
                patch.object(stat.owner, 'selected_revision', return_value='revision'), \
                patch.object(stat.owner, 'start_http_call', return_value=process), \
                patch.object(stat.owner, 'finish_call', return_value=row), \
                patch.object(stat.owner, 'retire', return_value={'physicalOwnersAfter': 0}), \
                patch.object(stat.owner, 'close_call'), patch.object(stat, 'validate'), \
                patch.object(stat, 'delta', return_value={}), patch.object(stat, 'require_zero_contact') as zero:
            first, second, third, fourth = (Path(tmp) / name for name in ('first', 'second', 'third', 'fourth'))
            first.mkdir(); second.mkdir(); third.mkdir(); fourth.mkdir()
            self.assertEqual(stat.cell(client, object(), {}, peer, first, 'denied')['case'], 'denied')
            zero.assert_called_once()
            self.assertEqual(stat.cell(client, object(), {}, peer, fourth, 'range-denied')['case'], 'range-denied')
            self.assertEqual(zero.call_count, 2)
            zero.side_effect = WorkflowError('unexpected-contact')
            with self.assertRaisesRegex(WorkflowError, 'unexpected-contact'):
                stat.cell(client, object(), {}, peer, second, 'denied')
            zero.side_effect = None
            row['decoded'] = [{'err': 'unavailable'}]
            with self.assertRaisesRegex(WorkflowError, 'c-stat-exact-ordinary-result'):
                stat.cell(client, object(), {}, peer, third, 'denied')


if __name__ == '__main__': unittest.main()
