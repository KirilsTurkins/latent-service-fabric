"""Mocked collector selection controls; no native cancellation qualification."""
from contextlib import contextmanager
import copy
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from tools.java_transaction_qualification import campaign, http, lifecycle
from tools.tests.test_java_transaction_campaign import inspection
from tools.tests.test_java_transaction_qualification import result


LEGACY = 'publication:sha256:' + '1' * 64
COMPATIBLE = 'publication:sha256:' + '2' * 64
KEY = 'java-original-1'
COMMITTED = 'COMMAND_CANCEL_DISPOSITION_ALREADY_COMMITTED'


class Fixture:
    def __init__(self, *, current=True):
        self.current, self.active = current, 'put-once-compatible-v2'
        self.events, self.failure = [], None
        self.original = result(count='1')
        command = inspection(self.original)
        command['source']['publicationId'] = LEGACY
        command['key']['clientKey'] = KEY
        self.response = {'cancellationDisposition': COMMITTED, 'command': command}
        self.subject = campaign.Campaign.__new__(campaign.Campaign)
        self.subject.publications = {'put-once-legacy-v1': LEGACY, 'put-once-compatible-v2': COMPATIBLE}
        self.subject.originals = {KEY: self.original}
        self.subject.client = SimpleNamespace(role='operator', call=Mock(side_effect=self.cancel),
            evidence=SimpleNamespace(passed=Mock(side_effect=self.passed)))
        self.activation = SimpleNamespace(switch=Mock(side_effect=self.switch))
        self.subject.node = SimpleNamespace(current_publication_program=current, current_program='terminal',
            current_activation=self.activation if current else None)
        self.subject.original = Mock(side_effect=self.read_original)
        self.subject.query = Mock(side_effect=self.query)
        self.replay = http.replay

    @contextmanager
    def user(self, client):
        assert client is self.subject.client and client.role == 'operator'
        client.role = 'user'
        self.events.append('user-enter')
        try:
            yield
        finally:
            client.role = 'operator'
            self.events.append('user-exit')

    def switch(self, subject, name):
        assert subject is self.subject and subject.client.role == 'operator'
        self.events.append(('switch', name))
        if self.failure == name:
            raise ValueError('selection-refused')
        self.active = name

    def cancel(self, *argv):
        self.events.append('cancel')
        assert self.subject.client.role == 'user'
        expected = ('transaction', 'cancel', *lifecycle.namespace_arguments(LEGACY),
            '--operation', 'update', '--client-key', KEY, '--attempt-id', self.original['attempt-id'],
            '--reason', 'cancelled')
        if argv != expected or (self.current and self.active != 'put-once-legacy-v1'):
            raise ValueError('protected-original-source-refused')
        if self.failure == 'cancel':
            raise ValueError('cancellation-refused')
        return {'data': copy.deepcopy(self.response)}

    def read_original(self, key):
        assert key == KEY
        assert self.active == 'put-once-compatible-v2'
        self.events.append('original-get')
        if self.failure == 'original-get':
            raise ValueError('original-read-refused')
        return copy.deepcopy(self.original)

    def verify_replay(self, original, retained):
        assert self.active == 'put-once-compatible-v2'
        self.events.append('replay')
        if self.failure == 'replay':
            raise ValueError('replay-refused')
        return self.replay(original, retained)

    def query(self, count):
        assert count == 4 and self.active == 'put-once-compatible-v2'
        self.events.append('query-four')
        if self.failure == 'query':
            raise ValueError('query-refused')

    def passed(self, name, value):
        assert name == 'cancellation-after-commit' and value == self.response
        self.events.append('passed')

    def run(self):
        with patch.object(lifecycle, 'as_user', side_effect=self.user), \
                patch.object(lifecycle, 'deploy', side_effect=AssertionError('unexpected generic deployment')), \
                patch.object(http, 'replay', side_effect=self.verify_replay):
            self.subject._retained_cancellation()


class RetainedCancellation(unittest.TestCase):
    def assert_unfinished(self, fixture):
        fixture.subject.client.evidence.passed.assert_not_called()
        fixture.subject.query.assert_not_called()
        self.assertNotIn('replay', fixture.events)
        self.assertEqual(fixture.subject.client.role, 'operator')

    def test_current_terminal_selects_original_then_compatible_before_replay(self):
        fixture = Fixture()
        original = copy.deepcopy(fixture.original)
        fixture.run()
        self.assertEqual(fixture.events, [('switch', 'put-once-legacy-v1'), 'user-enter', 'cancel',
            'user-exit', ('switch', 'put-once-compatible-v2'), 'original-get', 'replay', 'query-four', 'passed'])
        self.assertEqual(fixture.subject.client.call.call_count, 1)
        self.assertEqual(fixture.activation.switch.call_count, 2)
        self.assertEqual(fixture.original, original)

    def test_historical_runtime_uses_original_binding_without_switches(self):
        fixture = Fixture(current=False)
        fixture.run()
        self.assertEqual(fixture.events, ['user-enter', 'cancel', 'user-exit', 'original-get',
            'replay', 'query-four', 'passed'])
        fixture.activation.switch.assert_not_called()
        self.assertEqual(fixture.subject.client.call.call_count, 1)

    def test_current_requires_terminal_and_retained_activation(self):
        for program, activation in [('early', True), ('terminal', False)]:
            with self.subTest(program=program, activation=activation):
                fixture = Fixture()
                fixture.subject.node.current_program = program
                if not activation:
                    fixture.subject.node.current_activation = None
                with self.assertRaisesRegex(ValueError, 'current-retained-cancellation-original-selection'):
                    fixture.run()
                fixture.subject.client.call.assert_not_called()
                fixture.activation.switch.assert_not_called()
                self.assert_unfinished(fixture)

    def test_original_selection_failure_prevents_cancel_without_retry(self):
        fixture = Fixture()
        fixture.failure = 'put-once-legacy-v1'
        with self.assertRaisesRegex(ValueError, 'selection-refused'):
            fixture.run()
        fixture.subject.client.call.assert_not_called()
        self.assertEqual(fixture.activation.switch.call_count, 1)
        self.assert_unfinished(fixture)

    def test_cancel_failure_restores_user_context_and_stops_case(self):
        fixture = Fixture()
        fixture.failure = 'cancel'
        with self.assertRaisesRegex(ValueError, 'cancellation-refused'):
            fixture.run()
        self.assertEqual(fixture.subject.client.call.call_count, 1)
        self.assertEqual(fixture.activation.switch.call_count, 1)
        self.assert_unfinished(fixture)

    def test_non_already_committed_result_cannot_claim_case(self):
        for disposition in ['COMMAND_CANCEL_DISPOSITION_REQUESTED',
                'COMMAND_CANCEL_DISPOSITION_ALREADY_TERMINAL', 'COMMAND_CANCEL_DISPOSITION_RECOVERY_REQUIRED']:
            with self.subTest(disposition=disposition):
                fixture = Fixture()
                fixture.response['cancellationDisposition'] = disposition
                with self.assertRaisesRegex(ValueError, 'retained-cancellation-is-already-committed'):
                    fixture.run()
                self.assertEqual(fixture.subject.client.call.call_count, 1)
                self.assertEqual(fixture.activation.switch.call_count, 1)
                self.assert_unfinished(fixture)

    def test_missing_cancellation_disposition_cannot_claim_case(self):
        fixture = Fixture()
        del fixture.response['cancellationDisposition']
        with self.assertRaises(KeyError):
            fixture.run()
        self.assertEqual(fixture.subject.client.call.call_count, 1)
        self.assert_unfinished(fixture)

    def test_foreign_original_command_metadata_refuses_replay(self):
        for field in ['commandId', 'attemptId', 'publication', 'clientKey', 'metadataDurable']:
            with self.subTest(field=field):
                fixture = Fixture()
                command = fixture.response['command']
                if field == 'publication':
                    command['source']['publicationId'] = COMPATIBLE
                elif field == 'clientKey':
                    command['key']['clientKey'] = 'another-original'
                elif field == 'metadataDurable':
                    command[field] = False
                else:
                    command[field] = 'another-original'
                with self.assertRaisesRegex(ValueError, 'actual-original-durable-command-inspection'):
                    fixture.run()
                self.assertEqual(fixture.subject.client.call.call_count, 1)
                self.assertEqual(fixture.activation.switch.call_count, 1)
                self.assert_unfinished(fixture)

    def test_compatible_selection_failure_prevents_http_checks(self):
        fixture = Fixture()
        fixture.failure = 'put-once-compatible-v2'
        with self.assertRaisesRegex(ValueError, 'selection-refused'):
            fixture.run()
        self.assertEqual(fixture.subject.client.call.call_count, 1)
        self.assertEqual(fixture.activation.switch.call_count, 2)
        fixture.subject.original.assert_not_called()
        self.assert_unfinished(fixture)

    def test_original_http_get_failure_suppresses_replay_query_and_success(self):
        fixture = Fixture()
        fixture.failure = 'original-get'
        with self.assertRaisesRegex(ValueError, 'original-read-refused'):
            fixture.run()
        self.assertEqual(fixture.activation.switch.call_count, 2)
        self.assert_unfinished(fixture)

    def test_replay_failure_suppresses_query_and_success(self):
        fixture = Fixture()
        fixture.failure = 'replay'
        with self.assertRaisesRegex(ValueError, 'replay-refused'):
            fixture.run()
        fixture.subject.query.assert_not_called()
        fixture.subject.client.evidence.passed.assert_not_called()
        self.assertEqual(fixture.subject.client.call.call_count, 1)

    def test_query_failure_suppresses_success(self):
        fixture = Fixture()
        fixture.failure = 'query'
        with self.assertRaisesRegex(ValueError, 'query-refused'):
            fixture.run()
        fixture.subject.client.evidence.passed.assert_not_called()
        self.assertEqual(fixture.subject.client.call.call_count, 1)
        self.assertEqual(fixture.activation.switch.call_count, 2)
