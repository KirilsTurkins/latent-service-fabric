"""Optional cancellation metadata controls; mocked owners supply no native proof."""
from __future__ import annotations

import copy
import json
import unittest

from tools.java_transaction_qualification import campaign, lifecycle
from tools.tests.test_java_retained_cancellation import COMMITTED, KEY, SessionFixture


class OptionalPayloadFixture(SessionFixture):
    def __init__(self):
        super().__init__()
        self.lookup_record = copy.deepcopy(self.response['command'])
        self.response['command']['retainedResult'] = None
        self.lookup_calls, self.lookup_failure = [], None

    def call(self, *argv, **kwargs):
        if argv[:2] != ('transaction', 'lookup'):
            assert kwargs == {}
            return super().call(*argv)
        assert self.client.role == 'user'
        assert self.activation.active == 'put-once-legacy-v1'
        assert self.started[-1] == 'cancellation-legacy-runtime' and self.node.ordinal == 13
        assert argv == ('transaction', 'lookup',
            *lifecycle.namespace_arguments(self.publications['put-once-legacy-v1']),
            '--operation', 'update', '--client-key', KEY)
        assert kwargs == {'codes': (0, 3)}
        self.lookup_calls.append((argv, kwargs))
        self.events.append('lookup')
        if self.lookup_failure is not None:
            raise self.lookup_failure
        return {'data': {'command': copy.deepcopy(self.lookup_record)}}

    def damage(self, record, field):
        if field == 'publication':
            record['source']['publicationId'] = self.publications['put-once-compatible-v2']
        elif field == 'clientKey':
            record['key']['clientKey'] = 'another-original'
        elif field in {'metadataDurable', 'applicationStateCommitted'}:
            record[field] = False
        elif field == 'outcome':
            record[field] = 'COMMAND_OUTCOME_REJECTED'
        else:
            record[field] = 'another-original'


class CancellationOptionalPayload(unittest.TestCase):
    def assert_unfinished(self, fixture, lookups):
        self.assertEqual(len(fixture.cancel_calls), 1)
        self.assertEqual(len(fixture.lookup_calls), lookups)
        self.assertEqual(fixture.client.role, 'operator')
        self.assertEqual(fixture.activation.active, 'put-once-legacy-v1')
        self.assertEqual(fixture.node.ordinal, 13)
        self.assertEqual(fixture.started, [*fixture.old_prefix, *fixture.new_sessions[:2]])
        fixture.subject.original.assert_not_called()
        fixture.subject.query.assert_not_called()
        self.assertNotIn('replay', fixture.events)
        self.assertNotIn('cancellation-after-commit', fixture.collector.cases)
        fixture.unchanged_original_evidence()

    def test_null_receipt_reads_original_once_as_user_before_compatible_and_full_http_replay(self):
        with OptionalPayloadFixture() as fixture:
            original, receipt = copy.deepcopy(fixture.original), copy.deepcopy(fixture.response)
            fixture.subject._retained_cancellation()
            self.assertEqual(len(fixture.cancel_calls), 1)
            self.assertEqual(len(fixture.lookup_calls), 1)
            self.assertEqual(fixture.client.role, 'operator')
            self.assertEqual(fixture.started, [*fixture.old_prefix, *fixture.new_sessions])
            self.assertEqual(fixture.events.count('cancel'), 1)
            self.assertEqual(fixture.events.count('lookup'), 1)
            read = fixture.events.index('lookup')
            returned = fixture.events.index(('start', 'cancellation-compatible-metadata'))
            self.assertLess(fixture.events.index('cancel'), read)
            self.assertLess(read, returned)
            self.assertEqual(fixture.events[read - 1:read + 2], ['user-enter', 'lookup', 'user-exit'])
            self.assertEqual(fixture.events[-3:], ['original-get', 'replay', 'query-four'])
            self.assertEqual(fixture.original, original)
            self.assertEqual(fixture.response, receipt)
            captured = json.loads((fixture.collector.directory / 'case-cancellation-after-commit.json').read_bytes())
            self.assertIsNone(captured['observed']['command']['retainedResult'])
            fixture.unchanged_original_evidence()

    def test_complete_cancellation_payload_keeps_original_no_lookup_path(self):
        with OptionalPayloadFixture() as fixture:
            fixture.response['command']['retainedResult'] = copy.deepcopy(fixture.lookup_record['retainedResult'])
            fixture.lookup_failure = AssertionError('unexpected fallback read')
            fixture.subject._retained_cancellation()
            self.assertEqual(len(fixture.cancel_calls), 1)
            self.assertEqual(fixture.lookup_calls, [])
            self.assertEqual(fixture.started, [*fixture.old_prefix, *fixture.new_sessions])
            self.assertEqual(fixture.events.count('user-enter'), 1)
            self.assertEqual(fixture.events[-3:], ['original-get', 'replay', 'query-four'])

    def test_wrong_cancellation_identity_durability_outcome_or_source_refuses_before_read(self):
        for field in ['commandId', 'attemptId', 'publication', 'clientKey', 'metadataDurable',
                      'outcome', 'applicationStateCommitted']:
            with self.subTest(field=field), OptionalPayloadFixture() as fixture:
                fixture.damage(fixture.response['command'], field)
                with self.assertRaisesRegex(ValueError, 'actual-original-durable-command-inspection'):
                    fixture.subject._retained_cancellation()
                self.assert_unfinished(fixture, 0)

    def test_absent_or_malformed_original_source_cannot_trigger_fallback(self):
        for source in (None, {}, {'publicationId': 'foreign'}):
            with self.subTest(source=source), OptionalPayloadFixture() as fixture:
                fixture.response['command']['source'] = source
                with self.assertRaises((ValueError, KeyError, TypeError)):
                    fixture.subject._retained_cancellation()
                self.assert_unfinished(fixture, 0)

    def test_non_already_committed_null_receipt_does_not_read_or_claim(self):
        for disposition in ('COMMAND_CANCEL_DISPOSITION_REQUESTED',
                'COMMAND_CANCEL_DISPOSITION_ALREADY_TERMINAL', 'COMMAND_CANCEL_DISPOSITION_RECOVERY_REQUIRED'):
            with self.subTest(disposition=disposition), OptionalPayloadFixture() as fixture:
                fixture.response['cancellationDisposition'] = disposition
                with self.assertRaisesRegex(ValueError, 'retained-cancellation-is-already-committed'):
                    fixture.subject._retained_cancellation()
                self.assert_unfinished(fixture, 0)

    def test_missing_or_nonnull_malformed_payload_is_not_a_fallback_signal(self):
        for shape in ('missing', {}, [], False, 0):
            with self.subTest(shape=shape), OptionalPayloadFixture() as fixture:
                if shape == 'missing':
                    del fixture.response['command']['retainedResult']
                else:
                    fixture.response['command']['retainedResult'] = shape
                with self.assertRaises((KeyError, TypeError)):
                    fixture.subject._retained_cancellation()
                self.assert_unfinished(fixture, 0)

    def test_single_lookup_failure_or_cancellation_restores_user_without_retry_or_switch(self):
        for error in (ValueError('original-read-refused'), KeyboardInterrupt('original-cancellation')):
            with self.subTest(error=type(error).__name__), OptionalPayloadFixture() as fixture:
                fixture.lookup_failure = error
                with self.assertRaises(type(error)):
                    fixture.subject._retained_cancellation()
                self.assert_unfinished(fixture, 1)
                self.assertEqual(fixture.events[-2:], ['lookup', 'user-exit'])

    def test_foreign_lookup_identity_durability_outcome_or_source_fails_full_check(self):
        for field in ['commandId', 'attemptId', 'publication', 'clientKey', 'metadataDurable',
                      'outcome', 'applicationStateCommitted']:
            with self.subTest(field=field), OptionalPayloadFixture() as fixture:
                fixture.damage(fixture.lookup_record, field)
                with self.assertRaisesRegex(ValueError, 'actual-original-durable-command-inspection'):
                    fixture.subject._retained_cancellation()
                self.assert_unfinished(fixture, 1)

    def test_missing_or_expired_lookup_result_is_not_retried_or_treated_as_cancel_proof(self):
        for shape in ('missing-command', 'null-payload', 'missing-payload', 'empty-payload'):
            with self.subTest(shape=shape), OptionalPayloadFixture() as fixture:
                if shape == 'missing-command':
                    fixture.lookup_record = None
                elif shape == 'null-payload':
                    fixture.lookup_record['retainedResult'] = None
                elif shape == 'missing-payload':
                    del fixture.lookup_record['retainedResult']
                else:
                    fixture.lookup_record['retainedResult'] = {}
                with self.assertRaises((KeyError, TypeError)):
                    fixture.subject._retained_cancellation()
                self.assert_unfinished(fixture, 1)

    def test_lookup_payload_kind_encoding_and_exact_original_body_stay_mandatory(self):
        for field, value in [('kind', 'business-rejection'), ('encoding', 'text'), ('data', 'W10=')]:
            with self.subTest(field=field), OptionalPayloadFixture() as fixture:
                retained = fixture.lookup_record['retainedResult']
                if field == 'kind':
                    retained[field] = value
                else:
                    retained['value']['payload'][field] = value
                with self.assertRaisesRegex(ValueError, 'original-http-and-rpc-application-result-bytes'):
                    fixture.subject._retained_cancellation()
                self.assert_unfinished(fixture, 1)

    def test_full_rpc_result_remains_strict_outside_optional_cancel_path(self):
        with OptionalPayloadFixture() as fixture:
            with self.assertRaises(TypeError):
                campaign.rpc_result(fixture.response['command'], fixture.original,
                    fixture.publications['put-once-legacy-v1'], KEY)
            self.assertEqual(fixture.cancel_calls, [])
            self.assertEqual(fixture.lookup_calls, [])
            self.assertNotIn('cancellation-after-commit', fixture.collector.cases)

    def test_return_selection_failure_after_valid_read_does_not_claim_http_replay(self):
        with OptionalPayloadFixture() as fixture:
            fixture.failure = ('metadata', 'put-once-compatible-v2')
            with self.assertRaisesRegex(ValueError, 'uncertain-metadata'):
                fixture.subject._retained_cancellation()
            self.assertEqual(len(fixture.cancel_calls), 1)
            self.assertEqual(len(fixture.lookup_calls), 1)
            self.assertEqual(fixture.client.role, 'operator')
            fixture.subject.original.assert_not_called()
            fixture.subject.query.assert_not_called()
            self.assertNotIn('replay', fixture.events)
            self.assertNotIn('cancellation-after-commit', fixture.collector.cases)
