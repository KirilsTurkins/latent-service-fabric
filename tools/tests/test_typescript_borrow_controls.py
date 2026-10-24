"""Owning recipe refusal controls; these do not execute a native engine."""
from copy import deepcopy
import unittest

from tools.typescript_guest.borrow_controls import NORMAL_CASES, REFUSAL_CASES, native_control, source_controls


class BorrowControlEvidenceTests(unittest.TestCase):
    def native(self, case):
        refusal = case in REFUSAL_CASES
        ack = refusal and case.endswith('-ack')
        return {'case': case, 'status': 0, 'owners': 1 if refusal else 0,
                'expectedQuarantine': refusal, 'hostcallInGC': False, 'dropOrderValid': True,
                'recordDestroyed': True, 'observerDestroyed': True,
                'exactAckRefusals': 1 if ack else 0, 'subtaskDrops': 1 if ack or case == NORMAL_CASES[0] else 0,
                'cancelRequests': 1 if ack or case == NORMAL_CASES[0] else 0,
                'managerBytes': 128, 'baselineManagerBytes': 112, 'fixedManagerDeltaBytes': 16,
                'recordBytes': 256, 'observerBytes': 96}

    def test_six_source_cases_must_actually_run_without_any_skip(self):
        valid = {'testsRun': 6, 'skipped': 0, 'failures': 0, 'errors': 0}
        source_controls(valid)
        for key, value in [('testsRun', 5), ('skipped', 1), ('failures', 1), ('errors', 1), ('errors', False)]:
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                source_controls(dict(valid, **{key: value}))

    def test_native_refusal_cannot_report_zero_owners_or_unexercised_ack(self):
        case = 'borrow-refusal-observer-owner-ack'
        valid = self.native(case)
        native_control(valid, case)
        for key, value in [('owners', 0), ('owners', -1), ('owners', 257), ('owners', True),
                           ('expectedQuarantine', False), ('exactAckRefusals', 0),
                           ('exactAckRefusals', True), ('subtaskDrops', 0), ('recordDestroyed', False),
                           ('observerDestroyed', False), ('dropOrderValid', False), ('status', False)]:
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                native_control(dict(valid, **{key: value}), case)

    def test_normal_completion_cannot_hide_retention_or_change_abi(self):
        case = NORMAL_CASES[0]
        valid = self.native(case)
        native_control(valid, case)
        for key, value in [('owners', 1), ('expectedQuarantine', True), ('hostcallInGC', True),
                           ('fixedManagerDeltaBytes', 8), ('managerBytes', True), ('cancelRequests', 2),
                           ('subtaskDrops', 0), ('case', REFUSAL_CASES[0])]:
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                native_control(dict(valid, **{key: value}), case)
        sample = deepcopy(valid)
        del sample['observerBytes']
        with self.assertRaises(ValueError):
            native_control(sample, case)


if __name__ == '__main__':
    unittest.main()
