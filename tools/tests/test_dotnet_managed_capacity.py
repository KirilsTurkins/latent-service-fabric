"""Capacity profile boundaries and failure retention; no simulated guest qualification."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools import dotnet_managed_capacity_node as node
from tools.phase2_operator_process import WorkflowError


from tools.tests.test_sdk_scratch_qualification import historical_security_actions


def historical_checkout(value):
    """Authenticate the current action before the exact historical pin inverse."""
    value = historical_security_actions(value)
    prefix = 'KirilsTurkins/lsf-checkout@'
    current = prefix + '842365d0a25bf5a868311e4cb89c908bdcab4bb8'
    previous = prefix + 'c3024dfac542bb46ebccc7829ddf1f95e0be8da9'
    if type(value) is bytes:
        prefix, current, previous = (item.encode('ascii') for item in (prefix, current, previous))
    if type(value) not in (str, bytes) or not value.count(current) or value.count(prefix) != value.count(current):
        raise AssertionError('historical-workflow-exact-current-checkout-required')
    return value.replace(current, previous)


class ManagedCapacityTests(unittest.TestCase):
    def test_manual_selector_restores_entire_original_three_job_workflow(self):
        import hashlib
        from tools.ci_lane_inventory import workflow_model
        from tools.rust_capsule_project import ROOT
        value = workflow_model(historical_checkout((ROOT/'.github/workflows/dotnet-published-http.yml').read_text(encoding='utf8')))
        diagnostic = value['on']['workflow_dispatch']['inputs'].pop('periodic_diagnostic')
        self.assertEqual(diagnostic['type'], 'boolean');self.assertIs(diagnostic['default'], False)
        value['jobs'].pop('periodic-diagnostic')
        for original in value['jobs'].values():
            self.assertTrue(original['if'].endswith(' && !inputs.periodic_diagnostic'))
            original['if'] = original['if'].removesuffix(' && !inputs.periodic_diagnostic')
        selector = value['on']['workflow_dispatch']['inputs'].pop('owner_capacity')
        self.assertEqual(selector['type'], 'boolean');self.assertIs(selector['default'], False)
        job = value['jobs'].pop('owner-capacity')
        self.assertEqual(job['if'], "github.event_name == 'workflow_dispatch' && inputs.owner_capacity")
        expected = {'mixed-content': "github.event_name == 'workflow_dispatch' && inputs.mixed_content",
            'published-http': "github.event_name == 'workflow_dispatch' && inputs.fresh_component && !inputs.mixed_content",
            'exact-component': "(github.event_name != 'workflow_dispatch' || !inputs.fresh_component) && !inputs.mixed_content"}
        self.assertEqual(set(value['jobs']), set(expected))
        for name, previous in expected.items():
            self.assertEqual(value['jobs'][name]['if'], previous+' && !inputs.owner_capacity')
            value['jobs'][name]['if'] = previous
        self.assertEqual(hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest(),
            'f99e0b898d7c2bb8f2b5bc73574fc10ddf8b194b54b42970189dcac61181abf1')
        commands = [step.get('run', '') for step in job['steps']]
        self.assertEqual(sum('tools/qualify_dotnet_managed_capacity.py' in line for line in commands), 1)
        self.assertFalse(any('tools/qualify_dotnet_http_mixed.py' in line for line in commands))
        self.assertEqual(job['timeout-minutes'], 40)

    def test_selected_ceilings_only_narrow_original_queue_and_native_owners(self):
        original = {'tasks': 8, 'executors': 2, 'queuedWork': 8, 'waits': 16,
            'timers': 8, 'results': 8, 'nativeOwners': 8}
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary)/'node.json'
            source = {'providers': {'activationRuntime': {'limits': original}, 'http': {'unchanged': True}},
                'execution': {'maximumWallTimeMillis': 120000}, 'memory': 134217728}
            for native in (0, 1, 2):
                path.write_text(json.dumps(source), encoding='utf8')
                with patch.object(node.base, 'configuration', return_value=path):
                    selected = node.configuration(path.parent, None,
                        type('Peer', (), {'observation': lambda _: {'origins': []}, 'provider_destinations': lambda _: []})(), None, native)
                actual = json.loads(selected.read_text(encoding='utf8'))
                expected = copy.deepcopy(source)
                expected['providers']['activationRuntime']['limits'] = {**node.LIMITS, 'nativeOwners': native}
                self.assertEqual(actual, expected)
            for bad in (True, -1, 3, '1', None):
                with self.subTest(bad=bad), self.assertRaises((WorkflowError, ValueError)):
                    node.configuration(path.parent, None, None, None, bad)

    def test_timer_birth_and_return_sequences_prove_individual_original_instances(self):
        eight = '1:timers:8:1,2,3,4,5,6,7,8:7,6,5,4,3,2,1,0:refused:reused:fresh'
        seven = '1:timers:7:2,3,4,5,6,7,8:7,6,5,4,3,2,1:refused:reused:fresh'
        self.assertEqual(node.timers(eight)['individualTimers'], 8)
        self.assertEqual(node.timers(seven)['individualTimers'], 7)
        for bad in (eight.replace('1,2,3,4,5,6,7,8', '1,2,3,4,5,6,7,7'),
                    eight.replace('7,6,5,4,3,2,1,0', '7,6,6,4,3,2,1,0'),
                    eight.replace(':8:', ':True:'), eight.replace(':refused:', ':accepted:'),
                    eight.replace(':1,2', ':01,2'), eight+':extra'):
            with self.subTest(bad=bad), self.assertRaises((WorkflowError, ValueError)):
                node.timers(bad)

    def row(self):
        return {'processReaped': True, 'exitCode': 0, 'decoded': ['1:'+node.EXPECTED[0]],
            'response': {'outcomeKnown': True, 'category': 'success', 'data': {'resolvedRevision': {'exact': True},
                'consumption': {'outboundRequests': '0', 'cpuFuel': '17', 'peakMemoryBytes': '100'}}}}

    def test_results_bind_original_budget_revision_and_managed_oracle(self):
        row = self.row(); budget = {'cpuFuel': 1000000000, 'memoryBytes': 134217728}
        node.checked(row, 0, {'exact': True}, budget)
        for mutate in (lambda r: r.update(processReaped=False),
                       lambda r: r.update(decoded=['1:tasks:accepted']),
                       lambda r: r['response'].update(outcomeKnown=False),
                       lambda r: r['response']['data'].update(resolvedRevision={}),
                       lambda r: r['response']['data']['consumption'].update(outboundRequests='1'),
                       lambda r: r['response']['data']['consumption'].update(cpuFuel=True)):
            changed = copy.deepcopy(row); mutate(changed)
            with self.assertRaises((WorkflowError, ValueError)):
                node.checked(changed, 0, {'exact': True}, budget)

    def test_zero_native_terminal_never_becomes_typed_exception_or_application_success(self):
        row = self.row(); row.update(exitCode=4, decoded=[])
        row['response'].update(category='platform-failure', error={'code': 'guest-trap'})
        budget = {'cpuFuel': 1000000000, 'memoryBytes': 134217728}
        result = node.checked(row, 7, {'exact': True}, budget, installation_refusal=True)
        self.assertFalse(result['originalManagedExceptionTransported'])
        self.assertFalse(result['diagnosticCauseIndependentlyTyped'])
        for code in ('resource-exhausted', 'permission-denied', 'deadline-exceeded'):
            changed = copy.deepcopy(row); changed['response']['error']['code'] = code
            with self.subTest(code=code), self.assertRaises((WorkflowError, ValueError)):
                node.checked(changed, 7, {'exact': True}, budget, installation_refusal=True)
        with self.assertRaises((WorkflowError, ValueError)):
            node.checked(row, 7, {'exact': True}, budget)

    def test_partial_failure_is_retained_and_cleanup_cannot_replace_primary_exception(self):
        original = ValueError('synthetic public primary')
        class Owner:
            def exited(self): raise original
        class Process:
            owner = Owner()
            def close(self): raise RuntimeError('synthetic cleanup')
        class Client:
            deadline = 10**20
            evidence = Path('unused-control-directory')
        peer = type('Peer', (), {'observation': lambda _: {'requests': []}, 'origin': lambda _: {'host': '127.0.0.1', 'port': 1}})()
        with patch.object(node, 'selected_revision', return_value={}), patch.object(node, 'start_call', return_value=Process()), \
                patch.object(node, 'retain_partial') as retained, patch.object(node, 'write_json'):
            with self.assertRaises(ValueError) as caught:
                node.invoke(Client(), None, {}, peer, None, 0, 'control')
        self.assertIs(caught.exception, original)
        retained.assert_called_once()

    def test_periodic_closed_diagnostic_is_never_a_qualified_capacity_outcome(self):
        budget = {'cpuFuel': 1000000000, 'memoryBytes': 134217728}
        row = self.row(); row['decoded'] = ['1:'+node.EXPECTED[3]]
        node.checked(row, 3, {'exact': True}, budget)
        for value in ('periodic:diagnostic:2:fixture-assertion',
                      'periodic:diagnostic:6:admission-refused',
                      'periodic:diagnostic:7:unknown'):
            failed = copy.deepcopy(row); failed['decoded'] = ['1:'+value]
            with self.subTest(value=value), self.assertRaises(WorkflowError):
                node.checked(failed, 3, {'exact': True}, budget)


if __name__ == '__main__':
    unittest.main()
