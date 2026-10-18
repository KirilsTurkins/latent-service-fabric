"""Namespace observations require real closed success within one original cutoff."""
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from tools.java_transaction_qualification import campaign, lifecycle, read_observer
from tools.java_transaction_qualification.evidence import Evidence, RecordingClient, encoded
from tools.tests.java_read_observer_fixtures import Clock, PUBLICATION, busy, reply


def inspected(count='8'):
    return reply('state inspect', {'namespace': {'commandCount': count, 'stateBytes': '75', 'generation': '17'}})


def client(clock, *responses):
    return SimpleNamespace(call=Mock(side_effect=responses), deadline=clock.now + 1000,
                           config=Path('same-operator-config'), subject='same-operator')


def recording(clock, directory, responses, *, calls=0):
    value = RecordingClient.__new__(RecordingClient)
    value.cancellation, value.calls, value.deadline = Mock(), calls, clock.now + 1000
    value.node, value.config, value.phase4 = None, Path('same-operator-config'), True
    value.executable, value.directory, value.environment = Path('synthetic-cli'), directory, {}
    value.evidence = Evidence(directory / 'retained')
    created, completed = [], []
    responses = iter(responses)

    class Process:
        def __init__(self, arguments, *args, **kwargs):
            self.value = next(responses)
            self.buffers = (encoded(self.value), b'')
            self.status = 5 if self.value['category'] == 'transport-failure' else 0
            self.owner = SimpleNamespace(process=SimpleNamespace(returncode=self.status), finished=False)
            self.closed = False
            created.append(arguments)
            clock.now += 3

        def complete(self, deadline):
            completed.append(deadline)
            return SimpleNamespace(stdout=self.buffers[0], returncode=self.status)

        def close(self):
            self.closed, self.owner.finished = True, True

    return value, Process, created, completed


class NamespaceReadBackpressureControls(unittest.TestCase):
    def test_single_real_success_keeps_original_namespace_and_operator_request(self):
        clock = Clock()
        response = inspected()
        observed = client(clock, response)
        with clock.installed(lifecycle):
            self.assertIs(lifecycle.inspect_namespace(observed, PUBLICATION), response['data']['namespace'])
        observed.call.assert_called_once_with('state', 'inspect', '--namespace', lifecycle.cfg.NAMESPACE,
            '--incarnation', '1', '--authorization-publication', PUBLICATION,
            codes=(0, 5), timeout=25, cutoff=125.)
        self.assertEqual((observed.config, observed.subject), (Path('same-operator-config'), 'same-operator'))
        self.assertEqual(clock.sleeps, [])

    def test_busy_then_success_keeps_one_original_cutoff_and_identical_request(self):
        clock = Clock()
        observed = client(clock, busy('state inspect'), inspected())
        with clock.installed(lifecycle):
            self.assertEqual(lifecycle.inspect_namespace(observed, PUBLICATION)['commandCount'], '8')
        first, second = observed.call.call_args_list
        self.assertEqual(first.args, second.args)
        self.assertEqual(first.kwargs['cutoff'], second.kwargs['cutoff'])
        self.assertEqual(first.kwargs['timeout'], 25.)
        self.assertAlmostEqual(second.kwargs['timeout'], 24.95)
        self.assertEqual(clock.sleeps, [.05])

    def test_eight_busy_reads_fail_without_a_namespace_or_a_ninth_attempt(self):
        clock = Clock()
        observed = client(clock, *[busy('state inspect') for _ in range(8)])
        with clock.installed(lifecycle), self.assertRaisesRegex(ValueError, 'namespace-inspection-read-bound'):
            lifecycle.inspect_namespace(observed, PUBLICATION)
        self.assertEqual(observed.call.call_count, 8)
        self.assertEqual(clock.sleeps, [.05] * 7)
        self.assertEqual(len({row.args for row in observed.call.call_args_list}), 1)
        self.assertTrue(all(row.kwargs['cutoff'] == 125. and row.kwargs['codes'] == (0, 5)
                            for row in observed.call.call_args_list))

    def test_global_deadline_is_not_renewed_by_a_busy_read(self):
        clock = Clock()
        observed = client(clock, busy('state inspect'), inspected())
        observed.deadline = clock.now + 1
        with clock.installed(lifecycle):
            lifecycle.inspect_namespace(observed, PUBLICATION)
        self.assertEqual([row.kwargs['cutoff'] for row in observed.call.call_args_list], [101., 101.])
        self.assertEqual(observed.call.call_args_list[0].kwargs['timeout'], 1.)
        self.assertAlmostEqual(observed.call.call_args_list[1].kwargs['timeout'], .95)

    def test_expired_and_late_success_cutoffs_never_supply_namespace_proof(self):
        clock = Clock()
        observed = client(clock, inspected())
        observed.deadline = clock.now
        with clock.installed(lifecycle), self.assertRaisesRegex(ValueError, 'namespace-inspection-cutoff'):
            lifecycle.inspect_namespace(observed, PUBLICATION)
        observed.call.assert_not_called()
        def late(*args, **kwargs):
            clock.now += 25
            return inspected()
        observed.call, observed.deadline = Mock(side_effect=late), clock.now + 1000
        with clock.installed(lifecycle), self.assertRaisesRegex(ValueError, 'namespace-inspection-cutoff'):
            lifecycle.inspect_namespace(observed, PUBLICATION)
        self.assertEqual(observed.call.call_count, 1)

    def test_busy_at_cutoff_and_sleep_crossing_cutoff_cannot_make_another_read(self):
        for elapsed in (25., 24.99):
            clock = Clock()
            def near_cutoff(*args, **kwargs):
                clock.now += elapsed
                return busy('state inspect')
            observed = client(clock)
            observed.call = Mock(side_effect=near_cutoff)
            with self.subTest(elapsed=elapsed), clock.installed(lifecycle), \
                    self.assertRaisesRegex(ValueError, 'namespace-inspection-cutoff'):
                lifecycle.inspect_namespace(observed, PUBLICATION)
            self.assertEqual(observed.call.call_count, 1)
            self.assertLessEqual(sum(clock.sleeps), .05)

    def test_other_errors_are_fatal_without_another_read(self):
        for code in ('unavailable', 'permission-denied', 'not-found', 'cancelled', 'deadline-exceeded'):
            clock = Clock()
            response = busy('state inspect')
            response['error']['grpcCode'] = code
            observed = client(clock, response, inspected())
            with self.subTest(code=code), clock.installed(lifecycle), self.assertRaises(ValueError):
                lifecycle.inspect_namespace(observed, PUBLICATION)
            self.assertEqual(observed.call.call_count, 1)
            self.assertEqual(clock.sleeps, [])

    def test_malformed_busy_envelopes_never_authorize_another_read(self):
        changes = [('schemaVersion', 'future'), ('command', 'state create'), ('requestDispatched', False),
            ('requestDispatched', 1), ('outcomeKnown', True), ('outcomeKnown', 0), ('category', 'future'),
            ('data', {'namespace': {}}), ('error', None), ('extra', False)]
        for field, changed in changes:
            self.fatal_response(field, changed)
        for field, changed in [('code', 'resource-exhausted'), ('grpcCode', 'RESOURCE_EXHAUSTED'),
                ('message', ''), ('retryable', True), ('details', [])]:
            value = busy('state inspect')
            value['error'][field] = changed
            self.fatal_value(value)

    def fatal_response(self, field, changed):
        value = busy('state inspect')
        value[field] = changed
        self.fatal_value(value)

    def fatal_value(self, value):
        clock = Clock()
        observed = client(clock, value, inspected())
        with clock.installed(lifecycle), self.assertRaises(ValueError):
            lifecycle.inspect_namespace(observed, PUBLICATION)
        self.assertEqual(observed.call.call_count, 1)
        self.assertEqual(clock.sleeps, [])

    def test_success_requires_known_result_and_original_namespace_count(self):
        for field, changed in [('outcomeKnown', False), ('error', {}), ('requestDispatched', False),
                ('category', 'not-found')]:
            value = inspected()
            value[field] = changed
            self.fatal_value(value)
        for data in ({}, {'namespace': None}, {'namespace': {}}, {'namespace': {'commandCount': '08'}},
                     {'namespace': {'commandCount': '-1'}}, {'namespace': {'commandCount': 8}}):
            clock = Clock()
            observed = client(clock, reply('state inspect', data), inspected())
            with self.subTest(data=data), clock.installed(lifecycle), self.assertRaises((ValueError, KeyError, TypeError)):
                lifecycle.inspect_namespace(observed, PUBLICATION)
            self.assertEqual(observed.call.call_count, 1)

    def test_namespace_classifier_does_not_expand_original_allowlist_or_mutation_authority(self):
        with self.assertRaisesRegex(ValueError, 'explicit-original-read-only-operation'):
            read_observer.kind(busy('state inspect'), 'state inspect')
        for command in ('state create', 'state quiesce', 'state resume', 'dispatcher pause',
                        'dispatcher operation', 'transaction cancel', 'transaction lookup', 'transaction effect'):
            with self.subTest(command=command), self.assertRaises(ValueError):
                read_observer.namespace_kind(busy(command))
        with self.assertRaises(ValueError):
            read_observer.namespace_kind(reply('state inspect', {}, category='not-found'))

    def test_invalid_publication_is_refused_before_any_read(self):
        clock = Clock()
        observed = client(clock, inspected())
        for publication in ('', 'publication:sha256:' + 'A' * 64, PUBLICATION + '0'):
            with self.subTest(publication=publication), clock.installed(lifecycle), self.assertRaises(ValueError):
                lifecycle.inspect_namespace(observed, publication)
        observed.call.assert_not_called()

    def test_real_recording_client_retains_busy_bytes_and_reaps_same_request(self):
        import hashlib
        clock = Clock()
        responses = [busy('state inspect'), inspected()]
        with tempfile.TemporaryDirectory() as temporary:
            observed, process, created, completed = recording(clock, Path(temporary), responses)
            with clock.installed(lifecycle), patch('tools.java_transaction_qualification.evidence.Process', process):
                self.assertEqual(lifecycle.inspect_namespace(observed, PUBLICATION)['commandCount'], '8')
            self.assertEqual(created[0], created[1])
            self.assertEqual(completed, [125., 125.])
            self.assertEqual(observed.calls, 2)
            for index, response in enumerate(responses, 1):
                raw = encoded(response)
                name = f'cli-{index:03d}.stdout'
                self.assertEqual((observed.evidence.directory / name).read_bytes(), raw)
                self.assertEqual((observed.evidence.directory / f'cli-{index:03d}-process.json').read_bytes(),
                    encoded({'exitStatus': 5 if index == 1 else 0, 'reaped': True,
                        'stdout': {'path': name, 'bytes': len(raw), 'digest': 'sha256:' + hashlib.sha256(raw).hexdigest()},
                        'stderr': {'empty': True, 'bytes': 0, 'digest': 'sha256:' + hashlib.sha256(b'').hexdigest()}}))
                self.assertFalse((observed.evidence.directory / f'cli-{index:03d}.stderr').exists())

    def test_original_256_call_limit_still_blocks_the_next_busy_observation(self):
        clock = Clock()
        with tempfile.TemporaryDirectory() as temporary:
            observed, process, created, _ = recording(clock, Path(temporary), [busy('state inspect')], calls=255)
            with clock.installed(lifecycle), patch('tools.java_transaction_qualification.evidence.Process', process), \
                    self.assertRaisesRegex(ValueError, 'original-cli-campaign-bound'):
                lifecycle.inspect_namespace(observed, PUBLICATION)
            self.assertEqual(observed.calls, 256)
            self.assertEqual(len(created), 1)
            self.assertTrue((observed.evidence.directory / 'cli-256.stdout').is_file())

    def test_original_cancellation_before_first_or_next_read_never_spawns_after_refusal(self):
        for before_first in (True, False):
            clock = Clock()
            with self.subTest(before_first=before_first), tempfile.TemporaryDirectory() as temporary:
                observed, process, created, _ = recording(clock, Path(temporary), [busy('state inspect')])
                observed.cancellation.check.side_effect = [ValueError('original-cancelled')] if before_first \
                    else [None, ValueError('original-cancelled')]
                with clock.installed(lifecycle), patch('tools.java_transaction_qualification.evidence.Process', process), \
                        self.assertRaisesRegex(ValueError, 'original-cancelled'):
                    lifecycle.inspect_namespace(observed, PUBLICATION)
                self.assertEqual(len(created), 0 if before_first else 1)

    def test_process_failure_is_not_caught_or_retried(self):
        clock = Clock()
        observed = client(clock)
        observed.call.side_effect = RuntimeError('original-process-failure')
        with clock.installed(lifecycle), self.assertRaisesRegex(RuntimeError, 'original-process-failure'):
            lifecycle.inspect_namespace(observed, PUBLICATION)
        self.assertEqual(observed.call.call_count, 1)

    def test_real_campaign_still_compares_final_successful_count_after_all_four_refusals(self):
        for after_count in ('8', '9'):
            clock = Clock()
            observed = client(clock, inspected(), busy('state inspect'), inspected(after_count))
            observed.evidence = Mock()
            flow = campaign.Campaign.__new__(campaign.Campaign)
            flow.client = observed
            flow.query = Mock(return_value=(None, {'key-version': {'none': None}}))
            flow.socket = Mock(return_value={'body': b''})
            flow.refusal = Mock()
            with self.subTest(after_count=after_count), clock.installed(lifecycle):
                if after_count == '9':
                    with self.assertRaisesRegex(ValueError, 'foreign-caller-creates-no-command-row'):
                        flow._isolation_and_preconditions(PUBLICATION)
                else:
                    flow._isolation_and_preconditions(PUBLICATION)
            self.assertEqual(flow.query.call_count, 2)
            self.assertEqual(flow.refusal.call_count, 5)
            self.assertEqual([row.args[0] for row in flow.refusal.call_args_list[1:]],
                ['result-isolation-caller', 'command-isolation-caller', 'result-isolation-tenant', 'command-isolation-tenant'])
            final = [row for row in observed.evidence.passed.call_args_list if row.args[0] == 'isolation-preserves-durable-rows']
            self.assertEqual(len(final), 1 if after_count == '8' else 0)
            self.assertEqual(observed.call.call_count, 3)


if __name__ == '__main__':
    unittest.main()
