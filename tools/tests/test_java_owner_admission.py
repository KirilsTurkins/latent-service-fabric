"""Fail-closed source-control orchestration; no Java or component execution credit."""
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from tools import qualify_java_fibers as preparation


OWNER_CASES = ('normal', 'refused', 'lost', 'null', 'reentry', 'capacity')
NULL_FACTORY_CASES = (
    'cancel', 'remove', 'factory-throw', 'wait-denied', 'settle-result-denied',
    'settle-queue-denied', 'recovery', 'reentrant', 'scan-mutation',
    'retirement-scan-mutation', 'idle-scan-mutation', 'repeated-idle-scan-mutation',
    'exhausted-scan-retry', 'retry-with-live-work', 'worker-admission-denied',
    'manual-factory-throw', 'manual-worker-admission-denied',
    'managed-factory-thread', 'managed-factory-null', 'managed-factory-throw',
    'managed-null-pending', 'managed-null-fallback-throw', 'managed-null-worker-denied',
    'managed-null-worker-uncertain', 'managed-preferred-root', 'managed-nested-null-root',
    'managed-graceful-null-root', 'managed-graceful-thread-root', 'managed-graceful-executor-denied-root',
    'managed-obtrude-root',
)
SETTLEMENT_CASES = preparation.OWNER_SETTLEMENT_CASES
WORK_CASES = preparation.WORK_FINISH_CASES
SLEEP_RESULT = ('TIMER_SLEEP_ADMISSION_SOURCE PASS zero-raw-frame;zero-interrupt;typed-refusal;'
                'wait-return;same-work-retry;raw-hook-finally')


class RecordingCompiler:
    def __init__(self, override=None):
        self.sdk = preparation.ROOT / 'sdk/java-guest'
        self.calls = []
        self.override = override

    def run(self, stage, *argv):
        self.calls.append((stage, argv))
        if self.override is not None:
            result = self.override(stage)
            if result is not None:
                return result
        if stage == 'timer-sleep-admission-source-control':
            return SLEEP_RESULT
        if stage.startswith('scheduled-null-factory-activation-'):
            return 'SCHEDULED_NULL_FACTORY_ACTIVATION PASS ' + argv[-1]
        if stage == 'timer-worker-admission-source-control':
            return 'TIMER_WAIT_ADMISSION_SOURCE PASS typed-refusal;accepted-callback-not-run;owners-retired;root-refused'
        if stage.startswith('owner-admission-source-'):
            return 'OWNER_ADMISSION_SOURCE PASS ' + argv[-1]
        if stage.startswith('owner-settlement-source-'):
            return 'OWNER_SETTLEMENT_SOURCE PASS ' + argv[-1]
        if stage.startswith('work-finish-source-'):
            return 'WORK_FINISH_SOURCE PASS ' + argv[-2] + ' ' + argv[-1]
        return ''


class OwnerAdmissionPreparation(unittest.TestCase):
    def run_control(self, compiler):
        with tempfile.TemporaryDirectory() as temporary, patch.object(
                preparation, 'locked_model_classpath', return_value=('private-mocked-classpath', {'mock.jar': 'mock'})):
            return preparation.timer_sleep_admission_source_control(compiler, Path(temporary) / 'control')

    def test_each_owner_failure_mode_is_run_in_a_fresh_process_and_bound_to_source(self):
        compiler = RecordingCompiler()
        receipt = self.run_control(compiler)
        self.assertEqual([stage for stage, _ in compiler.calls], [
            'timer-sleep-admission-source-compile', 'timer-sleep-admission-source-control',
            *('scheduled-null-factory-activation-' + case for case in NULL_FACTORY_CASES),
            'timer-worker-admission-source-compile', 'timer-worker-admission-source-control',
            *('owner-admission-source-' + case for case in OWNER_CASES),
            *('owner-settlement-source-' + case for case in SETTLEMENT_CASES),
            *('work-finish-source-' + kind + '-' + mode for kind, mode in WORK_CASES)])
        compile_args = compiler.calls[0][1]
        self.assertEqual(compile_args[:4], ('javac', '-proc:none', '--release', '25'))
        required = (
            'fibers/dev/latent/guest/runtime/Activation.java',
            'fibers/conformance/compiler/timer-source-control/OwnerAdmissionSourceControl.java',
            'fibers/conformance/compiler/timer-source-control/OwnerSettlementSourceControl.java',
            'fibers/conformance/compiler/timer-source-control/WorkFinishSourceControl.java',
            'fibers/conformance/compiler/timer-source-control/ScheduledNullFactoryActivationControl.java',
            'fibers/conformance/compiler/timer-source-control/dev/latent/generated/Bindings.java',
        )
        for name in required:
            with self.subTest(source=name):
                self.assertIn(compiler.sdk / name, compile_args)
                self.assertEqual(receipt['sourceInputs'][name], preparation.digest((compiler.sdk / name).read_bytes()))
        timer_sources = (
            'fibers/dev/latent/guest/runtime/util/Timer.java',
            'fibers/dev/latent/guest/runtime/util/TimerTask.java',
            'fibers/conformance/compiler/timer-source-control/TimerWaitAdmissionSourceControl.java',
            'fibers/conformance/compiler/timer-source-control/dev/latent/guest/runtime/util/TimerWaitHooks.java',
        )
        for name in timer_sources:
            with self.subTest(source=name):
                self.assertEqual(receipt['sourceInputs'][name], preparation.digest((compiler.sdk / name).read_bytes()))
        self.assertEqual(receipt['timerWorkerAdmission'], 'private-ledger-refusal-and-root-fence-passed')
        self.assertEqual(receipt['scheduledNullFactoryActivation'], list(NULL_FACTORY_CASES))
        for case, (_, argv) in zip(NULL_FACTORY_CASES, compiler.calls[2:2 + len(NULL_FACTORY_CASES)], strict=True):
            self.assertEqual(argv[:3], ('java', '-Xmx256m', '-cp'))
            self.assertEqual(argv[-2:], ('ScheduledNullFactoryActivationControl', case))
        start = 4 + len(NULL_FACTORY_CASES)
        for case, (_, argv) in zip(OWNER_CASES, compiler.calls[start:start + len(OWNER_CASES)], strict=True):
            self.assertEqual(argv[:3], ('java', '-Xmx256m', '-cp'))
            self.assertEqual(argv[-2:], ('OwnerAdmissionSourceControl', case))
        for case, (_, argv) in zip(SETTLEMENT_CASES, compiler.calls[start + len(OWNER_CASES):start + len(OWNER_CASES) + len(SETTLEMENT_CASES)], strict=True):
            self.assertEqual(argv[:3], ('java', '-Xmx256m', '-cp'))
            self.assertEqual(argv[-2:], ('OwnerSettlementSourceControl', case))
        for case, (_, argv) in zip(WORK_CASES, compiler.calls[start + len(OWNER_CASES) + len(SETTLEMENT_CASES):], strict=True):
            self.assertEqual(argv[:3], ('java', '-Xmx256m', '-cp'))
            self.assertEqual(argv[-3:], ('WorkFinishSourceControl', *case))
        self.assertEqual(receipt['workFinishCases'], [list(case) for case in WORK_CASES])
        self.assertEqual(receipt['ownerAdmissionCases'], list(OWNER_CASES))
        self.assertEqual(receipt['ownerSettlementCases'], list(SETTLEMENT_CASES))
        self.assertEqual(receipt['status'], 'SDK-source-control-passed')
        self.assertEqual(receipt['jarDigests'], {'mock.jar': 'mock'})
        self.assertIs(receipt['componentExecutionPerformed'], False)
        self.assertIs(receipt['actualGuestBindingsUsed'], False)

    def test_empty_wrong_duplicate_or_extra_owner_output_cannot_pass(self):
        for kind, cases in (('admission', OWNER_CASES), ('settlement', SETTLEMENT_CASES)):
            prefix = 'OWNER_' + kind.upper() + '_SOURCE PASS '
            for case in cases:
                good = prefix + case
                for invalid in ('', prefix + 'other', good + '\n' + good, good + '\nunexpected'):
                    with self.subTest(kind=kind, case=case, output=invalid):
                        stage = 'owner-' + kind + '-source-' + case
                        compiler = RecordingCompiler(lambda actual: invalid if actual == stage else None)
                        with self.assertRaisesRegex(ValueError, 'owner ' + kind + ' source control did not complete: ' + case):
                            self.run_control(compiler)
                        self.assertEqual(compiler.calls[-1][0], stage)

    def test_timer_worker_admission_output_must_match_exactly(self):
        stage = 'timer-worker-admission-source-control'
        good = 'TIMER_WAIT_ADMISSION_SOURCE PASS typed-refusal;accepted-callback-not-run;owners-retired;root-refused'
        for invalid in ('', good + '\n' + good, good + '\nunexpected'):
            with self.subTest(output=invalid):
                compiler = RecordingCompiler(lambda actual: invalid if actual == stage else None)
                with self.assertRaisesRegex(ValueError, 'Timer worker admission control did not complete'):
                    self.run_control(compiler)
                self.assertEqual(compiler.calls[-1][0], stage)

    def test_null_factory_outputs_must_match_each_selected_mode(self):
        for case in NULL_FACTORY_CASES:
            stage = 'scheduled-null-factory-activation-' + case
            good = 'SCHEDULED_NULL_FACTORY_ACTIVATION PASS ' + case
            for invalid in ('', 'SCHEDULED_NULL_FACTORY_ACTIVATION PASS other', good + '\n' + good):
                with self.subTest(case=case, output=invalid):
                    compiler = RecordingCompiler(lambda actual: invalid if actual == stage else None)
                    with self.assertRaisesRegex(ValueError, 'null-factory activation control did not complete: ' + case):
                        self.run_control(compiler)
                    self.assertEqual(compiler.calls[-1][0], stage)

    def test_work_finish_outputs_cannot_omit_duplicate_or_mislabel_a_case(self):
        for kind, mode in WORK_CASES:
            stage = 'work-finish-source-' + kind + '-' + mode
            good = 'WORK_FINISH_SOURCE PASS ' + kind + ' ' + mode
            for invalid in ('', good + '\n' + good, good + '\nunexpected',
                            'WORK_FINISH_SOURCE PASS other ' + mode, 'WORK_FINISH_SOURCE PASS ' + kind + ' other'):
                with self.subTest(kind=kind, mode=mode, output=invalid):
                    compiler = RecordingCompiler(lambda actual: invalid if actual == stage else None)
                    with self.assertRaisesRegex(ValueError, 'work finish source control did not complete: ' + kind + ' ' + mode):
                        self.run_control(compiler)
                    self.assertEqual(compiler.calls[-1][0], stage)

    def test_compiler_sleep_and_owner_failures_preserve_the_primary_error(self):
        stages = ('timer-sleep-admission-source-compile', 'timer-sleep-admission-source-control',
                  *('scheduled-null-factory-activation-' + case for case in NULL_FACTORY_CASES),
                  'timer-worker-admission-source-compile', 'timer-worker-admission-source-control',
                  *('owner-admission-source-' + case for case in OWNER_CASES),
                  *('owner-settlement-source-' + case for case in SETTLEMENT_CASES),
                  *('work-finish-source-' + kind + '-' + mode for kind, mode in WORK_CASES))
        for stage in stages:
            with self.subTest(stage=stage):
                error = subprocess.CalledProcessError(1, stage)
                def fail(actual):
                    if actual == stage:
                        raise error
                compiler = RecordingCompiler(fail)
                with self.assertRaises(subprocess.CalledProcessError) as caught:
                    self.run_control(compiler)
                self.assertIs(caught.exception, error)
                self.assertEqual(compiler.calls[-1][0], stage)

    def test_changed_runtime_control_or_ledger_source_cannot_receive_a_receipt(self):
        for name in ('fibers/dev/latent/guest/runtime/Activation.java',
                     'fibers/dev/latent/guest/runtime/util/Timer.java',
                     'fibers/conformance/compiler/timer-source-control/TimerWaitAdmissionSourceControl.java',
                     'fibers/conformance/compiler/timer-source-control/OwnerAdmissionSourceControl.java',
                     'fibers/conformance/compiler/timer-source-control/OwnerSettlementSourceControl.java',
                     'fibers/conformance/compiler/timer-source-control/WorkFinishSourceControl.java',
                     'fibers/conformance/compiler/timer-source-control/ScheduledNullFactoryActivationControl.java',
                     'fibers/conformance/compiler/timer-source-control/dev/latent/generated/Bindings.java'):
            with self.subTest(source=name):
                compiler = RecordingCompiler()
                original = preparation.read_file
                def changed(path, *args, **kwargs):
                    raw = original(path, *args, **kwargs)
                    if path == compiler.sdk / name and compiler.calls:
                        return raw + b'\n// changed during source control\n'
                    return raw
                with patch.object(preparation, 'read_file', side_effect=changed):
                    with self.assertRaisesRegex(ValueError, 'source inputs changed'):
                        self.run_control(compiler)


if __name__ == '__main__':
    unittest.main()
