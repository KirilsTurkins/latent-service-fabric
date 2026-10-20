"""Finite managed waits require exact timer authority and lifecycle receipts."""
import copy
import unittest

from tools.dotnet_guest import runtime, task_wait
from tools.rust_capsule_project import digest, write_json
from tools.tests import test_dotnet_task_wait as controls


FINITE = {
    'finiteAndCancellableWaits': 'original-Task-WhenAny-Delay',
    'generatedHelperCount': 10,
    'finiteWaitCleanup': 'private-linked-source-cancel-dispose-finally',
    'zeroTimeout': 'query-only-before-cancellation',
    'waitCancellation': 'original-token-only',
    'publicWaitValidationAndExceptions': 'unchanged',
}
DECLARATIONS = [runtime.CLOCK, runtime.ACTIVATION, runtime.WALL, runtime.RANDOM]


class FiniteTaskWaitTests(unittest.TestCase):
    def control(self, declarations):
        value = controls.TaskWaitPortTests()
        value.setUp()
        self.addCleanup(value.doCleanups)
        value.declared = declarations
        return value

    def test_four_explicit_runtime_facets_select_the_finite_rewrite_without_http(self):
        value = self.control(DECLARATIONS)
        def run(stage, *arguments):
            self.assertEqual(arguments[2], '--finite-task-wait')
            value.stages.append(stage)
            arguments[-2].write_bytes(b'finite-control')
            write_json(arguments[-1], {**value.receipt, **FINITE, 'outputDigest': digest(b'finite-control')})
        value.run_tool = run
        port = value.prepare()
        value.references(port)
        record = port.finish(value.project, value.evidence)
        self.assertEqual(record['selection']['requiredDeclarations'], sorted(DECLARATIONS))
        self.assertNotIn(runtime.HTTP, record['selection']['requiredDeclarations'])
        self.assertEqual(record['finiteWaitCleanup'], FINITE['finiteWaitCleanup'])
        self.assertEqual(value.stages, ['task-wait-rewrite'])
        self.assertIsNotNone(record['nativeAotReferenceBinding'])

    def test_missing_wall_keeps_the_original_infinite_only_rewrite(self):
        value = self.control([runtime.CLOCK, runtime.ACTIVATION, runtime.RANDOM])
        port = value.prepare()
        self.assertEqual(port.evidence['finiteAndCancellableWaits'], 'original-unsupported')
        self.assertEqual(port.evidence['generatedHelperCount'], 9)
        self.assertEqual(port.evidence['selection']['requiredDeclarations'], sorted(DECLARATIONS[:2]))

    def test_missing_entropy_keeps_the_original_infinite_only_rewrite(self):
        value = self.control([runtime.CLOCK, runtime.ACTIVATION, runtime.WALL])
        port = value.prepare()
        self.assertEqual(port.evidence['finiteAndCancellableWaits'], 'original-unsupported')
        self.assertNotIn('finiteWaitCleanup', port.evidence)
        self.assertEqual(port.evidence['selection']['requiredDeclarations'], sorted(DECLARATIONS[:2]))

    def test_old_or_cross_selected_receipts_cannot_claim_finite_support(self):
        value = self.control(DECLARATIONS)
        finite = {**value.receipt, **FINITE}
        task_wait.validate_receipt(finite, finite=True)
        for receipt, selected in ((value.receipt, True), (finite, False), (finite, 1), (finite, 'true')):
            with self.subTest(selected=selected), self.assertRaises(ValueError):
                task_wait.validate_receipt(receipt, finite=selected)

    def test_finite_receipt_refuses_timer_leaks_synthetic_completion_and_changed_token_precedence(self):
        value = self.control(DECLARATIONS)
        finite = {**value.receipt, **FINITE}
        for key, changed in (('finiteWaitCleanup', 'dispose-without-cancel'),
                             ('zeroTimeout', 'create-timer-before-query'),
                             ('waitCancellation', 'replacement-token'),
                             ('publicWaitValidationAndExceptions', 'rewritten'),
                             ('completion', 'timeout-is-success'), ('generatedHelperCount', 9),
                             ('maximumNestedWaits', 33)):
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, 'rewrite-receipt'):
                task_wait.validate_receipt({**finite, key: changed}, finite=True)
        for key in FINITE:
            missing = copy.deepcopy(finite)
            del missing[key]
            with self.subTest(missing=key), self.assertRaisesRegex(ValueError, 'rewrite-receipt'):
                task_wait.validate_receipt(missing, finite=True)


if __name__ == '__main__':
    unittest.main()
