"""The existing native startup report survives reader failure without raw text."""
from contextlib import nullcontext
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from tools import node_startup_observation as observation
from tools import phase2_operator_process as process
from tools import qualify_go_node_stop as reference


def report():
    return {'schemaVersion': observation.SCHEMA, 'startupSucceeded': False,
        'terminalFailure': {'owner': 'platform', 'reason': 'unavailable'},
        'observations': [{'stage': 'auditCatalog',
            'failure': {'owner': 'storage', 'reason': 'corrupt'}}],
        'truncated': False, 'shutdown': None}


def encoded(value=None):
    return json.dumps(report() if value is None else value).encode() + b'\n'


class NodeStartupObservation(unittest.TestCase):
    def test_closed_native_report_is_distinct_from_legacy_single_line_and_has_no_success_credit(self):
        raw = encoded() + b'latentd: startup: unavailable\n'
        self.assertEqual(process.startup_diagnostic(raw), 'unavailable')
        self.assertEqual(observation.observe(raw), {
            'status': 'observed', 'qualification': False, 'report': report()})
        self.assertEqual(process.startup_diagnostic(b'latentd: startup: unavailable\n'),
                         'startup-unavailable')

    def test_unknown_private_extra_and_wrong_numeric_or_owner_fields_fail_closed(self):
        values = []
        for key, value in [('private', 'private-fixture-secret'), ('startupSucceeded', 0),
                           ('truncated', 0), ('shutdown', {}), ('schemaVersion', 'private-schema')]:
            selected = report(); selected[key] = value; values.append(selected)
        for key, value in [('owner', 'private'), ('reason', 'private'), ('private', 'secret')]:
            selected = report(); selected['terminalFailure'][key] = value; values.append(selected)
        for key, value in [('stage', 'privateStage'), ('stage', []), ('private', 'secret')]:
            selected = report(); selected['observations'][0][key] = value; values.append(selected)
        selected = report(); selected['observations'][0]['failure']['private'] = 'secret'; values.append(selected)
        selected = report(); selected['observations'][0]['failure']['reason'] = 'private'; values.append(selected)
        for value in values:
            with self.subTest(value=value):
                actual = observation.observe(encoded(value))
                self.assertEqual(actual, {'status': 'unavailable', 'qualification': False})
                self.assertNotIn('secret', json.dumps(actual))

    def test_duplicate_reports_keys_partial_truncated_and_excessive_reports_are_not_evidence(self):
        selected = report(); selected['truncated'] = True
        too_many = report(); too_many['observations'] *= 33
        duplicate = encoded().replace(b'"truncated": false', b'"truncated": false, "truncated": false')
        for raw in (b'', encoded() + encoded(), duplicate, encoded()[:-5], encoded(selected),
                    encoded(too_many), b'x' * 262145, b'x' * 16385 + encoded(), None):
            with self.subTest(size=len(raw) if raw is not None else None):
                self.assertEqual(observation.observe(raw), {'status': 'unavailable', 'qualification': False})

    def test_ordinary_stderr_does_not_enter_the_closed_observation(self):
        raw = b'private fixture path or credential\n' + encoded() + b'private output\n'
        actual = observation.observe(raw)
        self.assertEqual(actual['report'], report())
        self.assertNotIn('private', json.dumps(actual))

    def test_actual_process_startup_exit_keeps_error_and_attaches_closed_report(self):
        node = SimpleNamespace(drain=lambda: None, buffers=[bytearray(), bytearray(encoded())],
                               owner=SimpleNamespace(exited=lambda: True))
        with patch.object(process.time, 'monotonic', return_value=1.0):
            with self.assertRaisesRegex(process.WorkflowError, '^node-startup-exit-unavailable$') as failed:
                process.Process.line(node, 2.0)
        self.assertEqual(getattr(failed.exception, 'startup_failure', None), {
            'status': 'observed', 'qualification': False, 'report': report()})

    def test_go_failed_programme_retains_closed_startup_report_and_original_failure(self):
        error = process.WorkflowError('node-startup-exit-unavailable')
        error.startup_failure = observation.observe(encoded())
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            client = SimpleNamespace(environment={})
            with patch.object(reference, 'RecordingClient', return_value=client), \
                    patch.object(reference, 'owned_cancellation', return_value=nullcontext(None)), \
                    patch.object(reference, 'configuration', return_value=output / 'node.json'), \
                    patch.object(reference, 'connect', side_effect=error):
                with self.assertRaises(process.WorkflowError) as failed:
                    reference.programme({'latent': Path('latent'), 'latentd': Path('latentd')},
                        output, output, positive_timers=True)
            self.assertIs(failed.exception, error)
            retained = json.loads((output / 'pending/FAILED.json').read_bytes())
            self.assertEqual(retained['failedNodeStartup'], error.startup_failure)
            self.assertEqual(retained['status'], 'failed')
            self.assertNotIn('restart', retained)


if __name__ == '__main__':
    unittest.main()
