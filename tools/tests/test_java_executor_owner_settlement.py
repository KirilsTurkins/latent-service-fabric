"""Executor settlement owner selection and failure propagation, not a guest receipt."""
from pathlib import Path
from types import SimpleNamespace
import os
import unittest

from tools import qualify_java_fibers as subject


class ExecutorSettlementOwner(unittest.TestCase):
    def test_each_case_uses_a_fresh_owned_process(self):
        for actual in (False, True):
            with self.subTest(actual=actual):
                calls = []
                def run(stage, *argv):
                    calls.append((stage, argv))
                    prefix = 'EXECUTOR_ACTIVATION_SETTLEMENT' if actual else 'EXECUTOR_OWNER_SETTLEMENT'
                    return f'{prefix} PASS {argv[-2]} {argv[-1]}\n'
                compiler = SimpleNamespace(run=run)
                if actual:
                    receipt = subject.executor_activation_settlement_control(compiler, Path('classes'), 'locked.jar')
                    modes = subject.EXECUTOR_ACTIVATION_SETTLEMENT_CASES
                    main = 'ExecutorActivationSettlementControl'
                    classpath = str(Path('classes')) + os.pathsep + 'locked.jar'
                    status = 'SDK-activation-source-controls-passed'
                else:
                    receipt = subject.executor_owner_settlement_control(compiler, Path('classes'))
                    modes = subject.EXECUTOR_OWNER_SETTLEMENT_CASES
                    main = 'ExecutorOwnerSettlementControl'
                    classpath = Path('classes')
                    status = 'SDK-source-controls-passed'
                self.assertEqual(receipt, {'status': status, 'cases': {'managed': list(modes), 'scheduled': list(modes)},
                    'componentExecutionPerformed': False, 'actualGuestBindingsUsed': False})
                self.assertEqual(len(calls), 2 * len(modes))
                self.assertEqual(len({stage for stage, _ in calls}), len(calls))
                for index, (stage, argv) in enumerate(calls):
                    kind = ('managed', 'scheduled')[index // len(modes)]
                    mode = modes[index % len(modes)]
                    self.assertEqual(stage, ('executor-activation-settlement-' if actual else
                        'executor-owner-settlement-') + kind + '-' + mode)
                    self.assertEqual(argv, ('java', '-Xmx256m', '-cp', classpath, main, kind, mode))

    def test_missing_wrong_or_duplicated_receipt_fails_closed(self):
        for actual in (False, True):
            for returned in ('', 'SKIPPED', 'EXECUTOR_OWNER_SETTLEMENT PASS managed wrong',
                    'EXECUTOR_ACTIVATION_SETTLEMENT PASS managed denied\nFAIL'):
                with self.subTest(actual=actual, returned=returned):
                    calls = []
                    def run(*args): calls.append(args); return returned
                    compiler = SimpleNamespace(run=run)
                    with self.assertRaisesRegex(ValueError, 'Java executor .* settlement control did not complete'):
                        if actual: subject.executor_activation_settlement_control(compiler, Path('classes'), 'locked.jar')
                        else: subject.executor_owner_settlement_control(compiler, Path('classes'))
                    self.assertEqual(len(calls), 1)

    def test_process_failure_is_propagated_without_retry(self):
        for actual in (False, True):
            with self.subTest(actual=actual):
                calls, failure = [], RuntimeError('owned-process-failed')
                def run(*args): calls.append(args); raise failure
                compiler = SimpleNamespace(run=run)
                with self.assertRaises(RuntimeError) as caught:
                    if actual: subject.executor_activation_settlement_control(compiler, Path('classes'), 'locked.jar')
                    else: subject.executor_owner_settlement_control(compiler, Path('classes'))
                self.assertIs(caught.exception, failure)
                self.assertEqual(len(calls), 1)


if __name__ == '__main__':
    unittest.main()
