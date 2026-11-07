"""Local qualification-harness controls; no guest or provider is executed."""
import tempfile
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
            self.assertEqual(stat.CASES, ('normal', 'denied', 'not-found', 'fresh'))

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
            self.assertEqual(rules[1]['resources']['paths'], ['/conformance/echo'])
            self.assertTrue(all(row['resources']['origins'] == [origin] for row in rules))
        node.startup_record['providers'][0]['profile'] = 'wrong'
        with patch.object(stat.owner, 'install', return_value=[]), patch.object(stat, 'policy') as policy:
            with self.assertRaisesRegex(WorkflowError, 'c-stat-installed-http-provider'):
                stat.install(object(), node, target, origin)
            policy.assert_not_called()

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
            first, second, third = (Path(tmp) / name for name in ('first', 'second', 'third'))
            first.mkdir(); second.mkdir(); third.mkdir()
            self.assertEqual(stat.cell(client, object(), {}, peer, first, 'denied')['case'], 'denied')
            zero.assert_called_once()
            zero.side_effect = WorkflowError('unexpected-contact')
            with self.assertRaisesRegex(WorkflowError, 'unexpected-contact'):
                stat.cell(client, object(), {}, peer, second, 'denied')
            zero.side_effect = None
            row['decoded'] = [{'err': 'unavailable'}]
            with self.assertRaisesRegex(WorkflowError, 'c-stat-exact-ordinary-result'):
                stat.cell(client, object(), {}, peer, third, 'denied')


if __name__ == '__main__': unittest.main()
