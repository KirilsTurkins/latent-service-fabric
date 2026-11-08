"""Local qualification-harness controls; no guest or provider is executed."""
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
            self.assertEqual(stat.CASES, ('normal', 'denied', 'not-found', 'fresh',
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
            self.assertEqual(rules[0]['resources']['paths'], ['/conformance/json', '/conformance/status/404'])
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
