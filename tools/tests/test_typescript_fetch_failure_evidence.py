"""Orchestration and evidence failures cannot qualify a failed signed invocation."""
from contextlib import ExitStack, nullcontext
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

from tools import qualify_typescript_fetch_runtime as fetch
from tools.phase2_operator_process import WorkflowError


class FetchFailureEvidenceTests(unittest.TestCase):
    def observation(self, active='0'):
        return {'inventory': {'topology': {'entries': [
            {'name': 'invocation-cleanup-slots', 'activeCount': active}]}}}

    def client(self, **changes):
        usage = {'unavailable': False, 'counters': {name: '0' for name in fetch.ACTIVE_COUNTERS}}
        usage.update(changes)
        return Mock(**{'call.return_value': {'data': {'nodeUsage': usage}}})

    def test_rejected_cleanup_sample_is_retained_before_validation(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            with patch.object(fetch, 'sample', return_value=self.observation(active='1')):
                with self.assertRaisesRegex(WorkflowError, 'fetch-runtime-cleanup-slots'):
                    fetch.retire(self.client(), object(), {'name': 'test'}, output, 'good')
            self.assertEqual(json.loads((output/'after-good.json').read_text()), self.observation(active='1'))

    def test_unavailable_missing_and_live_host_counters_are_retained_and_rejected(self):
        for usage in ({'unavailable': True}, {'counters': {}},
                      {'counters': {name: '1' for name in fetch.ACTIVE_COUNTERS}}):
            with self.subTest(usage=usage), tempfile.TemporaryDirectory() as directory:
                output = Path(directory)
                with patch.object(fetch, 'sample', return_value=self.observation()):
                    with self.assertRaisesRegex(WorkflowError, 'fetch-runtime-physical-owners'):
                        fetch.retire(self.client(**usage), object(), {'name': 'test'}, output, 'pending')
                retained = json.loads((output/'after-pending-usage.json').read_text())
                for key, value in usage.items():
                    self.assertEqual(retained[key], value)

    def test_execute_observes_failed_case_before_node_close_and_counts_only_completed_cases(self):
        # These are orchestration doubles, not a native node or signed guest.
        for failed_boundary in ('invoke', 'cleanup'):
            with self.subTest(boundary=failed_boundary), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                output = root/'observed'
                events = []
                live = {'node': True}
                node = Mock()
                def close_node():
                    live['node'] = False
                    events.append('node-close')
                node.close.side_effect = close_node
                peer = Mock()
                peer.line.return_value = {'origins': {'primary': {'host': '127.0.0.1', 'port': 12345}}}
                client = self.client()
                client.deadline = time.monotonic() + 300
                def control(*args, **kwargs):
                    if args[0] == 'release':
                        return {'data': {'operation': {'publication': {'id': 'pub'}}}}
                    if args[0] == 'node':
                        self.assertTrue(live['node'])
                        events.append('failure-inventory')
                        return {'category': 'success', 'outcomeKnown': True, 'data': {'inventory': {'active': 1}}}
                    return dict(client.call.return_value, category='success', outcomeKnown=True)
                client.call.side_effect = control
                def invoke(_client, _target, _fixture, _operation, _args, name):
                    events.append(name)
                    denied = name in ('fetch-runtime-denied', 'fetch-http-denied')
                    trapped = name == 'fetch-request-ready' and failed_boundary == 'invoke'
                    value = 'entered' if name == 'fetch-entry' else 'request-ready'
                    return {'exitCode': 4 if denied or trapped else 0,
                        'decoded': None if denied or trapped else [value], 'processReaped': True,
                        'response': {'outcomeKnown': True,
                            'error': {'code': 'permission-denied' if denied else 'guest-trap'} if denied or trapped else None,
                            'data': {'consumption': {'cpuFuel': '0' if denied else '100',
                                'outboundRequests': 0, 'childCalls': 0, 'effectCount': 0}}}}
                def observe(_client, _probe, name, _count):
                    self.assertTrue(live['node'])
                    events.append(name)
                    active = '1' if name == 'after-request-ready' and failed_boundary == 'cleanup' else '0'
                    return self.observation(active)
                replacements = {
                    'build_evidence': Mock(return_value={'component': {'sha256': 'test-double'}}),
                    'build_environment': Mock(return_value={}),
                    'run_bounded_result': Mock(return_value=Mock(returncode=0)),
                    'owned_cancellation': Mock(side_effect=lambda: nullcontext(object())),
                    'RecordingClient': Mock(return_value=client), 'Process': Mock(return_value=peer),
                    'configuration': Mock(return_value=root/'configuration.json'),
                    'file_identity': Mock(return_value={'sha256': 'test-double', 'bytes': 1}),
                    'connect': Mock(return_value=node), 'Probe': Mock(return_value=object()),
                    'deploy': Mock(return_value={'name': 'deployment', 'generation': '1'}),
                    'grants': Mock(return_value=([], [])), 'call': invoke, 'sample': observe,
                }
                with ExitStack() as patches:
                    for name, replacement in replacements.items():
                        patches.enter_context(patch.object(fetch, name, replacement))
                    reason = 'typed-result' if failed_boundary == 'invoke' else 'cleanup-slots'
                    with self.assertRaisesRegex(WorkflowError, 'fetch-runtime-'+reason):
                        fetch.execute(root/'artifact', {name: root/name for name in fetch.PRODUCTS}, output)
                self.assertLess(events.index('fetch-request-ready'), events.index('failure-inventory'))
                self.assertLess(events.index('failure-inventory'), events.index('node-close'))
                failed = json.loads((output/'FAILED.json').read_text())
                self.assertEqual(failed['status'], 'failed')
                self.assertEqual(failed['stage'], 'request-ready')
                self.assertEqual(failed['cases'], ['entry'])
                self.assertFalse(failed['fullTicketQualification'])
                self.assertFalse((output/'qualification.json').exists())
                self.assertTrue((output/'after-failed-request-ready.json').is_file())
                if failed_boundary == 'cleanup':
                    self.assertTrue((output/'after-request-ready.json').is_file())

    def test_top_level_failure_record_cannot_mask_original_failure(self):
        original = WorkflowError('original-build-failure')
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(fetch, 'build_evidence', side_effect=original), \
                    patch.object(fetch, 'write_json', side_effect=OSError('disk-full')):
                with self.assertRaises(WorkflowError) as caught:
                    fetch.execute(Path(directory)/'artifact', {}, Path(directory)/'observed')
            self.assertIs(caught.exception, original)
            self.assertIn('fetch-runtime-failure-evidence:OSError', original.__notes__)

    def test_qualify_failure_record_preserves_original_failure_and_cancellation(self):
        for original in (WorkflowError('original-capture-failure'), KeyboardInterrupt()):
            with self.subTest(error=type(original).__name__), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                with patch.object(fetch, 'native_inputs', return_value=({}, {})), \
                        patch.object(fetch, 'project', side_effect=original), \
                        patch.object(fetch, 'write_json', side_effect=OSError('disk-full')):
                    with self.assertRaises(type(original)) as caught:
                        fetch.qualify(root/'output', root/'tools', root/'engine', root/'splicer')
                self.assertIs(caught.exception, original)
                self.assertIn('fetch-runtime-failure-evidence:OSError', original.__notes__)


