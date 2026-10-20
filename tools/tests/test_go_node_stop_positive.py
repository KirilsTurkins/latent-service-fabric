"""Native accepted waits, live original owners and unchanged poll bounds."""
from contextlib import nullcontext
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from tools import go_node_stop_positive as positive
from tools import go_node_stop_timer_observer as observer
from tools import qualify_go_node_stop as reference
from tools.tests.test_go_node_stop import inventory, provider_usage


def records(mode='pending'):
    events = [('start-accepted', 2, 0, 1), ('next-entered', 2, 1, 1)]
    if mode == 'pending':
        events += [('start-accepted', 3, 0, 1), ('next-entered', 3, 1, 1),
                   ('start-accepted', 3, 1, 2), ('next-entered', 3, 2, 2)]
    else:
        # Existing accepted children can enter their wait while the root drains.
        # The native close hook need not occur after the child's timer hook.
        events += [('root-close', 2, 0, 0), ('start-accepted', 2, 0, 1),
                   ('next-entered', 2, 1, 1)]
    return b''.join(observer.PREFIX + ('|%s|%s|%d|%d|%d|%d\n' %
        (mode, event, index, tasks, waits, timers)).encode()
        for index, (event, tasks, waits, timers) in enumerate(events, 1))


def barrier(raw=None, mode='pending', owners=None, usage=None):
    return positive.barrier(inventory() if owners is None else owners,
        records(mode) if raw is None else raw, 'node-stop-' + mode, mode,
        provider_usage=provider_usage() if usage is None else usage)


class GoNodeStopPositive(unittest.TestCase):
    def test_actual_single_earliest_body_wait_requires_admission_order_and_live_timer_owners(self):
        # Retained51190: the initializer retired without entering timer-next;
        # the pinned Go dispatcher waits on its earliest remaining timer.
        rows = [('start-accepted', 10, 0, 1), ('start-accepted', 11, 0, 1),
                ('start-accepted', 11, 0, 2), ('next-entered', 11, 1, 2)]
        raw = b''.join(observer.PREFIX + ('|pending|%s|%d|%d|%d|%d\n' %
            (event, index, tasks, waits, timers)).encode()
            for index, (event, tasks, waits, timers) in enumerate(rows, 1))
        value = barrier(raw)
        self.assertIsNotNone(value)
        self.assertEqual((value['acceptedTimerStarts'], value['enteredTimerWaits']), (3, 1))
        self.assertEqual(value['lastEnteredTimerOwners']['sequence'], 4)
        for invalid in (b'\n'.join(raw.splitlines()[:3])+b'\n',
                        raw.replace(b'next-entered|4|11|1|2', b'next-entered|4|11|0|2'),
                        raw.replace(b'next-entered|4|11|1|2', b'next-entered|4|11|1|1')):
            with self.subTest(invalid=invalid):
                self.assertIsNone(barrier(invalid))
        initializer_only_wait = records().splitlines()[:2]
        for index, (_event, tasks, waits, timers) in enumerate(rows[1:3], 3):
            initializer_only_wait.append(observer.PREFIX + ('|pending|start-accepted|%d|%d|%d|%d' %
                (index, tasks, waits, timers)).encode())
        self.assertIsNone(barrier(b'\n'.join(initializer_only_wait)+b'\n'))

    def test_actual_next_entered_and_current_timer_owners_replace_audit_completion_inference(self):
        value = barrier()
        self.assertEqual((value['acceptedTimerStarts'], value['enteredTimerWaits']), (3, 3))
        self.assertEqual(value['lastEnteredTimerOwners']['timers'], 2)
        self.assertFalse(value['auditCompletionUsedAsTimerSuccess'])
        self.assertFalse(value['actualNodeSignalSent'])
        self.assertFalse(value['rootCloseObserved'])
        self.assertEqual(value['retainedProviderUsage'], {'tenantSessions': 1, 'tenantCalls': 1, 'nodeCalls': 1})

    def test_returned_root_requires_real_close_and_live_child_wait_in_either_valid_order(self):
        raw = records('drain')
        self.assertTrue(barrier(raw, 'drain')['rootCloseObserved'])
        missing_close = []
        for line in raw.splitlines():
            if b'root-close' in line:
                continue
            fields = line.split(b'|')
            fields[3] = str(len(missing_close) + 1).encode()
            missing_close.append(b'|'.join(fields))
        self.assertIsNone(barrier(b'\n'.join(missing_close) + b'\n', 'drain'))
        self.assertIsNone(barrier(b'\n'.join(line for line in raw.splitlines() if b'next-entered|5' not in line) + b'\n', 'drain'))

    def test_missing_initializer_only_and_unrelated_audit_completion_never_supply_body_waits(self):
        init = b'\n'.join(records().splitlines()[:2]) + b'\n'
        for raw in (b'', init, init + b'\nHOST_COMPLETED timer-start\n',
                    b'PHASE2_AUDIT_EVENT_KIND_CAPABILITY_GRANT_ALLOWED timer-next\n'):
            with self.subTest(raw=raw):
                self.assertIsNone(barrier(raw))
        raw = records().replace(b'|3|2|2\n', b'|3|0|2\n')
        self.assertIsNone(barrier(raw))
        self.assertIsNone(barrier(records().replace(b'|3|2|2\n', b'|3|2|1\n')))

    def test_invalid_overflow_private_foreign_and_closed_pending_evidence_fail_closed(self):
        for raw in (records() + observer.PREFIX + b'|overflow\n',
                    records() + observer.PREFIX + b'|pending|private|7|3|2|2\n',
                    records().replace(b'|pending|', b'|drain|'),
                    records() + observer.PREFIX + b'|pending|root-close|7|3|2|2\n'):
            with self.subTest(raw=raw), self.assertRaisesRegex(RuntimeError, 'Go-node-stop-positive-'):
                barrier(raw)
        with self.assertRaisesRegex(RuntimeError, 'exact-public-activation'):
            positive.barrier(inventory(), records(), 'foreign', 'pending', provider_usage=provider_usage())

    def test_live_pipe_fragment_waits_for_the_same_complete_record_but_missing_sequences_fail_closed(self):
        raw = records()
        for selected in (raw[:-1], raw + observer.PREFIX[:10]):
            with self.subTest(selected=selected):
                self.assertTrue(positive.capture(selected)['partialRecord'])
                self.assertIsNone(barrier(selected))
        self.assertIsNotNone(barrier(raw))
        missing = b'\n'.join(line for line in raw.splitlines() if b'next-entered|2|' not in line) + b'\n'
        with self.assertRaisesRegex(RuntimeError, 'lost-native-record'):
            barrier(missing)
        with self.assertRaisesRegex(RuntimeError, 'native-record-bound'):
            barrier(raw + observer.PREFIX + b'x' * 129)

    def test_timer_events_alone_do_not_replace_current_store_provider_and_original_queue_ownership(self):
        for name in positive.oracle.LIVE_ROWS:
            owners = inventory()
            next(row for row in owners['topology']['entries'] if row['name'] == name)['activeCount'] = '0'
            with self.subTest(owner=name):
                self.assertIsNone(barrier(owners=owners))
        for scope, counter in (('tenantUsage', 'sessions'), ('tenantUsage', 'calls'), ('nodeUsage', 'broker_calls')):
            usage = provider_usage()
            usage[scope]['counters'][counter] = '0'
            with self.subTest(scope=scope, counter=counter):
                self.assertIsNone(barrier(usage=usage))
        owners = inventory();owners['queueDepth'] = 1
        with self.assertRaisesRegex(RuntimeError, 'no-hidden-root-queue'):
            barrier(owners=owners)

    def test_wait_reads_the_native_source_and_never_queries_optional_audit_or_extends_deadline(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            calls = []
            def control(*args):
                calls.append(args)
                if args[0] == 'node':
                    return {'data': {'inventory': inventory()}}
                self.assertEqual(args[0], 'capability')
                return {'data': {**provider_usage(), 'nextPageToken': None}}
            client = SimpleNamespace(deadline=100.0, evidence=root, call=control)
            node = SimpleNamespace(drain=lambda: None, buffers=[b'', records()])
            pending = SimpleNamespace(owner=SimpleNamespace(exited=lambda: False), authoring_activation='node-stop-pending')
            with patch.object(positive.time, 'monotonic', return_value=10.0), patch.object(positive.time, 'sleep') as sleep:
                value = positive.wait_live(client, node, pending, 'pending')
            self.assertEqual(value['attempts'], 1)
            self.assertEqual(client.deadline, 100.0)
            self.assertEqual(len(calls), 2)
            sleep.assert_not_called()
            self.assertTrue((root / 'positive-timer-1.json').is_file())
            self.assertEqual(value['timerObserver']['records'], observer.observe(records())['records'])

    def test_absent_events_exhaust_only_original_sixteen_attempts_and_restore_original_deadline(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            calls = []
            def control(*args):
                calls.append(args)
                return {'data': {'inventory': inventory()}} if args[0] == 'node' else {
                    'data': {**provider_usage(), 'nextPageToken': None}}
            client = SimpleNamespace(deadline=15.0, evidence=root, call=control)
            node = SimpleNamespace(drain=lambda: None, buffers=[b'', b''])
            pending = SimpleNamespace(owner=SimpleNamespace(exited=lambda: False), authoring_activation='node-stop-pending')
            with patch.object(positive.time, 'monotonic', return_value=10.0), patch.object(positive.time, 'sleep') as sleep, \
                    self.assertRaisesRegex(RuntimeError, 'live-barrier-attempts'):
                positive.wait_live(client, node, pending, 'pending')
            self.assertEqual(client.deadline, 15.0)
            self.assertEqual(len(calls), 32)
            self.assertEqual(len(list(root.glob('positive-timer-*.json'))), 16)
            self.assertEqual(sleep.call_args_list, [((0.01,),)] * 16)

    def test_completed_cli_and_expired_original_deadline_cannot_authorize_signal(self):
        client = SimpleNamespace(deadline=9.0)
        pending = SimpleNamespace(owner=SimpleNamespace(exited=lambda: True))
        with patch.object(positive.time, 'monotonic', return_value=10.0), \
                self.assertRaisesRegex(RuntimeError, 'live-barrier-deadline'):
            positive.wait_live(client, object(), pending, 'pending')
        self.assertEqual(client.deadline, 9.0)
        client.deadline = 100.0
        with patch.object(positive.time, 'monotonic', return_value=10.0), \
                self.assertRaisesRegex(RuntimeError, 'guest-completed-before-signal'):
            positive.wait_live(client, object(), pending, 'pending')
        self.assertEqual(client.deadline, 100.0)

    def test_only_explicit_positive_programme_selection_enables_the_existing_native_hook(self):
        for selected in (False, True):
            with self.subTest(selected=selected), tempfile.TemporaryDirectory() as directory:
                client = SimpleNamespace(environment={})
                def connect(actual, *args, **kwargs):
                    self.assertIs(actual, client)
                    self.assertEqual(actual.environment, {observer.ENVIRONMENT: '1'} if selected else {})
                    raise RuntimeError('controlled-before-node-start')
                with patch.object(reference, 'RecordingClient', return_value=client), \
                        patch.object(reference, 'owned_cancellation', return_value=nullcontext(None)), \
                        patch.object(reference, 'configuration', return_value=Path(directory) / 'node.json'), \
                        patch.object(reference, 'connect', side_effect=connect), \
                        self.assertRaisesRegex(RuntimeError, 'controlled-before-node-start'):
                    reference.programme({'latent': Path('latent'), 'latentd': Path('latentd')},
                        Path(directory), Path(directory), positive_timers=selected)
        for selected in (1, None, 'true'):
            with self.subTest(selected=selected), self.assertRaisesRegex(RuntimeError, 'positive-timer-selection'):
                reference.programme({}, Path('.'), Path('.'), positive_timers=selected)


if __name__ == '__main__':
    unittest.main()
