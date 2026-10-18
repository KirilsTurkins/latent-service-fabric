"""Finite read observers retain unknown replies and never supply mutation proof."""
import copy
from contextlib import nullcontext
from types import SimpleNamespace
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from tools.java_transaction_qualification import diagnostic_campaign as fault, pending_controls as controls, read_observer
from tools.java_transaction_qualification.evidence import Evidence, RecordingClient, encoded
from tools.tests.java_read_observer_fixtures import Clock, busy, collector, pending, pending_claim, reply
from tools.tests.test_java_pending_recovery import snapshot
from tools.tests.test_java_transaction_fault_campaign import terminal


def inspected():
    return reply('dispatcher inspect', {'dispatcher': snapshot(), 'auditAcknowledgement': {
        'status': 'AUDIT_ACK_STATUS_DURABLE', 'attemptSequence': '1'}})


class ReadBackpressureControls(unittest.TestCase):
    def test_busy_lookup_consumes_original_attempt_then_preserves_unknown_same_claim(self):
        clock, calls = Clock(), []
        claimed = pending_claim()
        replies = iter([busy('transaction lookup'), reply('transaction lookup', {'command': claimed}, outcome=False)])
        def call(*args, **kwargs):
            calls.append((args, kwargs))
            return next(replies)
        observed = collector(fault, call, clock)
        with clock.installed(fault), patch.object(fault.lifecycle, 'as_user', return_value=nullcontext()):
            self.assertIs(observed.original_attempt(pending(), 'original-key', clock.now + 10), claimed)
        self.assertEqual(len(calls), 2)
        self.assertEqual(clock.sleeps, [.05])
        self.assertTrue(all(args[:2] == ('transaction', 'lookup') and args[-2:] == ('--client-key', 'original-key')
                            and kwargs['codes'] == (0, 5, 6) and 0 < kwargs['timeout'] <= 10 for args, kwargs in calls))
        self.assertFalse(claimed['metadataDurable'])
        self.assertEqual(claimed['outcome'], 'COMMAND_OUTCOME_RECOVERY_REQUIRED')
        self.assertTrue(all(claimed[name] is None for name in ('commit', 'provenAbort', 'retainedResult')))

    def test_busy_dispatcher_reads_keep_original_cutoff_and_require_actual_audited_snapshot(self):
        clock = Clock()
        call = Mock(side_effect=[busy('dispatcher inspect'), inspected()])
        client = SimpleNamespace(call=call, deadline=clock.now + 1000)
        with clock.installed(controls):
            self.assertEqual(controls.inspect_dispatcher(client), snapshot())
        self.assertEqual(call.call_count, 2)
        self.assertEqual(clock.sleeps, [.05])
        self.assertEqual(call.call_args_list[0].kwargs['timeout'], 25.)
        self.assertAlmostEqual(call.call_args_list[1].kwargs['timeout'], 24.95)

    def test_eight_busy_reads_exhaust_without_claim_or_pause_cancel_or_replay(self):
        for name in ('transaction lookup', 'dispatcher inspect'):
            clock = Clock()
            call = Mock(return_value=busy(name))
            with self.subTest(name=name), clock.installed(fault), \
                    patch.object(fault.lifecycle, 'as_user', return_value=nullcontext()), self.assertRaises(ValueError):
                if name == 'transaction lookup':
                    collector(fault, call, clock).original_attempt(pending(), 'original-key', clock.now + 10)
                else:
                    controls.control_dispatcher(SimpleNamespace(call=call, deadline=clock.now + 1000), 'pause', 'original-pause')
            self.assertEqual(call.call_count, 8)
            self.assertTrue(all(row.args[:2] == tuple(name.split()) for row in call.call_args_list))

    def test_expired_cutoffs_make_no_call_and_late_success_cannot_extend_time(self):
        clock = Clock()
        call = Mock(return_value=inspected())
        client = SimpleNamespace(call=call, deadline=clock.now)
        with clock.installed(controls), self.assertRaises(ValueError):
            controls.inspect_dispatcher(client)
        call.assert_not_called()
        def late(*args, **kwargs):
            clock.now += 25
            return inspected()
        client.call, client.deadline = Mock(side_effect=late), clock.now + 1000
        with clock.installed(controls), self.assertRaises(ValueError):
            controls.inspect_dispatcher(client)
        self.assertEqual(client.call.call_count, 1)

    def test_drain_passes_its_original_ten_second_cutoff_through_busy_inspection(self):
        clock = Clock()
        call = Mock(side_effect=[busy('dispatcher inspect'), inspected()])
        client = SimpleNamespace(call=call, deadline=clock.now + 1000)
        with clock.installed(controls):
            self.assertEqual(controls.drained_dispatcher(client), snapshot())
        self.assertEqual(call.call_args_list[0].kwargs['timeout'], 10.)
        self.assertAlmostEqual(call.call_args_list[1].kwargs['timeout'], 9.95)

    def test_busy_schema_dispatched_unknown_code_and_empty_data_are_all_closed(self):
        changes = [('schemaVersion', 'future'), ('category', 'future'), ('command', 'dispatcher pause'),
            ('requestDispatched', False), ('requestDispatched', 1), ('outcomeKnown', True),
            ('outcomeKnown', 0), ('data', {'receipt': {}}), ('extra', False)]
        for field, changed in changes:
            value = busy('dispatcher inspect')
            value[field] = changed
            self.fatal_dispatcher(value)
        for field, changed in [('code', 'resource-exhausted'), ('grpcCode', 'unavailable'),
                ('grpcCode', 'permission-denied'), ('message', ''), ('retryable', True), ('details', [])]:
            value = busy('dispatcher inspect')
            value['error'][field] = changed
            self.fatal_dispatcher(value)

    def fatal_dispatcher(self, value):
        clock = Clock()
        call = Mock(return_value=value)
        client = SimpleNamespace(call=call, deadline=clock.now + 1000)
        with clock.installed(controls), self.assertRaises(ValueError):
            controls.control_dispatcher(client, 'pause', 'original-pause')
        self.assertEqual(call.call_count, 1)
        self.assertEqual(call.call_args.args[:2], ('dispatcher', 'inspect'))

    def test_revocation_other_rpc_errors_and_missing_audit_are_fatal_before_pause(self):
        value = busy('dispatcher inspect')
        value['error']['grpcCode'] = 'permission-denied'
        self.fatal_dispatcher(value)
        value = inspected()
        value['data']['auditAcknowledgement'] = None
        self.fatal_dispatcher(value)
        value = inspected()
        value['category'] = 'future'
        self.fatal_dispatcher(value)

    def test_pending_lookup_rejects_terminal_substitution_missing_source_and_wrong_attempt(self):
        for field, changed in [('outcome', 'COMMAND_OUTCOME_IN_PROGRESS'), ('outcome', 'COMMAND_OUTCOME_ABORTED'),
                ('metadataDurable', True), ('applicationStateCommitted', True), ('source', None),
                ('attemptId', '2'), ('attemptId', '01'), ('retainedResult', {}), ('commit', {}),
                ('provenAbort', {}), ('cleanupFailure', {}), ('commandId', 'not-original')]:
            claimed = pending_claim()
            claimed[field] = changed
            self.fatal_lookup(reply('transaction lookup', {'command': claimed}, outcome=False))
        for changed in ('wrong-key', None):
            claimed = pending_claim()
            claimed['key']['clientKey'] = changed
            self.fatal_lookup(reply('transaction lookup', {'command': claimed}, outcome=False))
        for changed in ('caller/bob', 'shared-scope', 'recovery:sha256:' + 'f' * 64):
            claimed = pending_claim()
            claimed['key']['recoveryScope'] = changed
            self.fatal_lookup(reply('transaction lookup', {'command': claimed}, outcome=False))
        for repeated in (['1' * 64] * 3, ['1' * 64, '4' * 64, '4' * 64]):
            claimed = pending_claim()
            claimed['retention']['requiredRecordIds'] = repeated
            self.fatal_lookup(reply('transaction lookup', {'command': claimed}, outcome=False))
        value = reply('transaction lookup', {'command': pending_claim()}, outcome=False)
        value['outcomeKnown'] = True
        self.fatal_lookup(value)

    def fatal_lookup(self, value):
        clock = Clock()
        call = Mock(return_value=value)
        observed = collector(fault, call, clock)
        with clock.installed(fault), patch.object(fault.lifecycle, 'as_user', return_value=nullcontext()), \
                self.assertRaises(ValueError):
            observed.original_attempt(pending(), 'original-key', clock.now + 10)
        self.assertEqual(call.call_count, 1)
        self.assertEqual(call.call_args.args[:2], ('transaction', 'lookup'))

    def test_successful_pending_read_is_not_staging_or_cancellation_authority(self):
        clock = Clock()
        call = Mock(return_value=reply('transaction lookup', {'command': pending_claim()}, outcome=False))
        observed = collector(fault, call, clock)
        observed.live_staging = Mock(side_effect=ValueError('actual-staging-missing'))
        with clock.installed(fault), patch.object(fault, 'roots', return_value={'original-root'}), \
                patch.object(fault.lifecycle, 'as_user', return_value=nullcontext()), self.assertRaisesRegex(ValueError, 'staging-missing'):
            observed.cancel(pending(), set(), 'original-key')
        observed.live_staging.assert_called_once()
        self.assertEqual(call.call_count, 1)
        self.assertEqual(call.call_args.args[:2], ('transaction', 'lookup'))

    def test_global_cli_bound_still_refuses_before_process_creation(self):
        clock = Clock()
        client = RecordingClient.__new__(RecordingClient)
        client.cancellation, client.calls, client.deadline = Mock(), 256, clock.now + 1000
        with clock.installed(fault), patch('tools.java_transaction_qualification.evidence.Process') as process, \
                self.assertRaisesRegex(ValueError, 'original-cli-campaign-bound'):
            client.call('dispatcher', 'inspect', '--scope', 'node', codes=(0, 5))
        process.assert_not_called()

    def test_deadline_crossed_by_node_drain_cannot_spawn_an_observer_process(self):
        clock = Clock()
        client = RecordingClient.__new__(RecordingClient)
        client.cancellation, client.calls, client.deadline = Mock(), 0, clock.now + 1000
        client.node = SimpleNamespace(drain=lambda: clock.sleep(1))
        with clock.installed(fault), patch('tools.java_transaction_qualification.evidence.Process') as process, \
                self.assertRaisesRegex(ValueError, 'original-cli-campaign-bound'):
            client.call('dispatcher', 'inspect', '--scope', 'node', codes=(0, 5), cutoff=clock.now + .5)
        process.assert_not_called()
        self.assertEqual(client.calls, 0)

    def test_busy_classifier_cannot_be_applied_to_a_mutation_or_receipt_operation(self):
        for command in ('dispatcher pause', 'dispatcher resume', 'dispatcher operation', 'transaction cancel', 'transaction effect'):
            with self.subTest(command=command), self.assertRaisesRegex(ValueError, 'read-only-operation'):
                read_observer.kind(busy(command), command)

    def test_original_lookup_deadline_cannot_accept_a_late_descriptive_claim(self):
        clock = Clock()
        def late(*args, **kwargs):
            clock.sleep(10)
            return reply('transaction lookup', {'command': pending_claim()}, outcome=False)
        call = Mock(side_effect=late)
        observed = collector(fault, call, clock)
        with clock.installed(fault), patch.object(fault.lifecycle, 'as_user', return_value=nullcontext()), \
                self.assertRaisesRegex(ValueError, 'within-same-cutoff'):
            observed.original_attempt(pending(), 'original-key', clock.now + 10)
        self.assertEqual(call.call_count, 1)

    def test_original_mutation_and_recovery_receipt_are_never_retried_on_busy(self):
        clock = Clock()
        call = Mock(side_effect=[inspected(), ValueError('original-mutating-rpc-refused')])
        client = SimpleNamespace(call=call, deadline=clock.now + 1000)
        with clock.installed(controls), self.assertRaisesRegex(ValueError, 'mutating-rpc'):
            controls.control_dispatcher(client, 'pause', 'original-pause')
        self.assertEqual([row.args[:2] for row in call.call_args_list], [('dispatcher', 'inspect'), ('dispatcher', 'pause')])
        self.assertEqual(call.call_args_list[-1].kwargs, {})
        observed = collector(fault, Mock(side_effect=[
            reply('transaction lookup', {'command': pending_claim()}, outcome=False),
            ValueError('original-cancel-rpc-refused')]), clock)
        observed.live_staging = Mock(return_value=terminal('cancel')[1]['transactionStaging'])
        with clock.installed(fault), patch.object(fault, 'roots', return_value={'original-root'}), \
                patch.object(fault.lifecycle, 'as_user', return_value=nullcontext()), self.assertRaisesRegex(ValueError, 'cancel-rpc'):
            observed.cancel(pending(), set(), 'original-key')
        self.assertEqual([row.args[:2] for row in observed.client.call.call_args_list],
                         [('transaction', 'lookup'), ('transaction', 'cancel')])
        self.assertEqual(observed.client.call.call_args_list[-1].kwargs, {})

    def test_current_pending_transaction_link_rejects_stale_witness_and_counter_only_staging(self):
        _, node = terminal('cancel')
        node['terminalState'] = None
        claimed = pending_claim()
        self.assertEqual(fault.staging_witness(node, claimed), node['transactionStaging'])
        for field, changed in [('commandId', 'f' * 64), ('attemptId', '2'),
                ('transactionId', 'f' * 64), ('publicationId', 'publication:sha256:' + 'f' * 64)]:
            stale = copy.deepcopy(node)
            stale['transactionStaging'][field] = changed
            with self.subTest(field=field), self.assertRaises(ValueError):
                fault.staging_witness(stale, claimed)
        for witness in (None, {'capturedIntents': 1, 'stateWriteBytes': '16616'}):
            changed = copy.deepcopy(node)
            changed['transactionStaging'] = witness
            with self.subTest(witness=witness), self.assertRaises(ValueError):
                fault.staging_witness(changed, claimed)

    def test_recording_client_preserves_raw_busy_and_reaps_with_absolute_read_cutoff(self):
        import hashlib
        clock = Clock()
        raw = encoded(busy('dispatcher inspect'))
        completed = []
        class Process:
            def __init__(self, *args, **kwargs):
                self.buffers = (raw, b'')
                self.owner = SimpleNamespace(process=SimpleNamespace(returncode=5), finished=False)
                self.closed = False
                clock.now += 3
            def complete(self, deadline):
                completed.append(deadline)
                return SimpleNamespace(stdout=raw, returncode=5)
            def close(self):
                self.closed, self.owner.finished = True, True
        with tempfile.TemporaryDirectory() as temporary:
            client = RecordingClient.__new__(RecordingClient)
            client.cancellation, client.calls, client.deadline = Mock(), 0, clock.now + 1000
            client.node, client.config, client.phase4 = None, None, True
            client.executable, client.directory, client.environment = Path('synthetic-cli'), Path(temporary), {}
            client.evidence = Evidence(Path(temporary) / 'retained')
            with clock.installed(fault), patch('tools.java_transaction_qualification.evidence.Process', Process):
                value = client.call('dispatcher', 'inspect', '--scope', 'node', codes=(0, 5), cutoff=110)
            self.assertEqual(value, busy('dispatcher inspect'))
            self.assertEqual(completed, [110])
            self.assertEqual((client.evidence.directory / 'cli-001.stdout').read_bytes(), raw)
            self.assertEqual((client.evidence.directory / 'cli-001-process.json').read_bytes(),
                encoded({'exitStatus': 5, 'reaped': True,
                    'stdout': {'path': 'cli-001.stdout', 'bytes': len(raw), 'digest': 'sha256:' + hashlib.sha256(raw).hexdigest()},
                    'stderr': {'empty': True, 'bytes': 0, 'digest': 'sha256:' + hashlib.sha256(b'').hexdigest()}}))
            self.assertFalse((client.evidence.directory / 'cli-001.stderr').exists())
            self.assertFalse(value['outcomeKnown'])
            self.assertEqual(client.calls, 1)

    def test_terminal_and_pending_identity_bind_transitive_read_observer_bytes(self):
        from tools import run_java_transaction_http_qualification as terminal_runner
        from tools import run_java_pending_recovery_qualification as pending_runner
        helper = 'tools/java_transaction_qualification/read_observer.py'
        self.assertIn(helper, terminal_runner.COLLECTORS)
        source = Path(terminal_runner.__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for name in dict.fromkeys(terminal_runner.COLLECTORS + pending_runner.EXTRA_COLLECTORS):
                destination = root / name
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes((source / name).read_bytes())
            with patch.object(terminal_runner, '__file__', str(root / 'tools/run_java_transaction_http_qualification.py')), \
                    patch.object(pending_runner, '__file__', str(root / 'tools/run_java_pending_recovery_qualification.py')):
                before = terminal_runner.collector_identity()
                inherited = pending_runner.collector_identity()
                self.assertEqual(before[helper], inherited[helper])
                path = root / helper
                path.write_bytes(path.read_bytes() + b'\n# controlled collector identity change\n')
                after = terminal_runner.collector_identity()
                inherited_after = pending_runner.collector_identity()
                self.assertNotEqual(before[helper], after[helper])
                self.assertEqual(after[helper], inherited_after[helper])
                for original, changed in ((before, after), (inherited, inherited_after)):
                    self.assertEqual({name: value for name, value in original.items() if name != helper},
                                     {name: value for name, value in changed.items() if name != helper})


if __name__ == '__main__':
    unittest.main()
