"""Synthetic restore-refusal controls; native history tests own runtime evidence."""
from contextlib import contextmanager
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from tools.java_transaction_qualification import campaign, configuration as cfg, http
from tools.java_transaction_qualification import lifecycle, offline_campaign, restored_view
from tools.java_transaction_qualification.evidence import encoded
from tools.tests import test_java_schema_minimum_refusal as responses
from tools.tests import test_java_schema_view as views


class RestoredMinimumRefusalControls(unittest.TestCase):
    @contextmanager
    def fixture(self):
        with views.SchemaViewControls().descriptors() as (_, writer_view, _, writer):
            # Explicitly reconstructed history, not a captured restore receipt.
            # Lost history can have a greater generation than restored history.
            old = views.number(views.number(writer_view, 43, 90), 59, 7)
            inspected = views.number(views.number(old, 43, 4), 59, 8)
            resumed = views.number(inspected, 43, 5)
            ready = views.number(resumed, 43, 6)
            before = {'disposition': 'query', 'state-view': responses.token(old)}
            flow = campaign.Campaign.__new__(campaign.Campaign)
            flow.service, flow.request_count = cfg.SERVICE, 0
            flow.client = SimpleNamespace(evidence=Mock())
            flow.transport = Mock()
            flow.transport.request.side_effect = [responses.fresh(ready), responses.unavailable(), responses.fresh(ready)]
            yield flow, before, inspected, resumed, ready, writer

    def observe(self, flow, before, inspected, resumed, ready, writer):
        recovered, _ = flow.query(4)
        return restored_view.minimum_refused(flow, 4, before, inspected, resumed, recovered, writer)

    def test_original_409_guard_is_red_and_restore_specific_refusal_uses_real_query_parser(self):
        with self.fixture() as args:
            flow, before, inspected, _, ready, _ = args
            with self.assertRaisesRegex(ValueError, 'actual-redacted-http-platform-refusal'):
                flow.refusal('restore-refuses-stale-query-minimum', responses.unavailable(), {409})
            recovered = self.observe(*args)
            self.assertEqual(http.view_token(recovered['state-view']), bytes(ready))
            self.assertGreater(int.from_bytes(http.view_token(before['state-view'])[43:51], 'little'),
                               int.from_bytes(bytes(inspected[43:51]), 'little'))
            self.assertEqual(flow.transport.request.call_count, 3)
            passed = flow.client.evidence.passed.call_args
            self.assertEqual(passed.args[0], 'restore-refuses-stale-query-minimum')
            self.assertEqual(passed.args[1]['underlyingPlatformError'], 'unobserved-redacted-http')
            self.assertEqual(passed.args[1]['freshQueryBefore'], recovered)
            self.assertEqual(passed.args[1]['freshQueryAfter'], recovered)

    def test_three_queries_keep_alice_original_minimum_and_no_command_or_body(self):
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
            inputs = [row.args[1] for row in flow.client.evidence.record.call_args_list
                      if row.args[0].endswith('-input')]
            self.assertEqual(len(inputs), 3)
            self.assertTrue(all(row['subject'] == cfg.ALICE and row['originalClientKey'] is None
                and row['originalPrecondition'] is None and row['bodyBase64'] is None for row in inputs))

    def test_each_minimum_native_and_ready_token_requires_exact_writer_scope(self):
        scopes = ({'tenant': 'foreign'}, {'namespace': 'foreign'}, {'entity': 'alice'}, {'incarnation': 2})
        for position in range(4):
            for scope in scopes:
                with self.subTest(position=position, scope=scope), self.fixture() as args:
                    flow, before, inspected, resumed, ready, writer = args
                    tokens = [list(http.view_token(before['state-view'])), inspected[:], resumed[:], ready[:]]
                    tokens[position][3:35] = views.binding(lifecycle.schema(writer), **scope)
                    if 'incarnation' in scope:
                        tokens[position] = views.number(tokens[position], 35, 2)
                    before['state-view'] = responses.token(tokens[0])
                    flow.transport.request.side_effect = [responses.fresh(tokens[3]), responses.unavailable()]
                    with self.assertRaisesRegex(ValueError, 'restored-query-scope-binding'):
                        self.observe(flow, before, tokens[1], tokens[2], tokens[3], writer)
                    self.assertEqual(flow.transport.request.call_count, 1)
                    flow.client.evidence.passed.assert_not_called()

    def test_even_matching_foreign_or_old_schema_tokens_do_not_replace_writer_companion(self):
        old_schema = json.loads(views.FIXTURE.read_bytes())['previous']['stateSchema']
        for schema in (old_schema, 'sha256:' + 'a' * 64):
            with self.subTest(schema=schema), self.fixture() as args:
                flow, before, inspected, resumed, ready, writer = args
                tokens = [list(http.view_token(before['state-view'])), inspected[:], resumed[:], ready[:]]
                for value in tokens:
                    value[3:35] = views.binding(schema)
                before['state-view'] = responses.token(tokens[0])
                flow.transport.request.side_effect = [responses.fresh(tokens[3]), responses.unavailable()]
                with self.assertRaisesRegex(ValueError, 'restored-query-scope-binding'):
                    self.observe(flow, before, tokens[1], tokens[2], tokens[3], writer)
                self.assertEqual(flow.transport.request.call_count, 1)

    def test_retained_writer_companion_changed_or_missing_is_fatal(self):
        for missing in (False, True):
            with self.subTest(missing=missing), self.fixture() as args:
                path = args[5].directory / 'project/transaction-binding.json'
                if missing:
                    path.unlink()
                else:
                    path.write_bytes(path.read_bytes() + b' ')
                with self.assertRaises((ValueError, OSError)):
                    self.observe(*args)
                self.assertEqual(args[0].transport.request.call_count, 1)
                args[0].client.evidence.passed.assert_not_called()

    def test_schema_epoch_mismatch_at_each_boundary_is_not_this_restore(self):
        for position in range(4):
            with self.subTest(position=position), self.fixture() as args:
                flow, before, inspected, resumed, ready, writer = args
                tokens = [list(http.view_token(before['state-view'])), inspected[:], resumed[:], ready[:]]
                epoch = int.from_bytes(bytes(tokens[position][51:59]), 'little')
                tokens[position] = views.number(tokens[position], 51, epoch + 1)
                before['state-view'] = responses.token(tokens[0])
                flow.transport.request.side_effect = [responses.fresh(tokens[3]), responses.unavailable()]
                with self.assertRaisesRegex(ValueError, 'restored-query-recovery-history'):
                    self.observe(flow, before, tokens[1], tokens[2], tokens[3], writer)
                self.assertEqual(flow.transport.request.call_count, 1)

    def test_unchanged_regressed_or_inconsistent_recovery_epoch_never_sends_stale_minimum(self):
        for position, epoch in ((0, 8), (0, 9), (1, 6), (2, 9), (3, 9)):
            with self.subTest(position=position, epoch=epoch), self.fixture() as args:
                flow, before, inspected, resumed, ready, writer = args
                tokens = [list(http.view_token(before['state-view'])), inspected[:], resumed[:], ready[:]]
                tokens[position] = views.number(tokens[position], 59, epoch)
                before['state-view'] = responses.token(tokens[0])
                flow.transport.request.side_effect = [responses.fresh(tokens[3]), responses.unavailable()]
                with self.assertRaisesRegex(ValueError, 'restored-query-recovery-history'):
                    self.observe(flow, before, tokens[1], tokens[2], tokens[3], writer)
                self.assertEqual(flow.transport.request.call_count, 1)

    def test_current_history_or_its_future_generation_minimum_cannot_be_the_old_history_case(self):
        for generation in (6, 7):
            with self.subTest(generation=generation), self.fixture() as args:
                args[1]['state-view'] = responses.token(views.number(args[4], 43, generation))
                with self.assertRaisesRegex(ValueError, 'restored-query-recovery-history'):
                    self.observe(*args)
                self.assertEqual(args[0].transport.request.call_count, 1)

    def test_first_resume_must_advance_exactly_once_without_generation_overflow(self):
        for inspected_generation, resumed_generation in ((4, 4), (4, 3), (4, 6), (2**64 - 1, 1)):
            with self.subTest(inspected=inspected_generation, resumed=resumed_generation), self.fixture() as args:
                flow, before, inspected, resumed, ready, writer = args
                with self.assertRaisesRegex(ValueError, 'actual-ready-restored-query-view'):
                    self.observe(flow, before, views.number(inspected, 43, inspected_generation),
                                 views.number(resumed, 43, resumed_generation), ready, writer)
                self.assertEqual(flow.transport.request.call_count, 1)

    def test_fresh_ready_generation_cannot_precede_actual_native_resume(self):
        with self.fixture() as args:
            flow, _, inspected, _, ready, _ = args
            altered = views.number(ready, 43, int.from_bytes(bytes(inspected[43:51]), 'little'))
            flow.transport.request.side_effect = [responses.fresh(altered), responses.unavailable()]
            with self.assertRaisesRegex(ValueError, 'actual-ready-restored-query-view'):
                self.observe(*args)
            self.assertEqual(flow.transport.request.call_count, 1)

    def test_malformed_minimum_native_tokens_and_nonquery_original_are_fatal(self):
        for value in (None, '', 'not-base64', responses.token([0] * 67)):
            with self.subTest(minimum=value), self.fixture() as args:
                args[1]['state-view'] = value
                with self.assertRaises((ValueError, TypeError)):
                    self.observe(*args)
                self.assertEqual(args[0].transport.request.call_count, 1)
        for position in (2, 3):
            for value in (None, [True] * 67, [0] * 67, [0] * 66):
                with self.subTest(position=position, native=value), self.fixture() as args:
                    changed = list(args)
                    changed[position] = value
                    with self.assertRaises((ValueError, TypeError)):
                        self.observe(*changed)
                    self.assertEqual(args[0].transport.request.call_count, 1)
        with self.fixture() as args:
            args[1]['disposition'] = 'committed'
            with self.assertRaisesRegex(ValueError, 'restored-query-scope-binding'):
                self.observe(*args)

    def test_200_403_409_other_gateway_codes_and_noninteger_status_do_not_qualify(self):
        for status in (200, 403, 409, 500, 502, 504, True, 503.0):
            with self.subTest(status=status), self.fixture() as args:
                flow, _, _, _, ready, _ = args
                refusal = responses.unavailable()
                refusal['status'] = status
                flow.transport.request.side_effect = [responses.fresh(ready), refusal]
                with self.assertRaisesRegex(ValueError, 'actual-incompatible-restore-minimum-refusal'):
                    self.observe(*args)
                self.assertEqual(flow.transport.request.call_count, 2)
                flow.client.evidence.passed.assert_not_called()

    def test_wrong_missing_or_application_body_and_every_malformed_loss_flag_are_fatal(self):
        changes = [('body', b''), ('body', b'Unavailable'), ('body', b'Forbidden\n'),
                   ('body', b'{"error":"unavailable"}'), ('body', None)]
        changes += [('bodyLost', flag) for flag in (True, None, 0, 1, 'false', [])]
        for field, value in changes:
            with self.subTest(field=field, value=value), self.fixture() as args:
                flow, _, _, _, ready, _ = args
                refusal = responses.unavailable()
                refusal[field] = value
                flow.transport.request.side_effect = [responses.fresh(ready), refusal]
                with self.assertRaisesRegex(ValueError, 'actual-incompatible-restore-minimum-refusal'):
                    self.observe(*args)
                self.assertEqual(flow.transport.request.call_count, 2)
                flow.client.evidence.passed.assert_not_called()

    def test_wrong_count_or_unhealthy_query_on_either_side_is_not_masked_by_refusal(self):
        for ordinal in (0, 2):
            for unhealthy in (False, True):
                with self.subTest(ordinal=ordinal, unhealthy=unhealthy), self.fixture() as args:
                    flow, _, _, _, ready, _ = args
                    values = [responses.fresh(ready), responses.unavailable(), responses.fresh(ready)]
                    values[ordinal] = responses.unavailable() if unhealthy else responses.fresh(ready, 5)
                    flow.transport.request.side_effect = values
                    with patch('tools.java_transaction_qualification.refusal_observation.observe'), \
                            self.assertRaises(ValueError):
                        self.observe(*args)
                    self.assertEqual(flow.transport.request.call_count, ordinal + 1)
                    flow.client.evidence.passed.assert_not_called()

    def test_changed_ready_generation_scope_or_epochs_after_refusal_cannot_claim_stability(self):
        for offset in (3, 35, 43, 51, 59):
            with self.subTest(offset=offset), self.fixture() as args:
                flow, _, _, _, ready, _ = args
                altered = ready[:]
                altered[offset] ^= 1
                if offset == 35:
                    altered = views.number(ready, 35, 2)
                flow.transport.request.side_effect = [responses.fresh(ready), responses.unavailable(), responses.fresh(altered)]
                with self.assertRaisesRegex(ValueError, 'restore-minimum-refusal-preserves-ready-view'):
                    self.observe(*args)
                self.assertEqual(flow.transport.request.call_count, 3)
                flow.client.evidence.passed.assert_not_called()

    def test_each_original_transport_error_propagates_without_retry_or_passed_case(self):
        for ordinal in (0, 1, 2):
            with self.subTest(ordinal=ordinal), self.fixture() as args:
                flow, _, _, _, ready, _ = args
                values = [responses.fresh(ready), responses.unavailable(), responses.fresh(ready)]
                values[ordinal] = RuntimeError('original-transport-failure')
                flow.transport.request.side_effect = values
                with self.assertRaisesRegex(RuntimeError, 'original-transport-failure'):
                    self.observe(*args)
                self.assertEqual(flow.transport.request.call_count, ordinal + 1)
                flow.client.evidence.passed.assert_not_called()

    def test_wrong_caller_cannot_supply_the_left_healthy_query(self):
        with self.fixture() as args:
            flow = args[0]
            original_socket = flow.socket
            def wrong_caller(mode, **kwargs):
                return original_socket(mode, subject=cfg.BOB)
            flow.socket = wrong_caller
            flow.transport.request.side_effect = None
            flow.transport.request.return_value = {'status': 403, 'body': b'Forbidden\n', 'headers': []}
            with patch('tools.java_transaction_qualification.refusal_observation.observe'), self.assertRaises(ValueError):
                self.observe(*args)
            self.assertEqual(flow.transport.request.call_count, 1)
            self.assertEqual(flow.transport.request.call_args.kwargs['headers'][0],
                             ('Authorization', 'Bearer ' + cfg.TOKENS[cfg.BOB]))
            flow.client.evidence.passed.assert_not_called()

    def test_other_service_and_generic_refusal_keep_original_403_409_contract(self):
        with self.fixture() as args:
            flow = args[0]
            flow.service = cfg.EARLY_HTTP_SERVICE
            with self.assertRaisesRegex(ValueError, 'current-terminal-restore-minimum'):
                self.observe(*args)
            self.assertEqual(flow.transport.request.call_count, 1)
            with self.assertRaisesRegex(ValueError, 'actual-redacted-http-platform-refusal'):
                flow.refusal('unrelated-refusal', responses.unavailable(), {409})
            for status, body in ((403, b'Forbidden\n'), (409, b'Conflict\n')):
                flow.refusal('original-generic-refusal', {'status': status, 'body': body}, {status})
            self.assertEqual(flow.client.evidence.passed.call_count, 2)

    def test_real_bounded_http_normal_return_omits_loss_flag_and_closes_all_three_connections(self):
        with self.fixture() as args:
            flow, before, _, _, ready, _ = args
            flow.transport = http.Http('localhost:52027', http.time.monotonic() + 30, maximum_requests=3)
            original_deadline = flow.transport.deadline
            connections, returned = [], []
            for value in (responses.fresh(ready), responses.unavailable(), responses.fresh(ready)):
                response = Mock(status=value['status'])
                response.getheaders.return_value = value['headers']
                response.read.return_value = value['body']
                connection = Mock()
                connection.getresponse.return_value = response
                connections.append(connection)
            original_request = flow.transport.request
            def capture_return(*args, **kwargs):
                value = original_request(*args, **kwargs)
                returned.append(value)
                return value
            with patch.object(http.http.client, 'HTTPConnection', side_effect=connections) as opened, \
                    patch.object(flow.transport, 'request', side_effect=capture_return):
                self.observe(*args)
            self.assertEqual(flow.transport.deadline, original_deadline)
            self.assertEqual(flow.transport.requests, 3)
            self.assertEqual(opened.call_count, 3)
            self.assertTrue(all(set(value) == {'status', 'headers', 'body'} for value in returned))
            for connection in connections:
                connection.putrequest.assert_called_once_with('GET', '/transaction/query', skip_host=True)
                connection.endheaders.assert_called_once_with(None)
                connection.close.assert_called_once_with()
                connection.getresponse.return_value.read.assert_called_once_with(http.MAX_BODY + 1)
            self.assertIn(('If-State-View', before['state-view']),
                          [row.args for row in connections[1].putheader.call_args_list])
            with self.assertRaisesRegex(ValueError, 'http-campaign-request-bound'):
                flow.transport.request('GET', '/transaction/query')

    def test_actual_restore_callsite_uses_existing_left_query_and_keeps_legacy_refusal_and_native_actions(self):
        for current in (True, False):
            with self.subTest(current=current), self.fixture() as args, tempfile.TemporaryDirectory() as temporary:
                flow, before, inspected, resumed, ready, writer = args
                directory = Path(temporary).resolve()
                subject = offline_campaign.OfflineCampaign.__new__(offline_campaign.OfflineCampaign)
                subject.directory, subject.current_v2 = directory, current
                subject.campaign, subject.client = flow, flow.client
                subject.writer, subject.publication = 'put-once-writer-v2', 'writer'
                subject.configuration = directory / 'original-node.json'
                subject.migration_operation = 'java-schema-v1-to-v2' if current else None
                subject.node = SimpleNamespace(current_publication_program=current,
                    current_activation=object() if current else None, start=Mock())
                subject.recipient, subject.quiesce, subject.originals = Mock(return_value={}), Mock(), Mock()
                subject.refresh_authority, subject.inspect = Mock(), Mock(return_value={'view': inspected})
                flow.items, flow.full_path = {subject.writer: writer}, directory / 'full-node.json'
                old = list(http.view_token(before['state-view']))
                changed = responses.result('committed', '5')
                flow.wait_effect = Mock()
                refusal = responses.unavailable() if current else {'status': 409, 'body': b'Conflict\n', 'headers': []}
                sequence = [responses.fresh(old), {'status': 200, 'body': encoded(changed), 'headers': responses.HEADERS},
                            responses.fresh(old, 5), responses.fresh(ready), refusal]
                if current:
                    sequence.append(responses.fresh(ready))
                sequence.append({'status': 404, 'body': b'Not found\n', 'headers': []})
                flow.transport.request.side_effect = sequence
                settings = {'dataDirectory': str(directory / 'source-data'),
                    'state': {'checkpointRoot': str(directory / 'source-checkpoint'), 'formatVersion': 2 if current else 1}}
                snapshot = {'snapshotDigest': 'sha256:' + '1' * 64, 'manifestDigest': 'sha256:' + '2' * 64}
                file = {'root': str(directory / 'snapshot-root'), 'name': 'original.snapshot'}
                acknowledgement, review = 'sha256:' + '3' * 64, 'sha256:' + '4' * 64
                def action(request):
                    if request['action'] == 'inspect-restore':
                        return {'snapshot': snapshot, 'windowDigest': acknowledgement}
                    if request['action'] == 'restore':
                        Path(request['destinationRoot']).mkdir(parents=True)
                        return dict(snapshot, destinationIdentity='original-destination')
                    if request['action'] == 'review':
                        return {'reviewDigest': review}
                    self.assertIn(request['action'], ('resume', 'resume-restored-migration'))
                    return dict(snapshot, action=request['action'], receipt=list(b'RMA\x01synthetic-receipt'),
                        view=resumed, replay=False, windowAcknowledgement=acknowledgement,
                        reviewDigest=review, resourcePhysicallyRetired=True)
                subject.action = Mock(side_effect=action)
                with patch.object(offline_campaign, 'read_json', return_value=settings), \
                        patch.object(offline_campaign.restore_installation, 'requested_identity', return_value='original-destination'), \
                        patch.object(offline_campaign.restore_installation, 'catalogs', return_value={}), \
                        patch.object(offline_campaign.restore_installation, 'selection', return_value=settings), \
                        patch('tools.java_transaction_qualification.restore_destination_roots.provision', return_value={}), \
                        patch.object(restored_view, 'minimum_refused', wraps=restored_view.minimum_refused) as checked, \
                        patch.object(flow, 'refusal', wraps=flow.refusal) as generic:
                    subject.restore(4, file, snapshot, before)
                if current:
                    checked.assert_called_once()
                    self.assertEqual(checked.call_args.args[:5], (flow, 4, before, inspected, resumed))
                    self.assertEqual(http.view_token(checked.call_args.args[5]['state-view']), bytes(ready))
                    self.assertIs(checked.call_args.args[6], writer)
                    generic.assert_not_called()
                    subject.refresh_authority.assert_called_once_with(settings)
                else:
                    checked.assert_not_called()
                    generic.assert_called_once_with('restore-refuses-stale-query-minimum', refusal, {409})
                    subject.refresh_authority.assert_not_called()
                self.assertEqual([row.args[0]['action'] for row in subject.action.call_args_list],
                    ['inspect-restore', 'restore', 'review', 'resume-restored-migration' if current else 'resume'])
                self.assertEqual(flow.transport.request.call_count, 7 if current else 6)
                self.assertEqual([row.args for row in flow.transport.request.call_args_list].count(('POST', '/transaction/command')), 1)
                subject.originals.assert_called_once_with('restore')
                flow.wait_effect.assert_called_once_with('writer', 'java-after-restore-checkpoint', changed)
                subject.node.start.assert_called_once()

    def test_terminal_pending_and_early_collector_identities_bind_new_helper_bytes(self):
        from tools import run_java_transaction_http_qualification as terminal
        from tools import run_java_pending_recovery_qualification as pending
        from tools import run_java_early_http_qualification as early
        root = Path(__file__).resolve().parents[2]
        name = 'tools/java_transaction_qualification/restored_view.py'
        self.assertEqual(terminal.COLLECTORS.count(name), 1)
        self.assertEqual(terminal.COLLECTORS[-1],
                         'docs/testing/evidence/java-current-http-reconstructed-capture-2026-10-15.json')
        with tempfile.TemporaryDirectory() as temporary:
            copied = Path(temporary)
            for path in dict.fromkeys(terminal.COLLECTORS + pending.EXTRA_COLLECTORS + early.EXTRA_COLLECTORS):
                destination = copied / path
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes((root / path).read_bytes())
            with patch.object(terminal, '__file__', str(copied / 'tools/run_java_transaction_http_qualification.py')), \
                    patch.object(pending, '__file__', str(copied / 'tools/run_java_pending_recovery_qualification.py')), \
                    patch.object(early, '__file__', str(copied / 'tools/run_java_early_http_qualification.py')):
                before = [module.collector_identity() for module in (terminal, pending, early)]
                helper = copied / name
                helper.write_bytes(helper.read_bytes() + b'\n')
                after = [module.collector_identity() for module in (terminal, pending, early)]
            for original, changed in zip(before, after, strict=True):
                self.assertNotEqual(original[name], changed[name])
                self.assertEqual({key: value for key, value in original.items() if key != name},
                                 {key: value for key, value in changed.items() if key != name})


if __name__ == '__main__':
    unittest.main()
