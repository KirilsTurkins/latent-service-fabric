"""Current schema-history refusal controls; synthetic HTTP is not qualification."""
import base64
from contextlib import contextmanager
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from tools.java_transaction_qualification import campaign, configuration as cfg, http, lifecycle
from tools.java_transaction_qualification import offline_campaign, schema_view
from tools.java_transaction_qualification.evidence import encoded
from tools.tests import test_java_schema_view as views
from tools.tests.test_java_transaction_qualification import HEADERS, result


def token(view):
    return base64.b64encode(bytes(view)).decode()


def fresh(view, count=4):
    value = result('query', str(count))
    value['state-view'] = token(view)
    frame = [{'ok': {'count': str(count), 'view-version': list(view), 'key-version': {'none': None}}}]
    value['result']['body-base64'] = base64.b64encode(encoded(frame)).decode()
    return {'status': 200, 'body': encoded(value), 'headers': HEADERS, 'bodyLost': False}


def unavailable():
    return {'status': 503, 'body': b'Unavailable\n', 'bodyLost': False, 'headers': []}


class SchemaMinimumRefusalControls(unittest.TestCase):
    @contextmanager
    def fixture(self):
        with views.SchemaViewControls().descriptors() as (old, migrated, original, target):
            minimum = views.number(old, 43, int.from_bytes(bytes(old[43:51]), 'little') - 1)
            ready = views.number(migrated, 43, int.from_bytes(bytes(migrated[43:51]), 'little') + 1)
            before = {'disposition': 'query', 'state-view': token(minimum)}
            flow = campaign.Campaign.__new__(campaign.Campaign)
            flow.service, flow.request_count = cfg.SERVICE, 0
            flow.client = SimpleNamespace(evidence=Mock())
            flow.transport = Mock()
            flow.transport.request.side_effect = [fresh(ready), unavailable(), fresh(ready)]
            yield flow, before, old, migrated, ready, original, target

    def observe(self, flow, before, old, migrated, ready, original, target):
        return schema_view.minimum_refused(flow, 4, before, old, migrated, original, target)

    def test_old_409_guard_red_and_current_closed_refusal_green_with_real_query_parser(self):
        with self.fixture() as args:
            flow = args[0]
            with self.assertRaisesRegex(ValueError, 'actual-redacted-http-platform-refusal'):
                flow.refusal('schema-refuses-stale-query-minimum', unavailable(), {409})
            observed = self.observe(*args)
            self.assertEqual(http.view_token(observed['state-view']), bytes(args[4]))
            self.assertEqual(flow.transport.request.call_count, 3)
            passed = flow.client.evidence.passed.call_args
            self.assertEqual(passed.args[0], 'schema-refuses-stale-query-minimum')
            self.assertEqual(passed.args[1]['underlyingPlatformError'], 'unobserved-redacted-http')

    def test_three_requests_keep_same_alice_path_and_original_minimum_without_body_or_command(self):
        with self.fixture() as args:
            flow, before = args[:2]
            self.observe(*args)
            calls = flow.transport.request.call_args_list
            for row in calls:
                self.assertEqual(row.args, ('GET', '/transaction/query'))
                self.assertIsNone(row.kwargs['body'])
                self.assertEqual(row.kwargs['headers'][0], ('Authorization', 'Bearer ' + cfg.TOKENS[cfg.ALICE]))
                self.assertFalse(row.kwargs['lose_body'])
            self.assertEqual(calls[0].kwargs['headers'], calls[2].kwargs['headers'])
            self.assertEqual(calls[1].kwargs['headers'][1:], [('If-State-View', before['state-view'])])
            records = [row.args[1] for row in flow.client.evidence.record.call_args_list
                       if row.args[0].endswith('-input')]
            self.assertEqual(len(records), 3)
            self.assertTrue(all(row['subject'] == cfg.ALICE and row['originalClientKey'] is None
                and row['originalPrecondition'] is None and row['bodyBase64'] is None for row in records))

    def test_wrong_200_409_403_and_boolean_status_never_record_the_case_or_query_again(self):
        for status in (200, 409, 403, True):
            with self.subTest(status=status), self.fixture() as args:
                flow, _, _, _, ready, _, _ = args
                refusal = unavailable()
                refusal['status'] = status
                flow.transport.request.side_effect = [fresh(ready), refusal, fresh(ready)]
                with self.assertRaises(ValueError):
                    self.observe(*args)
                self.assertEqual(flow.transport.request.call_count, 2)
                flow.client.evidence.passed.assert_not_called()

    def test_other_503_bodies_missing_body_and_loss_are_not_the_intended_refusal(self):
        for field, value in [('body', b''), ('body', b'Unavailable'), ('body', b'Forbidden\n'),
                ('body', b'{"error":"unavailable"}'), ('body', None), ('bodyLost', True), ('bodyLost', None)]:
            with self.subTest(field=field, value=value), self.fixture() as args:
                flow, _, _, _, ready, _, _ = args
                refusal = unavailable()
                refusal[field] = value
                flow.transport.request.side_effect = [fresh(ready), refusal]
                with self.assertRaises(ValueError):
                    self.observe(*args)
                self.assertEqual(flow.transport.request.call_count, 2)
                flow.client.evidence.passed.assert_not_called()

    def test_wrong_subject_denial_cannot_supply_the_required_positive_query(self):
        with self.fixture() as args:
            flow = args[0]
            original_socket = flow.socket
            def denied_subject(mode, **kwargs):
                return original_socket(mode, subject=cfg.BOB)
            flow.socket = denied_subject
            flow.transport.request.return_value = {'status': 403, 'body': b'Forbidden\n', 'headers': []}
            flow.transport.request.side_effect = None
            with patch('tools.java_transaction_qualification.refusal_observation.observe'), self.assertRaises(ValueError):
                self.observe(*args)
            self.assertEqual(flow.transport.request.call_count, 1)
            self.assertEqual(flow.transport.request.call_args.kwargs['headers'][0],
                             ('Authorization', 'Bearer ' + cfg.TOKENS[cfg.BOB]))
            flow.client.evidence.passed.assert_not_called()

    def test_wrong_count_before_or_after_refusal_fails_the_actual_query_oracle(self):
        for first in (True, False):
            with self.subTest(first=first), self.fixture() as args:
                flow, _, _, _, ready, _, _ = args
                flow.transport.request.side_effect = [fresh(ready, 5 if first else 4), unavailable(), fresh(ready, 5)]
                with self.assertRaisesRegex(ValueError, 'actual-fresh-java-aggregate-value'):
                    self.observe(*args)
                self.assertEqual(flow.transport.request.call_count, 1 if first else 3)
                flow.client.evidence.passed.assert_not_called()

    def test_foreign_scope_or_entity_minimum_never_makes_a_request(self):
        for scope in ({'tenant': 'foreign'}, {'namespace': 'foreign'}, {'entity': 'bob'}):
            with self.subTest(scope=scope), self.fixture() as args:
                flow, before, old, _, _, original, _ = args
                changed = old[:]
                changed[3:35] = views.binding(lifecycle.schema(original), **scope)
                before['state-view'] = token(changed)
                with self.assertRaisesRegex(ValueError, 'original-pre-schema-query-minimum'):
                    self.observe(*args)
                flow.transport.request.assert_not_called()

    def test_current_schema_minimum_and_future_generation_are_not_old_history(self):
        for current in (True, False):
            with self.subTest(current=current), self.fixture() as args:
                flow, before, old, migrated = args[:4]
                altered = migrated if current else views.number(old, 43, int.from_bytes(bytes(old[43:51]), 'little') + 1)
                before['state-view'] = token(altered)
                with self.assertRaisesRegex(ValueError, 'original-pre-schema-query-minimum'):
                    self.observe(*args)
                flow.transport.request.assert_not_called()

    def test_minimum_incarnation_schema_and_recovery_epoch_mismatches_are_fatal(self):
        for offset in (35, 51, 59):
            with self.subTest(offset=offset), self.fixture() as args:
                flow, before, old = args[:3]
                before['state-view'] = token(views.number(old, offset, 2))
                with self.assertRaisesRegex(ValueError, 'original-pre-schema-query-minimum'):
                    self.observe(*args)
                flow.transport.request.assert_not_called()

    def test_malformed_missing_and_nonquery_original_minima_are_fatal(self):
        for changed in (None, '', 'not-base64', token([0] * 67)):
            with self.subTest(changed=changed), self.fixture() as args:
                flow, before = args[:2]
                before['state-view'] = changed
                with self.assertRaises((ValueError, TypeError)):
                    self.observe(*args)
                flow.transport.request.assert_not_called()
        with self.fixture() as args:
            args[1]['disposition'] = 'committed'
            with self.assertRaises(ValueError):
                self.observe(*args)
            args[0].transport.request.assert_not_called()

    def test_native_scope_or_recovery_transition_cannot_substitute_for_schema_migration(self):
        for offset in (3, 35, 59):
            with self.subTest(offset=offset), self.fixture() as args:
                changed = list(args)
                changed[3] = args[3][:]
                changed[3][offset] ^= 1
                with self.assertRaises(ValueError):
                    self.observe(*changed)
                args[0].transport.request.assert_not_called()

    def test_foreign_stale_or_wrong_epoch_success_cannot_precede_the_negative_query(self):
        for offset in (3, 35, 51, 59, 43):
            with self.subTest(offset=offset), self.fixture() as args:
                flow, _, old, migrated, ready = args[:5]
                altered = ready[:]
                if offset == 43:
                    altered = views.number(ready, 43, int.from_bytes(bytes(migrated[43:51]), 'little') - 1)
                else:
                    altered[offset] ^= 1
                flow.transport.request.side_effect = [fresh(altered), unavailable()]
                with self.assertRaises(ValueError):
                    self.observe(*args)
                self.assertEqual(flow.transport.request.call_count, 1)
                flow.client.evidence.passed.assert_not_called()

    def test_changed_ready_view_after_refusal_cannot_claim_no_mutation(self):
        with self.fixture() as args:
            flow, _, _, _, ready = args[:5]
            changed = views.number(ready, 43, int.from_bytes(bytes(ready[43:51]), 'little') + 1)
            flow.transport.request.side_effect = [fresh(ready), unavailable(), fresh(changed)]
            with self.assertRaisesRegex(ValueError, 'preserves-ready-view'):
                self.observe(*args)
            self.assertEqual(flow.transport.request.call_count, 3)
            flow.client.evidence.passed.assert_not_called()

    def test_transport_or_following_query_failure_is_never_retried_or_recorded(self):
        for ordinal in (0, 1, 2):
            with self.subTest(ordinal=ordinal), self.fixture() as args:
                flow, _, _, _, ready = args[:5]
                values = [fresh(ready), unavailable(), fresh(ready)]
                values[ordinal] = RuntimeError('original-transport-failure')
                flow.transport.request.side_effect = values
                with self.assertRaisesRegex(RuntimeError, 'original-transport-failure'):
                    self.observe(*args)
                self.assertEqual(flow.transport.request.call_count, ordinal + 1)
                flow.client.evidence.passed.assert_not_called()

    def test_wrong_service_and_unrelated_503_contexts_do_not_expand_generic_refusal(self):
        with self.fixture() as args:
            flow = args[0]
            flow.service = cfg.EARLY_HTTP_SERVICE
            with self.assertRaisesRegex(ValueError, 'current-terminal-schema-minimum'):
                self.observe(*args)
            flow.transport.request.assert_not_called()
            with self.assertRaisesRegex(ValueError, 'actual-redacted-http-platform-refusal'):
                flow.refusal('unrelated-refusal', unavailable(), {409})
            flow.refusal('future-generation-conflict', {'status': 409, 'body': b'Conflict\n'}, {409})
            self.assertEqual(flow.client.evidence.passed.call_args.args[0], 'future-generation-conflict')

    def test_current_callsite_uses_helper_and_legacy_preserves_sole_original_409(self):
        with self.fixture() as args:
            _, before, old, migrated, ready, original, target = args
            for current in (True, False):
                subject = offline_campaign.OfflineCampaign.__new__(offline_campaign.OfflineCampaign)
                subject.current_v2, subject.writer, subject.configuration = current, 'put-once-writer-v2', 'config'
                subject.campaign = SimpleNamespace(query=Mock(side_effect=[(before, None), ({'state-view': token(ready)}, None)]),
                    items={'put-once-legacy-v1': original, 'put-once-writer-v2': target},
                    publications={'put-once-compatible-v2': 'compatible'}, signed='signed',
                    proposals={'deploymentGrants': []}, configuration=SimpleNamespace(authority='authority'),
                    refusal=Mock(), socket=Mock(return_value={'status': 409}), client=SimpleNamespace(evidence=Mock()))
                subject.node = Mock(spec=['start'])
                subject.client = SimpleNamespace(evidence=Mock())
                subject.publication = 'writer'
                subject.recipient, subject.quiesce, subject.originals = Mock(return_value={}), Mock(), Mock()
                subject.inspect = Mock(side_effect=[{'view': old}, {'view': migrated}])
                subject.snapshot = Mock(return_value=({'root': 'snapshot'}, {'snapshotDigest': 's', 'manifestDigest': 'm'}))
                subject.action = Mock(side_effect=[{'completed': False}, {'completed': True}, {}])
                with self.subTest(current=current), patch.object(lifecycle, 'deploy'), \
                        patch.object(schema_view, 'advanced'), patch.object(offline_campaign, 'epoch_advanced'), \
                        patch.object(schema_view, 'minimum_refused', return_value={'state-view': token(ready)}) as checked:
                    subject.schema(4)
                if current:
                    checked.assert_called_once_with(subject.campaign, 4, before, old, migrated, original, target)
                    subject.campaign.refusal.assert_not_called()
                    subject.campaign.socket.assert_not_called()
                else:
                    checked.assert_not_called()
                    subject.campaign.refusal.assert_called_once_with('schema-refuses-stale-query-minimum', {'status': 409}, {409})
                    subject.campaign.socket.assert_called_once_with('query', minimum=before['state-view'])

    def test_real_http_normal_return_omits_loss_flag_while_explicit_malformed_flags_fail(self):
        with self.fixture() as args:
            flow, before, _, _, ready = args[:5]
            flow.transport = http.Http('localhost:52027', http.time.monotonic() + 30)
            connections, responses, returned = [], [], []
            for value in (fresh(ready), unavailable(), fresh(ready)):
                response = Mock(status=value['status'])
                response.getheaders.return_value = value['headers']
                response.read.return_value = value['body']
                connection = Mock()
                connection.getresponse.return_value = response
                connections.append(connection)
                responses.append(response)
            original_request = flow.transport.request
            def capture_return(*args, **kwargs):
                value = original_request(*args, **kwargs)
                returned.append(value)
                return value
            with patch.object(http.http.client, 'HTTPConnection', side_effect=connections) as opened, \
                    patch.object(flow.transport, 'request', side_effect=capture_return):
                observed = self.observe(*args)
            self.assertEqual(http.view_token(observed['state-view']), bytes(ready))
            self.assertEqual(opened.call_count, 3)
            self.assertEqual(flow.transport.requests, 3)
            self.assertEqual(len(returned), 3)
            self.assertTrue(all(set(value) == {'status', 'headers', 'body'} for value in returned))
            self.assertEqual(returned[1]['body'], b'Unavailable\n')
            for connection, response in zip(connections, responses, strict=True):
                connection.putrequest.assert_called_once_with('GET', '/transaction/query', skip_host=True)
                connection.endheaders.assert_called_once_with(None)
                connection.close.assert_called_once_with()
                response.read.assert_called_once_with(http.MAX_BODY + 1)
            minimum_headers = [row.args for row in connections[1].putheader.call_args_list
                               if row.args[0] == 'If-State-View']
            self.assertEqual(minimum_headers, [('If-State-View', before['state-view'])])
            records = [row.args[1] for row in flow.client.evidence.record.call_args_list
                       if row.args[0].endswith('-response')]
            self.assertEqual(len(records), 3)
            self.assertTrue(all(row['bodyLost'] is False for row in records))
            flow.client.evidence.passed.assert_called_once()
        for flag in (None, True, 0, 1, 'false', []):
            with self.subTest(flag=flag), self.fixture() as args:
                flow, _, _, _, ready = args[:5]
                refusal = unavailable()
                refusal['bodyLost'] = flag
                flow.transport.request.side_effect = [fresh(ready), refusal]
                with self.assertRaisesRegex(ValueError, 'actual-incompatible-schema-minimum-refusal'):
                    self.observe(*args)
                self.assertEqual(flow.transport.request.call_count, 2)
                flow.client.evidence.passed.assert_not_called()


if __name__ == '__main__':
    unittest.main()
