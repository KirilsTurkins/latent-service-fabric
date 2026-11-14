"""Failure diagnostics never replace the signed case's original failing outcome."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from tools import typescript_fetch_failure as failure
from tools.phase2_operator_process import WorkflowError, read_json


class FetchFailureObservations(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.output = Path(self.temporary.name)
        self.target = {'name': 'typescript-fetch'}
        self.client = Mock(deadline=1000)
        self.client.call.side_effect = [
            {'category': 'success', 'outcomeKnown': True, 'data': {'inventory': {'active': 1, 'quarantined': 1}}},
            {'category': 'success', 'outcomeKnown': True, 'data': {'nodeUsage': {'unavailable': False, 'counters': {'broker_handles': 2}}}}]
        self.clock = patch.object(failure.time, 'monotonic', return_value=10)
        self.clock.start()
        self.addCleanup(self.clock.stop)

    def test_success_performs_no_extra_reads_or_writes(self):
        result = {'cases': []}
        with failure.observe_case_failure(self.client, self.target, self.output, 'entry', result):
            result['cases'].append('entry')
        self.client.call.assert_not_called()
        self.assertEqual(result, {'cases': ['entry']})
        self.assertEqual(list(self.output.iterdir()), [])

    def raise_case_failure(self, error, result):
        with failure.observe_case_failure(self.client, self.target, self.output,
                                          'abort-fanout-refusal', result):
            raise error

    def test_failed_case_retains_nonzero_owners_and_exact_original_exception(self):
        result = {'cases': ['abort-fanout']}
        error = WorkflowError('fetch-runtime-typed-result')
        with self.assertRaises(WorkflowError) as caught:
            self.raise_case_failure(error, result)
        self.assertIs(caught.exception, error)
        self.assertEqual(result['cases'], ['abort-fanout'])
        observation = result['failedCase']['cleanupObservation']
        self.assertFalse(observation['physicalRetirementProven'])
        path = self.output / observation['path']
        self.assertEqual(observation['identity'], failure.file_identity(path))
        receipt = read_json(path)
        self.assertEqual(receipt['status'], 'observed')
        self.assertEqual(receipt['observations']['inventory']['value'], {'active': 1, 'quarantined': 1})
        self.assertEqual(receipt['observations']['providerUsage']['value']['counters']['broker_handles'], 2)
        self.assertEqual([call.args[:2] for call in self.client.call.call_args_list],
                         [('node', 'get'), ('capability', 'list')])
        self.assertTrue(all(0 < call.kwargs['timeout'] <= 3
                            for call in self.client.call.call_args_list))

    def test_failed_inventory_read_does_not_skip_provider_observation_or_leak_error(self):
        self.client.call.side_effect = [RuntimeError('private-credential-never-retain'),
            {'category': 'success', 'outcomeKnown': True, 'data': {'nodeUsage': {'unavailable': True}}}]
        observed = failure.failed_case_observation(self.client, self.target, self.output, 'refusal')
        self.assertEqual(observed['status'], 'partial')
        raw = (self.output / observed['path']).read_text()
        self.assertNotIn('private-credential', raw)
        receipt = read_json(self.output / observed['path'])
        self.assertEqual(receipt['observations']['inventory'], {'status': 'unavailable', 'reason': 'read-failed'})
        self.assertTrue(receipt['observations']['providerUsage']['value']['unavailable'])
        self.assertEqual(self.client.call.call_count, 2)

    def test_failed_or_unknown_control_results_are_not_observations(self):
        for result in ({'category': 'platform-failure', 'outcomeKnown': True},
                       {'category': 'success', 'outcomeKnown': False}):
            with self.subTest(result=result):
                self.client.call.side_effect = [dict(result, data={'inventory': {'active': 0}}),
                    dict(result, data={'nodeUsage': {'unavailable': False}})]
                observed = failure.failed_case_observation(self.client, self.target, self.output, 'refusal-' + result['category'])
                receipt = read_json(self.output / observed['path'])
                self.assertEqual(observed['status'], 'partial')
                self.assertTrue(all(row == {'status': 'unavailable', 'reason': 'read-failed'}
                                    for row in receipt['observations'].values()))
        self.assertTrue(all(call.kwargs['codes'] == (0, 2, 3, 4, 5, 6, 130)
                            for call in self.client.call.call_args_list))

    def test_original_deadline_is_not_extended_and_exhaustion_stops_new_reads(self):
        self.client.deadline = 11
        with patch.object(failure.time, 'monotonic', side_effect=[10, 10.5, 11]):
            observed = failure.failed_case_observation(self.client, self.target, self.output, 'refusal')
        self.client.call.assert_called_once()
        self.assertEqual(self.client.call.call_args.kwargs['timeout'], .5)
        receipt = read_json(self.output / observed['path'])
        self.assertEqual(receipt['observations']['providerUsage'], {'status': 'unavailable', 'reason': 'deadline'})
        self.client.reset_mock()
        self.client.deadline = 9
        failure.failed_case_observation(self.client, self.target, self.output, 'expired')
        self.client.call.assert_not_called()

    def test_write_and_observer_errors_cannot_mask_the_test_failure(self):
        for operation in ('write_json', 'failed_case_observation'):
            result = {'cases': []}
            original = WorkflowError('fetch-runtime-typed-result')
            with self.subTest(operation=operation), \
                    patch.object(failure, operation, side_effect=OSError('private-path')), \
                    self.assertRaises(WorkflowError) as caught:
                self.raise_case_failure(original, result)
            self.assertIs(caught.exception, original)
            self.assertEqual(result['failedCase']['cleanupObservation']['status'], 'unavailable')
            self.assertFalse(result['failedCase']['cleanupObservation']['physicalRetirementProven'])

    def test_cancellation_and_invalid_names_do_not_start_diagnostics(self):
        result = {'cases': []}
        with self.assertRaises(KeyboardInterrupt):
            self.raise_case_failure(KeyboardInterrupt(), result)
        self.client.call.assert_not_called()
        self.assertNotIn('failedCase', result)
        observed = failure.failed_case_observation(self.client, self.target, self.output, '../invalid')
        self.assertEqual(observed['reason'], 'invalid-case-name')
        self.client.call.assert_not_called()
        self.assertEqual(list(self.output.iterdir()), [])
