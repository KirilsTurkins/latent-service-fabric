"""Closed qualification failure evidence without invoking a node or container."""
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import re
import sys
from types import SimpleNamespace
import unittest
from unittest import mock

from tools import native_runtime
from tools.native_runtime import common, files


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / 'tools/container_runtime/qualification_inside.py'
PREFIX = 'container-qualification-command-failure: '
SECRET = 'sensitive-test-sentinel'


def load_qualification():
    spec = importlib.util.spec_from_file_location('container_qualification_diagnostic_control', SOURCE)
    module = importlib.util.module_from_spec(spec)
    aliases = {'native_runtime': native_runtime, 'native_runtime.common': common,
               'native_runtime.files': files}
    with mock.patch.dict(sys.modules, aliases), mock.patch.object(sys, 'path', list(sys.path)):
        spec.loader.exec_module(module)
    return module


class ContainerQualificationDiagnosticTests(unittest.TestCase):
    def setUp(self):
        self.q = load_qualification()
        self.q.DEADLINE = 100
        self.q.time = SimpleNamespace(monotonic=mock.Mock(return_value=50))
        self.events = []
        self.stored = []
        self.created = []
        self.responses = [(0, self.result())]
        self.q.execute = mock.Mock(side_effect=self.execute)
        self.q.files = SimpleNamespace(replace=self.store, create=self.create)
        self.q.require = self.require

    @staticmethod
    def result(category='success', known=True, error=None, data=None):
        return {'schemaVersion': 'latent.cli.result.v1', 'category': category,
                'outcomeKnown': known, 'requestDispatched': True,
                'error': error, 'data': data or {}}

    def failure(self, details=None):
        return self.result('platform-failure', False, {
            'code': 'unavailable', 'message': SECRET, 'retryable': True,
            'details': details if details is not None else []}, {'payload': SECRET})

    def execute(self, arguments, **options):
        self.events.append(('execute', arguments))
        status, result = self.responses.pop(0)
        return status, common.encode(result)

    def store(self, path, value):
        self.events.append(('store', str(path)))
        self.stored.append((path, json.loads(value)))

    def create(self, path, value):
        self.created.append((path, json.loads(value)))

    def require(self, condition, diagnostic):
        self.events.append(('require', diagnostic, bool(condition)))
        common.require(condition, diagnostic)

    def capture_failure(self, *arguments):
        class OrderedStream(io.StringIO):
            def write(stream_self, value):
                self.events.append(('stderr',))
                return super().write(value)
        stream = OrderedStream()
        with contextlib.redirect_stderr(stream), self.assertRaisesRegex(
                common.InstallError, '^container-qualification-command-failed$'):
            self.q.call(*arguments)
        text = stream.getvalue()
        self.assertTrue(text.startswith(PREFIX))
        self.assertNotIn(SECRET, text)
        return json.loads(text[len(PREFIX):])

    def test_failure_preserves_original_fields_storage_order_and_command(self):
        details = [{'kind': 'admission.currentness', 'fields': {'reason': 'admission-authority-busy'}}]
        self.responses = [(4, self.failure(details))]
        arguments = ('trigger', 'apply', Path('/private/' + SECRET), '--operation-id', SECRET,
                     '--expected-generation', '7', '--expected-state-version', '9007199254740993')
        evidence = self.capture_failure(*arguments)
        self.assertEqual(evidence, {
            'exitCode': 4, 'category': 'platform-failure', 'code': 'unavailable',
            'outcomeKnown': False, 'nativeCall': 1, 'phase': 'trigger.apply',
            'currentnessReason': 'admission-authority-busy'})
        self.assertEqual(self.stored, [(Path('/var/cache/lsf/qualification-command-failure.json'), evidence)])
        self.q.execute.assert_called_once_with(
            ['/opt/lsf/release/bin/latent', '--config', '/etc/lsf/client.json', '--output', 'json',
             *(str(value) for value in arguments)], maximum=300000, timeout=5, stdout_only=True)
        kinds = [event[0] for event in self.events]
        self.assertEqual([kind for kind in kinds if kind != 'stderr'], ['require', 'execute', 'store', 'require'])
        self.assertLess(kinds.index('store'), kinds.index('stderr'))
        self.assertLess(kinds.index('stderr'), len(kinds) - 1)
        self.assertEqual(self.events[-1], ('require', 'container-qualification-command-failed', False))
        self.assertEqual(self.q.CALLS, 1)
        self.assertEqual(self.q.time.monotonic.call_count, 2)

    def test_success_and_allowed_not_found_keep_original_results_without_diagnostics(self):
        for status, category in [(0, 'success'), (6, 'not-found')]:
            with self.subTest(status=status):
                result = self.result(category, data={'stateVersion': '9007199254740993', 'trigger': None})
                self.responses = [(status, result)]
                stream = io.StringIO()
                with contextlib.redirect_stderr(stream):
                    self.assertEqual(self.q.call('trigger', 'get', SECRET, codes=(0, 6)), result)
                self.assertEqual(stream.getvalue(), '')
                self.assertEqual(self.stored, [])
        self.assertEqual(self.q.execute.call_count, 2)

    def test_unknown_outcome_keeps_original_assertion_without_failure_diagnostic(self):
        self.responses = [(0, self.result(known=False))]
        stream = io.StringIO()
        with contextlib.redirect_stderr(stream), self.assertRaisesRegex(
                common.InstallError, '^container-qualification-unknown-outcome$'):
            self.q.call('node', 'get', SECRET)
        self.assertEqual(stream.getvalue(), '')
        self.assertEqual(self.stored, [])
        self.q.execute.assert_called_once()

    def test_original_route_cas_and_manifest_are_forwarded_without_retry(self):
        for previous_trigger, status in [(None, 6), ({'generation': '9007199254740992'}, 0)]:
            with self.subTest(previous=previous_trigger):
                self.setUp()
                previous = {'trigger': previous_trigger, 'stateVersion': '9007199254740993'}
                self.responses = [(status, self.result(data=previous)), (4, self.failure())]
                stream = io.StringIO()
                with contextlib.redirect_stderr(stream), self.assertRaisesRegex(
                        common.InstallError, '^container-qualification-command-failed$'):
                    self.q.route(SECRET, 'publication-sentinel', '/docs', 'HEAD',
                                 scheme='https', authority='frontend.example.test:18443')
                operation = 'initial-' + SECRET + '-1'
                request = Path('/var/cache/lsf') / (operation + '.json')
                cli = ['/opt/lsf/release/bin/latent', '--config', '/etc/lsf/client.json', '--output', 'json']
                self.assertEqual(self.q.execute.call_args_list, [
                    mock.call([*cli, 'trigger', 'get', SECRET], maximum=300000, timeout=5, stdout_only=True),
                    mock.call([*cli, 'trigger', 'apply', str(request), '--operation-id', operation,
                               '--expected-generation', previous_trigger['generation'] if previous_trigger else '0',
                               '--expected-state-version', previous['stateVersion']],
                              maximum=300000, timeout=5, stdout_only=True)])
                self.assertEqual(self.created, [(request, {
                    'apiVersion': 'latent.dev/v1alpha1', 'kind': 'HttpTrigger',
                    'metadata': {'name': SECRET, 'tenant': 'tests'}, 'spec': {
                        'target': {'kind': 'static-web', 'publication': 'publication-sentinel'},
                        'configuration': {'profile': 'static-site-v1', 'scheme': 'https',
                                          'host': 'frontend.example.test:18443', 'path': '/docs',
                                          'pathMatch': 'prefix', 'method': 'HEAD'}}})])
                self.assertNotIn(SECRET, stream.getvalue())
                self.assertEqual(json.loads(stream.getvalue()[len(PREFIX):])['nativeCall'], 2)
                self.assertEqual(self.q.CALLS, 2)

    def test_exact_closed_currentness_reasons_survive(self):
        for reason in self.q.CURRENTNESS_REASONS:
            with self.subTest(reason=reason):
                self.responses = [(4, self.failure([{'kind': 'admission.currentness',
                                                   'fields': {'reason': reason, 'private': SECRET}}]))]
                self.assertEqual(self.capture_failure('trigger', 'apply', SECRET)['currentnessReason'], reason)

    def test_unknown_lookalike_and_malformed_reasons_are_not_disclosed(self):
        details = [None, {'kind': 'admission.currentness', 'fields': []},
                   {'kind': 'other', 'fields': {'reason': 'admission-authority-busy'}},
                   {'kind': 'admission.currentness', 'fields': {'reason': 'admission-authority-busy ' + SECRET}},
                   {'kind': 'admission.currentness', 'fields': {'reason': [SECRET]}},
                   {'kind': 'admission.currentness', 'fields': {'reason': SECRET}}]
        for detail in details:
            with self.subTest(detail=detail):
                self.responses = [(4, self.failure([detail]))]
                evidence = self.capture_failure('trigger', 'apply-' + SECRET, SECRET)
                self.assertIsNone(evidence['currentnessReason'])
                self.assertEqual(evidence['phase'], 'unmapped')

    def test_currentness_vocabulary_matches_existing_rust_public_contract(self):
        source = (ROOT / 'crates/latent-core/src/error.rs').read_text(encoding='utf-8')
        block = source.split('pub const ADMISSION_CURRENTNESS_REASONS: &[&str] = &[', 1)[1].split('];', 1)[0]
        self.assertEqual(self.q.CURRENTNESS_REASONS, tuple(re.findall(r'"([^"]+)"', block)))

    def test_stderr_failure_is_best_effort_and_preserves_original_status_assertion(self):
        for error in [OSError('closed-stderr'), ValueError('closed-stderr')]:
            with self.subTest(error=type(error).__name__):
                self.setUp()
                self.responses = [(4, self.failure())]
                stream = mock.Mock()
                stream.write.side_effect = error
                with contextlib.redirect_stderr(stream), self.assertRaisesRegex(
                        common.InstallError, '^container-qualification-command-failed$'):
                    self.q.call('trigger', 'apply', SECRET)
                self.assertEqual(len(self.stored), 1)
                self.q.execute.assert_called_once()
                self.assertEqual(self.events[-1], ('require', 'container-qualification-command-failed', False))

    def test_original_storage_error_still_precedes_status_assertion_and_stderr(self):
        self.responses = [(4, self.failure())]
        self.q.files.replace = mock.Mock(side_effect=OSError('original-storage-error'))
        stream = io.StringIO()
        with contextlib.redirect_stderr(stream), self.assertRaisesRegex(OSError, '^original-storage-error$'):
            self.q.call('trigger', 'apply', SECRET)
        self.assertEqual(stream.getvalue(), '')
        self.assertNotIn(('require', 'container-qualification-command-failed', False), self.events)
        self.q.execute.assert_called_once()
        self.q.files.replace.assert_called_once()

    def test_original_operation_and_absolute_deadline_bounds_remain(self):
        for calls, deadline in [(64, 100), (0, 50)]:
            with self.subTest(calls=calls, deadline=deadline):
                self.q.CALLS = calls
                self.q.DEADLINE = deadline
                with self.assertRaisesRegex(common.InstallError, '^container-qualification-operation-bound$'):
                    self.q.call('trigger', 'apply', SECRET)
        self.q.execute.assert_not_called()
        self.assertEqual(self.stored, [])

    def test_short_original_deadline_is_not_extended(self):
        self.q.DEADLINE = 53
        self.assertEqual(self.q.call('node', 'get', SECRET), self.result())
        self.assertEqual(self.q.execute.call_args.kwargs,
                         {'maximum': 300000, 'timeout': 3, 'stdout_only': True})
        self.assertEqual(self.q.time.monotonic.call_count, 2)


if __name__ == '__main__':
    unittest.main()
