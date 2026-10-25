"""Controller/deadline argument units with a fake client; no process/runtime qualification."""
import unittest
from unittest.mock import patch

from tools import guest_compatibility as compatibility
from tools import guest_compatibility_context as context
from tools import guest_compatibility_outcomes as outcomes
from tools.dev_workflow import node_scenarios
from tools.dev_workflow.common import digest, encode


def collector(names):
    report = compatibility.report('typescript', digest(b'captured source'), digest(b'component'),
                                  'lsf-host-abi-phase3-v5', [], [])
    captured = outcomes.Capture(digest(b'frontend'), report['componentDigest'],
                               context.create(report, [], {'state': 'absent'}))
    revision = {'releaseDigest': report['componentDigest']}
    for name in names:
        captured.observe(name, {'category': 'platform-failure', 'outcomeKnown': True,
            'error': {'code': 'guest-trap', 'details': []}, 'data': {'resolvedRevision': revision}},
            True, expected_revision=revision)
    return captured


class Client:
    def __init__(self, *, fail=False):
        self.calls = []
        self.fail = fail

    def call(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        if self.fail:
            raise RuntimeError('private-host-error-must-not-escape')
        return {'category': 'success', 'outcomeKnown': True, 'data': {'schemaVersion': 1,
            'historyAvailable': True, 'nodes': [{'activationId': args[4],
            'targetService': 'examples/service', 'diagnosticIsTerminal': False,
            'diagnostic': {'schemaVersion': 1, 'stage': 5, 'reason': 17,
                'configuredBound': '16', 'calculatedRequirement': '17'}}]}}


class ResourceObservationOwner(unittest.TestCase):
    def test_original_absolute_deadline_caps_the_real_call_and_prevents_late_second_query(self):
        captured, client = collector(('first', 'second')), Client()
        selectors = [('first', 'original-first', 'examples/service'),
                     ('second', 'original-second', 'examples/service')]
        with patch.object(node_scenarios.time, 'monotonic', side_effect=(10, 11)):
            node_scenarios._collect_node_observations(captured, client, selectors, 16)
        self.assertEqual(client.calls, [(('--rpc-timeout-ms', '1000', 'activation', 'tree',
            'original-first', '--page-size', '1'), {'timeout': 1})])
        rows = outcomes.read(encode(captured.snapshot()))['cases']
        self.assertEqual(rows[0]['nodeDiagnostic']['resourceDimension'], 'tasks')
        self.assertEqual(rows[1]['nodeDiagnostic'], {'state': 'unavailable', 'reason': 'observation-deadline'})
        self.assertTrue(all(row['cause'] == 'unknown' for row in rows))

    def test_actual_client_failure_is_not_retried_and_cannot_replace_original_trap(self):
        captured, client = collector(('failed',)), Client(fail=True)
        with patch.object(node_scenarios.time, 'monotonic', return_value=10):
            node_scenarios._collect_node_observations(captured, client,
                [('failed', 'original-failed', 'examples/service')], 20)
        self.assertEqual(len(client.calls), 1)
        row = captured.snapshot()['cases'][0]
        self.assertEqual(row['errorCode'], 'guest-trap')
        self.assertEqual(row['nodeDiagnostic'], {'state': 'unavailable', 'reason': 'history-unavailable'})
        self.assertNotIn('private-host-error', encode(captured.snapshot()).decode())

    def test_unissued_or_option_like_identity_and_overbound_selector_refuse_before_rpc(self):
        captured, client = collector(('invalid',)), Client()
        with patch.object(node_scenarios.time, 'monotonic', return_value=10):
            node_scenarios._collect_node_observations(captured, client,
                [('invalid', '--all-tenants', 'examples/service')], 20)
        self.assertEqual(client.calls, [])
        self.assertEqual(captured.snapshot()['cases'][0]['nodeDiagnostic']['reason'],
                         'original-identifier-unavailable')
        with self.assertRaises(ValueError):
            node_scenarios._collect_node_observations(captured, client,
                [('invalid', 'original', 'examples/service')] * 9, 20)
        self.assertEqual(client.calls, [])


if __name__ == '__main__':
    unittest.main()
