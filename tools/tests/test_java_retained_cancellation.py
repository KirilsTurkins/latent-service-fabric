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

    def switch(self, subject, name, *, retained_cancellation=False):
        assert subject is self.subject and subject.client.role == 'operator'
        assert retained_cancellation is True
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


class SessionFixture:
    """Real collector owners and guards with mocked processes, metadata and RPCs."""

    def __init__(self):
        from contextlib import ExitStack
        from pathlib import Path
        import tempfile
        import time
        from tools.java_transaction_qualification import configuration, evidence
        from tools.java_transaction_qualification.current_activation import CurrentActivation
        from tools.phase2_operator_process import write_json

        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name).resolve()
        self.stack = ExitStack()
        self.events, self.started, self.processes, self.cancel_calls = [], [], [], []
        self.failure, self.lease_calls, self.metadata_calls = None, 0, 0
        self.collector = evidence.Evidence(self.root / 'evidence')
        (self.root / 'client').mkdir()
        self.client = SimpleNamespace(phase4=True, directory=self.root / 'client', environment={},
            deadline=time.monotonic() + 120, cancellation=SimpleNamespace(check=Mock()),
            evidence=self.collector, role='operator', call=Mock(side_effect=self.call))
        self.node = lifecycle.Node(self.client, self.root / 'mock-node', self.root,
                                   current_publication_program=True)
        names = ('aggregate', 'put-once-legacy-v1', 'put-once-compatible-v2',
                 'put-once-writer-v2', 'put-once-diagnostics')
        self.publications = {name: 'publication:sha256:' + str(index + 1) * 64
                             for index, name in enumerate(names)}
        self.items = tuple(SimpleNamespace(name=name, component_digest='sha256:' + str(index + 5) * 64)
                           for index, name in enumerate(names))
        rows = [{'tenant': configuration.TENANT, 'contract': configuration.CONTRACT,
                 'binding': configuration.DEPLOYMENT, 'deployment': configuration.DEPLOYMENT,
                 'incarnation': 1, 'function': function, 'publication': self.publications[item.name],
                 'componentDigest': item.component_digest}
                for item in self.items for function in ('update', 'query', 'scan')]
        inspected = self.root / 'inspected.json'
        write_json(inspected, {'state': {'formatVersion': 2, 'operations': rows}})
        self.configuration = configuration.Configuration(self.root / 'bootstrap.json',
            {'state': {'formatVersion': 2, 'operations': []}}, 'localhost:1', {})
        write_json(self.configuration.path, self.configuration.value)
        self.activation = CurrentActivation(self.client, self.configuration, self.node, self.root,
            self.items, self.publications, {'deploymentGrants': ['original']}, inspected)
        self.node.current_activation = self.activation
        self.original = result(count='1')
        retained = inspection(self.original)
        retained['source']['publicationId'] = self.publications['put-once-legacy-v1']
        retained['key']['clientKey'] = KEY
        self.response = {'cancellationDisposition': COMMITTED, 'command': retained}
        self.subject = campaign.Campaign.__new__(campaign.Campaign)
        self.subject.client, self.subject.node = self.client, self.node
        self.subject.publications, self.subject.originals = self.publications, {KEY: self.original}
        self.subject.original = Mock(side_effect=self.read_original)
        self.subject.query = Mock(side_effect=self.query)
        self.actual_replay = http.replay
        self.old_prefix = ('publish', 'authority', 'namespace-create', 'legacy-runtime',
            'diagnostic-metadata', 'diagnostic-runtime', 'legacy-metadata', 'legacy-after-diagnostic',
            'compatible-metadata', 'compatible-runtime', 'compatible-after-crash')
        self.new_sessions = ('cancellation-legacy-metadata', 'cancellation-legacy-runtime',
                             'cancellation-compatible-metadata', 'cancellation-compatible-runtime')

    def __enter__(self):
        self.stack.enter_context(patch.object(lifecycle, 'Process', side_effect=self.process))
        self.stack.enter_context(patch.object(self.node, 'stop', side_effect=self.stop))
        self.stack.enter_context(patch.object(lifecycle, 'admission_lease_interval', side_effect=self.lease))
        self.stack.enter_context(patch.object(lifecycle, 'deployment_metadata', side_effect=self.metadata))
        self.stack.enter_context(patch.object(lifecycle, 'bind_http_routes', side_effect=self.bind))
        self.stack.enter_context(patch.object(lifecycle, 'as_user', side_effect=self.user))
        self.stack.enter_context(patch.object(http, 'replay', side_effect=self.replay))
        try:
            for session in self.old_prefix:
                name = ('put-once-compatible-v2' if session.startswith('compatible') else
                        'put-once-diagnostics' if session.startswith('diagnostic') else 'put-once-legacy-v1')
                path = self.configuration.path if session in lifecycle.CURRENT_METADATA_SESSIONS else self.activation.path(name)
                self.node.start(path, current_session=session)
                if session != self.old_prefix[-1]:
                    self.node.stop()
            for name, session in [('put-once-legacy-v1', 'legacy-after-diagnostic'),
                                  ('put-once-compatible-v2', 'compatible-runtime')]:
                self.activation.metadata[name] = ({'generation': '1'}, {'originalTarget': name})
                self.collector.passed('deploy-' + name + '-' + session, {'original': True})
            self.activation.active = 'put-once-compatible-v2'
            self.subject.full_path = self.activation.path(self.activation.active)
            self.old_files = {row['path']: (self.collector.directory / row['path']).read_bytes()
                              for row in self.collector.files}
            self.events.clear()
            return self
        except BaseException:
            self.__exit__(None, None, None)
            raise

    def __exit__(self, *_):
        try:
            if self.node.process is not None:
                self.node.stop()
            assert all(process.closed for process in self.processes)
        finally:
            self.stack.close()
            self.temporary.cleanup()

    def process(self, argv, directory, environment, cancellation, maximum):
        assert maximum == 262144 and cancellation is self.client.cancellation
        assert argv[1:3] == ['serve', '--config']
        session = self.node.program[self.node.ordinal - 1]
        self.started.append(session)
        self.events.append(('start', session))
        fixture = self

        class MockProcess:
            def __init__(self):
                self.closed, self.buffers = False, [bytearray(), bytearray()]
                self.owner = SimpleNamespace(process=SimpleNamespace(returncode=None), finished=False)

            def line(self, cutoff):
                assert cutoff <= fixture.client.deadline
                if fixture.failure == ('start', session):
                    self.owner.process.returncode = 1
                    raise ValueError('session-start-refused')
                return {'endpoint': '127.0.0.1:52000'}

            def close(self):
                self.closed, self.owner.finished = True, True

        process = MockProcess()
        self.processes.append(process)
        return process

    def stop(self):
        assert self.node.process is not None
        self.events.append(('stop', self.node.program[self.node.ordinal - 1]))
        self.node.process.close()
        self.node.process, self.client.node = None, None

    def lease(self, client):
        assert client is self.client and self.node.process is None
        self.lease_calls += 1
        self.events.append(('lease', self.lease_calls))
        if self.failure == ('lease', self.lease_calls):
            raise ValueError('original-admission-lease-interval')
        if self.failure == ('cancelled', self.lease_calls):
            raise KeyboardInterrupt('original-cancellation')

    def metadata(self, client, signed, item, publication, grants):
        assert client is self.client and client.role == 'operator'
        assert publication == self.publications[item.name] and grants == ['original']
        self.metadata_calls += 1
        self.events.append(('metadata', item.name))
        self.metadata_name = item.name
        if self.failure == ('metadata', item.name):
            raise ValueError('uncertain-metadata')
        return {'generation': str(self.metadata_calls + 1)}, {'originalTarget': item.name}

    def bind(self, *_):
        self.events.append(('bind', self.metadata_name))
        if self.failure == ('bind', self.metadata_name):
            raise ValueError('uncertain-trigger')

    @contextmanager
    def user(self, client):
        assert client is self.client and client.role == 'operator'
        client.role = 'user'
        self.events.append('user-enter')
        try:
            yield
        finally:
            client.role = 'operator'
            self.events.append('user-exit')

    def call(self, *argv):
        if argv[:2] == ('node', 'get'):
            return {'data': {'inventory': {'health': {'ready': True}}}}
        assert self.client.role == 'user' and self.activation.active == 'put-once-legacy-v1'
        expected = ('transaction', 'cancel',
            *lifecycle.namespace_arguments(self.publications['put-once-legacy-v1']),
            '--operation', 'update', '--client-key', KEY, '--attempt-id', self.original['attempt-id'],
            '--reason', 'cancelled')
        assert argv == expected
        self.cancel_calls.append(argv)
        self.events.append('cancel')
        return {'data': copy.deepcopy(self.response)}

    def read_original(self, key):
        assert key == KEY
        assert self.activation.active == 'put-once-compatible-v2'
        assert self.started[-1] == 'cancellation-compatible-runtime'
        self.events.append('original-get')
        return copy.deepcopy(self.original)

    def replay(self, original, retained):
        self.events.append('replay')
        return self.actual_replay(original, retained)

    def query(self, count):
        assert count == 4 and self.activation.active == 'put-once-compatible-v2'
        self.events.append('query-four')

    def unchanged_original_evidence(self):
        assert all((self.collector.directory / name).read_bytes() == raw
                   for name, raw in self.old_files.items())


class RetainedCancellationSessions(unittest.TestCase):
    def test_real_sequence_uses_four_unique_sessions_before_unchanged_writer_suffix(self):
        with SessionFixture() as fixture:
            fixture.subject._retained_cancellation()
            self.assertEqual(fixture.started, [*fixture.old_prefix, *fixture.new_sessions])
            self.assertEqual(len(fixture.cancel_calls), 1)
            self.assertEqual(fixture.client.role, 'operator')
            self.assertEqual(fixture.node.ordinal, 15)
            self.assertEqual(fixture.lease_calls, 4)
            self.assertEqual(fixture.collector.cases, [
                'deploy-put-once-legacy-v1-legacy-after-diagnostic',
                'deploy-put-once-compatible-v2-compatible-runtime',
                'deploy-put-once-legacy-v1-cancellation-legacy-runtime',
                'deploy-put-once-compatible-v2-cancellation-compatible-runtime',
                'cancellation-after-commit'])
            self.assertEqual(fixture.events[-3:], ['original-get', 'replay', 'query-four'])
            fixture.unchanged_original_evidence()
            suffix = ('writer-metadata', 'writer-runtime', 'restored-runtime')
            self.assertEqual(fixture.node.program, (*fixture.old_prefix, *fixture.new_sessions, *suffix))
            for session in suffix:
                fixture.node.stop()
                path = (fixture.configuration.path if session.endswith('metadata') else
                        fixture.activation.path('put-once-writer-v2'))
                fixture.node.start(path, current_session=session)
            fixture.node.stop()
            with self.assertRaisesRegex(ValueError, 'bounded-current-node-session-program'):
                fixture.node.start(fixture.configuration.path, current_session='writer-metadata')
            self.assertEqual(len(fixture.started), 18)

    def test_consumed_prefix_refuses_default_old_session_names_before_cancel(self):
        with SessionFixture() as fixture:
            with self.assertRaisesRegex(ValueError, 'bounded-current-node-session-program'):
                fixture.activation.switch(fixture.subject, 'put-once-legacy-v1')
            self.assertEqual(fixture.started, list(fixture.old_prefix))
            self.assertEqual(fixture.cancel_calls, [])
            self.assertEqual(fixture.node.ordinal, 11)
            fixture.unchanged_original_evidence()

    def test_duplicate_cancellation_cannot_reuse_completed_phase_or_evidence(self):
        with SessionFixture() as fixture:
            fixture.subject._retained_cancellation()
            cases, files = list(fixture.collector.cases), copy.deepcopy(fixture.collector.files)
            with self.assertRaisesRegex(ValueError, 'bounded-current-node-session-program'):
                fixture.subject._retained_cancellation()
            self.assertEqual(len(fixture.cancel_calls), 1)
            self.assertEqual(fixture.collector.cases, cases)
            self.assertEqual(fixture.collector.files, files)
            fixture.unchanged_original_evidence()

    def test_phase_is_literal_bool_terminal_and_two_original_publications_only(self):
        choices = [(value, 'terminal', True, 'put-once-legacy-v1') for value in (0, 1, None, 'true')]
        choices += [(True, value, True, 'put-once-legacy-v1') for value in ('pending-close', 'early-http')]
        choices += [(True, 'terminal', False, 'put-once-legacy-v1')]
        choices += [(True, 'terminal', True, name) for name in
                    ('aggregate', 'put-once-writer-v2', 'put-once-diagnostics', 'foreign')]
        for flag, program, current, name in choices:
            with self.subTest(flag=flag, program=program, name=name), SessionFixture() as fixture:
                fixture.node.current_program, fixture.node.current_publication_program = program, current
                with self.assertRaises(ValueError):
                    fixture.activation.switch(fixture.subject, name, retained_cancellation=flag)
                self.assertEqual(fixture.events, [])
                self.assertEqual(fixture.started, list(fixture.old_prefix))
                self.assertEqual(fixture.cancel_calls, [])

    def test_new_slots_keep_metadata_empty_and_runtime_one_publication(self):
        from tools.phase2_operator_process import read_json, write_json
        for position, kind in ((11, 'runtime-in-metadata'), (12, 'empty-runtime'), (12, 'mixed-runtime')):
            with self.subTest(position=position, kind=kind), SessionFixture() as fixture:
                fixture.node.stop()
                fixture.node.ordinal = position
                runtime = read_json(fixture.activation.path('put-once-legacy-v1'))
                if kind == 'empty-runtime':
                    runtime['state']['operations'] = []
                elif kind == 'mixed-runtime':
                    runtime['state']['operations'][0]['publication'] = fixture.publications['put-once-compatible-v2']
                path = fixture.root / 'invalid-session.json'
                write_json(path, runtime)
                with self.assertRaises(ValueError):
                    fixture.node.start(path, current_session=fixture.node.program[position])
                self.assertEqual(fixture.started, list(fixture.old_prefix))
                self.assertEqual(fixture.node.ordinal, position)
                self.assertEqual(fixture.cancel_calls, [])

    def test_original_lease_failure_or_cancellation_prevents_new_start_and_cancel(self):
        for label, error in [('lease', ValueError), ('cancelled', KeyboardInterrupt)]:
            with self.subTest(label=label), SessionFixture() as fixture:
                fixture.failure = (label, 1)
                with self.assertRaises(error):
                    fixture.subject._retained_cancellation()
                self.assertEqual(fixture.started, list(fixture.old_prefix))
                self.assertEqual(fixture.cancel_calls, [])
                self.assertEqual(fixture.lease_calls, 1)
                fixture.unchanged_original_evidence()

    def test_uncertain_metadata_or_trigger_never_starts_cancellation_runtime(self):
        for stage in ('metadata', 'bind'):
            with self.subTest(stage=stage), SessionFixture() as fixture:
                fixture.failure = (stage, 'put-once-legacy-v1')
                with self.assertRaisesRegex(ValueError, 'uncertain-'):
                    fixture.subject._retained_cancellation()
                self.assertEqual(fixture.started, [*fixture.old_prefix, 'cancellation-legacy-metadata'])
                self.assertIsNone(fixture.node.process)
                self.assertEqual(fixture.cancel_calls, [])
                self.assertNotIn('cancellation-after-commit', fixture.collector.cases)
                fixture.unchanged_original_evidence()

    def test_metadata_or_runtime_start_failure_is_retained_without_retry_or_cancel(self):
        for session in ('cancellation-legacy-metadata', 'cancellation-legacy-runtime'):
            with self.subTest(session=session), SessionFixture() as fixture:
                fixture.failure = ('start', session)
                with self.assertRaisesRegex(ValueError, 'session-start-refused'):
                    fixture.subject._retained_cancellation()
                self.assertEqual(fixture.started.count(session), 1)
                self.assertEqual(fixture.cancel_calls, [])
                self.assertIsNone(fixture.node.process)
                self.assertIn(f'node-{fixture.node.ordinal}-startup-failure.json',
                              [row['path'] for row in fixture.collector.files])
                self.assertNotIn('cancellation-after-commit', fixture.collector.cases)

    def test_return_phase_failure_after_cancel_prevents_http_and_success(self):
        for stage, value in [('metadata', 'put-once-compatible-v2'),
                             ('bind', 'put-once-compatible-v2'),
                             ('start', 'cancellation-compatible-runtime')]:
            with self.subTest(stage=stage), SessionFixture() as fixture:
                fixture.failure = (stage, value)
                with self.assertRaises(ValueError):
                    fixture.subject._retained_cancellation()
                self.assertEqual(len(fixture.cancel_calls), 1)
                fixture.subject.original.assert_not_called()
                fixture.subject.query.assert_not_called()
                self.assertNotIn('replay', fixture.events)
                self.assertNotIn('cancellation-after-commit', fixture.collector.cases)
                self.assertEqual(fixture.client.role, 'operator')

    def test_existing_exclusive_receipt_cannot_be_overwritten_or_claimed(self):
        with SessionFixture() as fixture:
            name = 'case-deploy-put-once-legacy-v1-cancellation-legacy-runtime.json'
            fixture.collector.write(name, b'original-occupied-evidence')
            with self.assertRaises(FileExistsError):
                fixture.subject._retained_cancellation()
            self.assertEqual((fixture.collector.directory / name).read_bytes(), b'original-occupied-evidence')
            self.assertEqual(fixture.cancel_calls, [])
            self.assertNotIn('deploy-put-once-legacy-v1-cancellation-legacy-runtime', fixture.collector.cases)
            self.assertNotIn('cancellation-after-commit', fixture.collector.cases)

    def test_default_live_runtime_reuse_keeps_original_behavior_without_new_phase(self):
        with SessionFixture() as fixture:
            original = fixture.activation.metadata['put-once-compatible-v2'][1]
            returned = fixture.activation.switch(fixture.subject, 'put-once-compatible-v2')
            self.assertIs(returned, original)
            self.assertEqual(fixture.events, [])
            self.assertEqual(fixture.started, list(fixture.old_prefix))
            fixture.unchanged_original_evidence()
