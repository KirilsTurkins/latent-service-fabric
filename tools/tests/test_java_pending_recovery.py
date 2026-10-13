"""Closed observer/sequence controls; synthetic values do not qualify a native run."""
from __future__ import annotations

import copy
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from tools.java_transaction_qualification import configuration as cfg, lifecycle, pending_controls as controls
from tools.java_transaction_qualification.pending_campaign import CLOSE_OPERATION, PendingCampaign
from tools.phase2_operator_process import write_json


def view():
    return list(b'NV\x02' + bytes([19]) * 32
                + b''.join(value.to_bytes(8, 'little') for value in (1, 2, 3, 4)))


def snapshot():
    return ({field: '0' for field in controls.COUNTERS}
        | {field: False for field in controls.FLAGS}
        | dict(generation={'ownerEpoch': '1', 'revision': '2'}, failure='DISPATCHER_FAILURE_NONE',
               paused=True, clockContinuityProven=True, liveWorkers='2', countsObservedAtUnixMillis='3'))


def plan_result():
    return {'action': 'inspect-close-effects', 'acknowledgement': 'sha256:' + 'a' * 64,
        'plan': {'schemaVersion': 'lsf.effect-recovery-close.v1', 'operatorId': cfg.OPERATOR,
            'operationId': CLOSE_OPERATION,
            'scope': {'tenant': cfg.TENANT, 'namespace': cfg.NAMESPACE, 'incarnation': 1},
            'expectedView': view(), 'expectedGuard': [1, 2, 3], 'lossWindowDigest': [34] * 32,
            'reason': 'remote-acceptance-observed-explicit-no-redrive', 'effects': [{
                'effectId': 'e' * 64, 'originalDigest': [1] * 32, 'payloadDigest': [2] * 32,
                'historyDigest': [3] * 32, 'originalDisposition': 'Pending', 'originalClockMillis': 10}]}}


def receipt(plan, *, replay=False):
    return {'action': 'close-effects', 'replay': replay, 'receipt': {
        'schemaVersion': 'lsf.effect-recovery-close.v1', 'outcome': 'closed-without-redrive',
        'plan': copy.deepcopy(plan), 'acknowledgement': [170] * 32, 'observedAtMillis': 11}}


class PendingRecoveryControls(unittest.TestCase):
    def test_program_selectors_reject_unknown_untyped_and_legacy_pending_before_process(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            with patch.object(lifecycle, 'Process') as process:
                for selected in ('other', [], True, 0, None):
                    with self.subTest(selected=selected), self.assertRaises(ValueError):
                        lifecycle.Node(SimpleNamespace(phase4=True), root / 'unused', root,
                                       current_publication_program=True, current_program=selected)
                with self.assertRaises(ValueError):
                    lifecycle.Node(SimpleNamespace(phase4=True), root / 'unused', root,
                                   current_program='pending-close')
                process.assert_not_called()

    def test_pending_session_order_cannot_expand_terminal_or_legacy_defaults(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            node = lifecycle.Node(SimpleNamespace(phase4=True, environment={}, cancellation=None), root / 'unused', root,
                current_publication_program=True, current_program='pending-close')
            rows = [{'publication': 'publication:sha256:' + 'a' * 64, 'function': function}
                    for function in ('update', 'query', 'scan')]
            path = root / 'configuration.json'
            with patch.object(lifecycle, 'Process', side_effect=RuntimeError('native-not-created')) as process:
                for position, session in enumerate(lifecycle.PENDING_NODE_PROGRAM):
                    node.ordinal = position
                    path = root / f'configuration-{position}.json'
                    write_json(path, {'state': {'formatVersion': 2, 'operations': [] if position < 2 else rows}})
                    with self.subTest(position=position), self.assertRaisesRegex(RuntimeError, 'native-not-created'):
                        node.start(path, current_session=session)
                self.assertEqual(process.call_count, 6)
                node.ordinal = 6
                with self.assertRaises(ValueError):
                    node.start(path, current_session='pending-restored-runtime')
                node.ordinal = 4
                with self.assertRaises(ValueError):
                    node.start(path, current_session='diagnostic-metadata')
            ordinary = lifecycle.Node(SimpleNamespace(phase4=True), root / 'unused', root,
                                       current_publication_program=True)
            self.assertEqual(ordinary.program, lifecycle.CURRENT_NODE_PROGRAM)
            self.assertEqual(len(ordinary.program), 14)
            legacy = lifecycle.Node(SimpleNamespace(), root / 'unused', root)
            legacy.ordinal = 6
            with patch.object(lifecycle, 'Process') as process, self.assertRaises(ValueError):
                legacy.start(path)
            process.assert_not_called()

    def test_restore_authority_is_one_empty_operation_session_at_exact_pending_position(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            node = lifecycle.Node(SimpleNamespace(phase4=True, environment={}, cancellation=None), root / 'unused', root,
                current_publication_program=True, current_program='pending-close')
            path = root / 'configuration.json'
            write_json(path, {'state': {'formatVersion': 2, 'operations': [], 'createIfMissing': False}})
            with patch.object(lifecycle, 'Process', side_effect=RuntimeError('native-not-created')) as process:
                node.ordinal = 4
                with self.assertRaises(ValueError):
                    node.start(path, restore_authority=True)
                process.assert_not_called()
                node.ordinal = 5
                with self.assertRaisesRegex(RuntimeError, 'native-not-created'):
                    node.start(path, restore_authority=True)
                self.assertEqual(node.restore_authority_sessions, 1)
                with self.assertRaises(ValueError):
                    node.start(path, restore_authority=True)
                self.assertEqual(process.call_count, 1)

    def test_logical_pause_with_any_live_physical_owner_cannot_satisfy_drain(self):
        client = SimpleNamespace(deadline=10**12)
        for field in controls.PHYSICAL:
            value = snapshot()
            value[field] = '1'
            with self.subTest(field=field), patch.object(controls, 'inspect_dispatcher', return_value=value), \
                 patch.object(controls.time, 'sleep'), self.assertRaisesRegex(ValueError, 'not-drained'):
                controls.drained_dispatcher(client)
        with patch.object(controls, 'inspect_dispatcher', return_value=snapshot()):
            self.assertEqual(controls.drained_dispatcher(client)['liveWorkers'], '2')
        value = snapshot()
        value['restoreReviewRequired'] = True
        with patch.object(controls, 'inspect_dispatcher', return_value=value), self.assertRaises(ValueError):
            controls.drained_dispatcher(client)

    def test_close_plan_preserves_exact_pending_effect_window_view_and_operator(self):
        value = plan_result()
        expected, ack = controls.close_plan(value, CLOSE_OPERATION, 'e' * 64, view(), 'sha256:' + '2' * 64)
        self.assertEqual(expected, value['plan'])
        self.assertEqual(ack, value['acknowledgement'])
        for field, changed in (('operatorId', 'other'), ('operationId', 'other'),
                ('expectedView', view()[:-1]), ('lossWindowDigest', [1] * 32), ('approved', True)):
            invalid = copy.deepcopy(value)
            invalid['plan'][field] = changed
            with self.subTest(field=field), self.assertRaises(ValueError):
                controls.close_plan(invalid, CLOSE_OPERATION, 'e' * 64, view(), 'sha256:' + '2' * 64)
        for changed in ({'effectId': 'f' * 64}, {'originalDisposition': 'ProviderAcknowledged'},
                        {'originalClockMillis': True}, {'originalDigest': [0] * 32}):
            invalid = copy.deepcopy(value)
            invalid['plan']['effects'][0].update(changed)
            with self.subTest(changed=changed), self.assertRaises(ValueError):
                controls.close_plan(invalid, CLOSE_OPERATION, 'e' * 64, view(), 'sha256:' + '2' * 64)

    def test_close_is_abandonment_and_replay_cannot_replace_receipt_or_acknowledgement(self):
        plan = plan_result()['plan']
        value = receipt(plan)
        self.assertEqual(controls.close_receipt(value, plan, 'sha256:' + 'a' * 64, replay=False), value['receipt'])
        for field, changed in (('outcome', 'delivered'), ('acknowledgement', [1] * 32),
                ('observedAtMillis', True), ('observedAtMillis', 9), ('approved', True)):
            invalid = copy.deepcopy(value)
            invalid['receipt'][field] = changed
            with self.subTest(field=field), self.assertRaises(ValueError):
                controls.close_receipt(invalid, plan, 'sha256:' + 'a' * 64, replay=False)
        with self.assertRaises(ValueError):
            controls.close_receipt(value, plan, 'sha256:' + 'a' * 64, replay=True)

    def test_changed_replay_stops_before_review_resume_or_runtime_start(self):
        runner = PendingCampaign.__new__(PendingCampaign)
        inspected = plan_result()
        first, repeated = receipt(inspected['plan']), receipt(inspected['plan'], replay=True)
        repeated['receipt']['observedAtMillis'] = 12
        runner.action = Mock(side_effect=[inspected, first, repeated])
        runner.inspect, runner.resume = Mock(), Mock()
        runner.node = SimpleNamespace(start=Mock())
        with self.assertRaisesRegex(ValueError, 'replay-is-immutable'):
            runner.close_original({'effect-ids': ['e' * 64]}, {'view': view()}, 'sha256:' + '2' * 64)
        self.assertEqual(runner.action.call_count, 3)
        runner.inspect.assert_not_called()
        runner.resume.assert_not_called()
        runner.node.start.assert_not_called()

    def test_dispatcher_audit_is_not_synthesized_from_nonnull_or_known_receipt(self):
        controls.durable_audit({'status': 'AUDIT_ACK_STATUS_DURABLE', 'attemptSequence': '1'})
        for value in ({}, {'status': 'AUDIT_ACK_STATUS_UNAVAILABLE', 'attemptSequence': '1'},
                      {'status': 'AUDIT_ACK_STATUS_DURABLE', 'attemptSequence': True},
                      {'status': 'AUDIT_ACK_STATUS_DURABLE', 'attemptSequence': '0'}):
            with self.subTest(value=value), self.assertRaises(ValueError):
                controls.durable_audit(value)

    def test_live_owner_after_signed_commit_prevents_quiesce_and_backup(self):
        from tools.java_transaction_qualification import pending_campaign
        runner = PendingCampaign.__new__(PendingCampaign)
        original = {'disposition': 'committed', 'effect-ids': ['e' * 64]}
        runner.campaign = SimpleNamespace(query=Mock(return_value=({}, {'key-version': {'none': None}})),
            result=Mock(return_value=original), socket=Mock(return_value={}), originals={})
        runner.client = SimpleNamespace()
        runner.publication = 'publication:sha256:' + 'a' * 64
        runner.pending_effect = Mock(return_value={'disposition': 'EFFECT_DISPOSITION_PENDING'})
        runner.observation = Mock(return_value={'posts': 0, 'mutations': 0, 'retainedRecords': 0})
        runner.quiesce, runner.snapshot = Mock(), Mock()
        with patch.object(controls, 'control_dispatcher'), \
             patch.object(controls, 'drained_dispatcher', side_effect=[snapshot(), ValueError('physical-live')]), \
             patch.object(pending_campaign.http, 'aggregate', return_value={'count': '1'}), \
             patch.object(pending_campaign.lifecycle, 'lookup', return_value={}), \
             patch.object(pending_campaign, 'rpc_result'):
            with self.assertRaisesRegex(ValueError, 'physical-live'):
                runner.execute()
        runner.quiesce.assert_not_called()
        runner.snapshot.assert_not_called()

    def test_unknown_dispatcher_operation_lookup_cannot_qualify_plausible_original_receipt(self):
        audit = {'status': 'AUDIT_ACK_STATUS_DURABLE', 'attemptSequence': '1'}
        original = {'operationId': 'original-pause', 'receiptId': 'sha256:' + 'a' * 64,
            'action': 'DISPATCHER_ACTION_PAUSE', 'authenticatedOperator': lifecycle.operator_actor(),
            'actorTenant': cfg.TENANT, 'beforeGeneration': {'ownerEpoch': '1', 'revision': '2'},
            'afterGeneration': {'ownerEpoch': '1', 'revision': '3'}, 'observedAtUnixMillis': '10',
            'clockContinuityProven': True, 'restoreReviewRequired': False,
            'disposition': 'STATE_OPERATION_DISPOSITION_COMMITTED'}
        responses = [
            {'outcomeKnown': True, 'data': {'dispatcher': snapshot(), 'auditAcknowledgement': audit}},
            {'outcomeKnown': True, 'data': {'receipt': original, 'replayed': False, 'published': True,
                                          'paused': True, 'auditAcknowledgement': audit}},
            {'outcomeKnown': False, 'data': {'receipt': original, 'auditAcknowledgement': audit}}]
        client = SimpleNamespace(call=Mock(side_effect=responses), evidence=SimpleNamespace(passed=Mock()))
        with self.assertRaisesRegex(ValueError, 'historical-dispatcher-receipt-is-original'):
            controls.control_dispatcher(client, 'pause', 'original-pause')
        self.assertEqual(client.call.call_count, 3)
        client.evidence.passed.assert_not_called()


if __name__ == '__main__':
    unittest.main()
