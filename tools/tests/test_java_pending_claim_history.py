"""Mocked observations match the retained paused snapshot shape; no native claim."""
import copy
from contextlib import contextmanager
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from tools.java_transaction_qualification import pending_controls as controls


def acknowledged_snapshot():
    return {
        'generation': {'ownerEpoch': '1', 'revision': '2'},
        'failure': 'DISPATCHER_FAILURE_NONE',
        'queued': '0', 'activeJobs': '0', 'retainedAttemptBytes': '0',
        'liveWorkers': '3', 'acceptedEffects': '0', 'physicalOwners': '0',
        'quarantinedPhysicalOwners': '0', 'commandOwners': '0', 'claims': '1',
        'pendingEffects': '0', 'uncertainEffects': '0', 'blockedEffects': '0',
        'deadLetterEffects': '0', 'countsObservedAtUnixMillis': '3',
        'paused': True, 'pendingControl': False, 'restoreReviewRequired': False,
        'admissionClosed': False, 'quarantined': False, 'clockContinuityProven': True,
    }


def inspected(snapshot):
    return {
        'schemaVersion': 'latent.cli.result.v1', 'command': 'dispatcher inspect',
        'category': 'success', 'requestDispatched': True, 'outcomeKnown': True,
        'error': None,
        'data': {
            'dispatcher': copy.deepcopy(snapshot),
            'auditAcknowledgement': {
                'status': 'AUDIT_ACK_STATUS_DURABLE', 'attemptSequence': '151'},
        },
    }


class ReadFixture:
    def __init__(self, snapshot=None, *, deadline=100, response=None):
        self.now = 0.
        self.sleeps = []
        self.calls = []
        self.snapshot = acknowledged_snapshot() if snapshot is None else snapshot
        self.response = response
        self.client = SimpleNamespace(deadline=deadline, call=self.call)

    def call(self, *arguments, **keywords):
        self.calls.append((arguments, keywords))
        return (copy.deepcopy(self.response) if self.response is not None
                else inspected(self.snapshot))

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds

    @contextmanager
    def installed(self):
        with patch.object(controls.time, 'monotonic', side_effect=lambda: self.now), \
             patch.object(controls.time, 'sleep', side_effect=self.sleep):
            yield self.client


class PendingClaimHistory(unittest.TestCase):
    def test_actual_paused_acknowledged_shape_keeps_completed_claim_history(self):
        fixture = ReadFixture()
        with fixture.installed() as client:
            try:
                value = controls.drained_dispatcher(client)
            except ValueError as error:
                self.fail(f'healthy retired-owner snapshot rejected for cumulative claims: {error}')
        self.assertEqual(value, fixture.snapshot)
        self.assertEqual(value['claims'], '1')
        self.assertEqual(value['liveWorkers'], '3')
        self.assertEqual(len(fixture.calls), 1)
        self.assertEqual(fixture.sleeps, [])

    def test_each_real_physical_owner_still_refuses_with_the_same_claim_history(self):
        for field in ('queued', 'activeJobs', 'retainedAttemptBytes', 'acceptedEffects',
                      'physicalOwners', 'quarantinedPhysicalOwners', 'commandOwners'):
            value = acknowledged_snapshot()
            value[field] = '1'
            fixture = ReadFixture(value)
            with self.subTest(field=field), fixture.installed() as client, \
                 self.assertRaisesRegex(ValueError, '^actual-paused-dispatcher-not-drained$'):
                controls.drained_dispatcher(client)
            self.assertEqual(fixture.snapshot['claims'], '1')
            self.assertEqual(len(fixture.calls), 24)
            self.assertEqual(fixture.sleeps, [.1] * 24)
            self.assertTrue(all(arguments == ('dispatcher', 'inspect', '--scope', 'node')
                                and keywords['codes'] == (0, 5)
                                and keywords['cutoff'] == 10.
                                for arguments, keywords in fixture.calls))
            self.assertEqual(fixture.calls[0][1]['timeout'], 10.)
            self.assertAlmostEqual(fixture.calls[-1][1]['timeout'], 7.7)

    def test_physical_release_must_be_observed_without_resetting_history(self):
        held = acknowledged_snapshot()
        held['acceptedEffects'] = held['physicalOwners'] = held['activeJobs'] = '1'
        fixture = ReadFixture(held)
        responses = iter([inspected(held), inspected(acknowledged_snapshot())])
        def call(*arguments, **keywords):
            fixture.calls.append((arguments, keywords))
            return next(responses)
        fixture.client.call = call
        with fixture.installed() as client:
            value = controls.drained_dispatcher(client)
        self.assertEqual(value, acknowledged_snapshot())
        self.assertEqual(value['claims'], '1')
        self.assertEqual(len(fixture.calls), 2)
        self.assertEqual(fixture.sleeps, [.1])
        self.assertEqual(fixture.calls[0][1]['cutoff'], fixture.calls[1][1]['cutoff'])
        self.assertAlmostEqual(fixture.calls[1][1]['timeout'], 9.9)

    def test_valid_uint64_history_is_preserved_at_zero_one_and_maximum(self):
        for claims in ('0', '1', str(2**64 - 1)):
            value = acknowledged_snapshot()
            value['claims'] = claims
            fixture = ReadFixture(value)
            with self.subTest(claims=claims), fixture.installed() as client:
                self.assertEqual(controls.drained_dispatcher(client)['claims'], claims)
            self.assertEqual(len(fixture.calls), 1)
            self.assertEqual(fixture.sleeps, [])

    def test_missing_noncanonical_and_out_of_range_claim_history_remain_fatal(self):
        for claims in (None, True, 1, '-1', '+1', '01', '1.0', '', ' 1', '1 ',
                       str(2**64), '9' * 21, '\u0661'):
            value = acknowledged_snapshot()
            value['claims'] = claims
            fixture = ReadFixture(value)
            with self.subTest(claims=claims), fixture.installed() as client, \
                 self.assertRaisesRegex(ValueError, '^original-dispatcher-counter$'):
                controls.drained_dispatcher(client)
            self.assertEqual(len(fixture.calls), 1)
            self.assertEqual(fixture.sleeps, [])
        value = acknowledged_snapshot()
        del value['claims']
        fixture = ReadFixture(value)
        with fixture.installed() as client, \
             self.assertRaisesRegex(ValueError, '^closed-healthy-dispatcher-observation$'):
            controls.drained_dispatcher(client)
        self.assertEqual(len(fixture.calls), 1)
        self.assertEqual(fixture.sleeps, [])

    def test_health_pause_and_current_control_guards_are_independent_of_history(self):
        for field, changed in (('paused', False), ('pendingControl', True),
                               ('restoreReviewRequired', True), ('admissionClosed', True),
                               ('quarantined', True), ('clockContinuityProven', False)):
            value = acknowledged_snapshot()
            value[field] = changed
            fixture = ReadFixture(value)
            with self.subTest(field=field), fixture.installed() as client, \
                 self.assertRaisesRegex(ValueError, '^original-paused-dispatcher-control$'):
                controls.drained_dispatcher(client)
            self.assertEqual(len(fixture.calls), 1)
            self.assertEqual(fixture.sleeps, [])

    def test_generation_audit_and_failure_guards_cannot_be_replaced_by_history(self):
        for field, changed in (('failure', 'DISPATCHER_FAILURE_WORKER'),
                               ('generation', {'ownerEpoch': '0', 'revision': '2'})):
            value = acknowledged_snapshot()
            value[field] = changed
            fixture = ReadFixture(value)
            with self.subTest(field=field), fixture.installed() as client, \
                 self.assertRaises(ValueError):
                controls.drained_dispatcher(client)
            self.assertEqual(len(fixture.calls), 1)
            self.assertEqual(fixture.sleeps, [])
        for acknowledgement in (None, {'status': 'AUDIT_ACK_STATUS_UNKNOWN', 'attemptSequence': '151'},
                                 {'status': 'AUDIT_ACK_STATUS_DURABLE', 'attemptSequence': '0'}):
            response = inspected(acknowledged_snapshot())
            response['data']['auditAcknowledgement'] = acknowledgement
            fixture = ReadFixture(response=response)
            with self.subTest(acknowledgement=acknowledgement), fixture.installed() as client, \
                 self.assertRaises(ValueError):
                controls.drained_dispatcher(client)
            self.assertEqual(len(fixture.calls), 1)
            self.assertEqual(fixture.sleeps, [])

    def test_held_owner_cannot_renew_the_original_global_deadline(self):
        value = acknowledged_snapshot()
        value['physicalOwners'] = '1'
        fixture = ReadFixture(value, deadline=.25)
        with fixture.installed() as client, self.assertRaisesRegex(ValueError, 'cutoff'):
            controls.drained_dispatcher(client)
        self.assertEqual(len(fixture.calls), 3)
        self.assertAlmostEqual(fixture.now, .25)
        self.assertEqual(len(fixture.sleeps), 3)
        self.assertAlmostEqual(fixture.sleeps[-1], .05)
        self.assertTrue(all(keywords['cutoff'] == .25 for _, keywords in fixture.calls))
        for (_, keywords), expected in zip(fixture.calls, (.25, .15, .05)):
            self.assertAlmostEqual(keywords['timeout'], expected)


if __name__ == '__main__':
    unittest.main()
