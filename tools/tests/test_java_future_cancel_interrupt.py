"""Qualification wiring and failure propagation, not Java guest execution proof."""
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from tools import qualify_java_fibers as subject


class FutureCancellationControl(unittest.TestCase):
    def test_every_selected_mode_runs_in_a_fresh_owned_process(self):
        calls = []
        classes = Path('compiled-private-source')

        def run(stage, *argv):
            calls.append((stage, argv))
            implementation, mode = argv[-2:]
            return f'future-cancel-interrupt {implementation} {mode} passed\n'

        compiler = SimpleNamespace(run=run)
        receipt = subject.future_cancel_interrupt_control(compiler, classes)
        expected = {
            'jdk': list(subject.FUTURE_CANCEL_INTERRUPT_CASES),
            'source': [*subject.FUTURE_CANCEL_INTERRUPT_CASES, *subject.FUTURE_CANCEL_SETTLEMENT_CASES],
        }
        self.assertEqual(receipt, {'status': 'JDK-and-SDK-source-controls-passed', 'cases': expected,
            'componentExecutionPerformed': False, 'actualGuestBindingsUsed': False})
        self.assertEqual(len(calls), sum(map(len, expected.values())))
        self.assertEqual(len({stage for stage, _ in calls}), len(calls))
        index = 0
        for implementation, modes in expected.items():
            for mode in modes:
                self.assertEqual(calls[index], ('future-cancel-interrupt-' + implementation + '-' + mode,
                    ('java', '-Xmx256m', '-cp', classes,
                     'dev.latent.guest.runtime.concurrent.FutureTaskInterruptFailureControl', implementation, mode)))
                index += 1
        self.assertFalse(set(expected['jdk']) & set(subject.FUTURE_CANCEL_SETTLEMENT_CASES))

    def test_missing_wrong_duplicate_or_skipped_success_is_refused(self):
        first = subject.FUTURE_CANCEL_INTERRUPT_CASES[0]
        marker = f'future-cancel-interrupt jdk {first} passed'
        for text in ('', 'SKIPPED', marker.replace('jdk', 'source'), marker.replace(first, 'normal'),
                     marker + '\n' + marker, marker + '\nFAIL'):
            with self.subTest(text=text):
                calls = []

                def run(stage, *argv):
                    calls.append(stage)
                    return text

                with self.assertRaisesRegex(ValueError, 'Java future cancellation control did not complete'):
                    subject.future_cancel_interrupt_control(SimpleNamespace(run=run), Path('classes'))
                self.assertEqual(len(calls), 1)

    def test_process_error_is_not_relabelled_or_retried(self):
        for implementation, mode in (('jdk', 'before-runtime'), ('source', 'after-error'),
                                     ('source', 'refused'), ('source', 'lost-ack')):
            with self.subTest(implementation=implementation, mode=mode):
                failure = RuntimeError('owned-process-failed')
                calls = []

                def run(stage, *argv):
                    calls.append((argv[-2], argv[-1]))
                    if calls[-1] == (implementation, mode):
                        raise failure
                    return f'future-cancel-interrupt {argv[-2]} {argv[-1]} passed'

                with self.assertRaises(RuntimeError) as caught:
                    subject.future_cancel_interrupt_control(SimpleNamespace(run=run), Path('classes'))
                self.assertIs(caught.exception, failure)
                self.assertEqual(calls[-1], (implementation, mode))
                self.assertEqual(calls.count((implementation, mode)), 1)

    def test_scheduled_owner_compiles_control_and_propagates_matrix_failure(self):
        """The production owner, not an alternate test entry point, selects the matrix."""
        calls = []
        sdk = subject.ROOT / 'sdk/java-guest'
        control = sdk / 'fibers/conformance/compiler/scheduled-source-control/FutureTaskInterruptFailureControl.java'

        def run(stage, *argv):
            calls.append((stage, argv))
            if stage == 'scheduled-stopped-reference-jdk':
                return ('SCHEDULED_STOPPED_REFERENCE PASS delayed;fixed-rate;fixed-delay;nested;future;'
                    'running;shutdown;shutdown-policy;physical-runner')
            if stage == 'scheduled-periodic-reference-jdk':
                return ('SCHEDULED_PERIODIC_REFERENCE PASS fixed-rate;fixed-delay;reentrant;failure;self-cancel;'
                    'concurrent-manual;concurrent-worker;shutdown;continue-policy')
            if stage in ('executor-invoke-interrupt-reference-jdk', 'executor-invoke-interrupt-source'):
                return ('EXECUTOR_INVOKE_INTERRUPT PASS preinterrupted-ready;empty;zero;pending-cancel;'
                    'blocked-interrupt')
            if stage == 'executor-invoke-interrupt-owner':
                return 'EXECUTOR_INVOKE_INTERRUPT_OWNER PASS all;any;queued-until-drain;result-settled'
            if stage in ('executor-await-termination-reference-jdk', 'executor-await-termination-source'):
                return 'EXECUTOR_AWAIT_TERMINATION PASS zero;negative;positive;terminated;blocked-interrupt;override'
            if stage == 'executor-await-termination-owner':
                return 'EXECUTOR_AWAIT_TERMINATION_OWNER PASS managed;scheduled;owners-held-until-worker-return;override'
            if stage in ('future-task-null-failure-reference-jdk', 'future-task-null-failure-source'):
                return 'FUTURE_TASK_NULL_FAILURE PASS pending;null-success;terminal-noop;nonnull;blocked-getter'
            if stage == 'future-task-null-failure-owner':
                return 'FUTURE_TASK_NULL_FAILURE_OWNER PASS original-result-held-until-runner-exit'
            if stage in ('future-task-monitor-reference-jdk', 'future-task-monitor-source'):
                return 'FUTURE_TASK_MONITOR_REFERENCE PASS run;cancel;completed-get;executor;scheduled-cancel;failed-get-callback'
            if stage == 'future-task-monitor-owner':
                return 'FUTURE_TASK_MONITOR_OWNER PASS managed;active-owners;scheduled;retired-under-public-monitor;failure-owner'
            if stage in ('default-executor-monitor-reference-jdk', 'default-executor-monitor-source'):
                return 'DEFAULT_EXECUTOR_MONITOR_REFERENCE PASS cold;warm'
            if stage.startswith('default-executor-monitor-owner-'):
                return 'DEFAULT_EXECUTOR_OWNER PASS ' + argv[-1]
            if stage.endswith('-compile'):
                return ''
            raise AssertionError('execution continued after the failed matrix')

        compiler = SimpleNamespace(sdk=sdk, run=run)
        failure = RuntimeError('cancellation-control-failed')
        with tempfile.TemporaryDirectory() as temporary, \
                patch.object(subject, 'future_cancel_interrupt_control', side_effect=failure) as matrix:
            output = Path(temporary) / 'source'
            with self.assertRaises(RuntimeError) as caught:
                subject.scheduled_source_control(compiler, output)
            self.assertIs(caught.exception, failure)
            matrix.assert_called_once_with(compiler, output)
        self.assertEqual([stage for stage, _ in calls[-15:]], ['scheduled-source-compile',
            'executor-invoke-interrupt-source', 'executor-invoke-interrupt-owner',
            'executor-await-termination-source', 'executor-await-termination-owner',
            'future-task-null-failure-source', 'future-task-null-failure-owner',
            'future-task-monitor-source', 'future-task-monitor-owner', 'default-executor-monitor-source',
            'default-executor-monitor-owner-denied', 'default-executor-monitor-owner-manage',
            'default-executor-monitor-owner-uncertain', 'default-executor-monitor-owner-concurrent',
            'default-executor-monitor-owner-rejection-lock'])
        self.assertIn('executor-invoke-interrupt-reference-jdk', [stage for stage, _ in calls])
        self.assertIn('executor-await-termination-reference-jdk', [stage for stage, _ in calls])
        self.assertIn('future-task-null-failure-reference-jdk', [stage for stage, _ in calls])
        self.assertIn('future-task-monitor-reference-jdk', [stage for stage, _ in calls])
        self.assertIn('default-executor-monitor-reference-jdk', [stage for stage, _ in calls])
        argv = calls[-15][1]
        self.assertEqual(argv[:4], ('javac', '-proc:none', '--release', '25'))
        self.assertEqual(argv.count(control), 1)
        self.assertIn(sdk / 'fibers/dev/latent/guest/runtime/concurrent/FutureTask.java', argv)
        self.assertIn(sdk / 'fibers/conformance/compiler/scheduled-source-control/ExecutorInvokeInterruptOwnerControl.java', argv)
        self.assertIn(sdk / 'fibers/conformance/compiler/scheduled-source-control/ExecutorAwaitTerminationOwnerControl.java', argv)
        self.assertIn(sdk / 'fibers/conformance/compiler/scheduled-source-control/FutureTaskNullFailureOwnerControl.java', argv)
        self.assertIn(sdk / 'fibers/conformance/compiler/scheduled-source-control/FutureTaskMonitorOwnerControl.java', argv)
        self.assertIn(sdk / 'fibers/conformance/compiler/scheduled-source-control/DefaultExecutorOwnerControl.java', argv)
        for missing in ('executor-invoke-interrupt-reference-jdk', 'executor-invoke-interrupt-source',
                        'executor-invoke-interrupt-owner', 'executor-await-termination-reference-jdk',
                        'executor-await-termination-source', 'executor-await-termination-owner',
                        'future-task-null-failure-reference-jdk', 'future-task-null-failure-source',
                        'future-task-null-failure-owner', 'future-task-monitor-reference-jdk',
                        'future-task-monitor-source', 'future-task-monitor-owner',
                        'default-executor-monitor-reference-jdk', 'default-executor-monitor-source',
                        'default-executor-monitor-owner-denied', 'default-executor-monitor-owner-manage',
                        'default-executor-monitor-owner-uncertain', 'default-executor-monitor-owner-concurrent',
                        'default-executor-monitor-owner-rejection-lock'):
            with self.subTest(missing=missing), tempfile.TemporaryDirectory() as temporary, \
                    patch.object(subject, 'future_cancel_interrupt_control') as matrix:
                def incomplete(stage, *arguments):
                    return 'SKIPPED' if stage == missing else run(stage, *arguments)
                incomplete_compiler = SimpleNamespace(sdk=sdk, run=incomplete)
                with self.assertRaisesRegex(ValueError, 'Java (executor (invoke|termination)|future task null failure|FutureTask monitor|default executor monitor) .*'):
                    subject.scheduled_source_control(incomplete_compiler, Path(temporary) / 'source')
                matrix.assert_not_called()

    def test_missing_control_is_refused_before_compilation_or_execution(self):
        sdk = subject.ROOT / 'sdk/java-guest'
        original = subject.read_file

        def read(path, *args):
            if path.name == 'FutureTaskInterruptFailureControl.java':
                raise FileNotFoundError('missing-cancellation-control')
            return original(path, *args)

        with tempfile.TemporaryDirectory() as temporary, patch.object(subject, 'read_file', side_effect=read), \
                patch.object(subject, 'future_cancel_interrupt_control') as matrix:
            calls = []
            compiler = SimpleNamespace(sdk=sdk, run=lambda *args: calls.append(args))
            output = Path(temporary) / 'source'
            with self.assertRaisesRegex(FileNotFoundError, 'missing-cancellation-control'):
                subject.scheduled_source_control(compiler, output)
            matrix.assert_not_called()
            self.assertEqual(calls, [])
            self.assertFalse(output.exists())


class ScheduledReadyShutdownControl(unittest.TestCase):
    @staticmethod
    def receipt(stage):
        if stage in ('scheduled-ready-shutdown-jdk', 'scheduled-ready-shutdown-source'):
            return 'SCHEDULED_READY_SHUTDOWN PASS disabled;changed;elapsed;default;periodic;owners'
        if stage == 'scheduled-ready-clock-compile': return ''
        if stage == 'scheduled-ready-clock-boundary':
            return ('boundary=49:cancelled=true:held=1:1:1:active=none:final=0:0:0\n'
                    'boundary=50:cancelled=false:held=1:2:2:active=1:1:1:final=0:0:0\n'
                    'boundary=51:cancelled=false:held=1:2:2:active=1:1:1:final=0:0:0')
        if stage == 'scheduled-ready-clock-failure':
            return 'clock-failure=propagated:held=1:1:1:laterCancelled=true:final=0:0:0'
        raise AssertionError(stage)

    @staticmethod
    def sources():
        fibers = subject.ROOT / 'sdk/java-guest/fibers'
        return (sorted((fibers / 'dev/latent/guest/runtime/concurrent').glob('*.java')),
                fibers / 'conformance/compiler/scheduled-source-control')

    def run_control(self, root, run):
        ports, private = self.sources()
        output = root / 'source'; output.mkdir()
        return subject.scheduled_ready_shutdown_control(SimpleNamespace(run=run), output, root / 'reference', ports, private)

    def test_all_selected_receipts_and_limits(self):
        calls = []
        def run(stage, *args):
            calls.append(stage)
            return self.receipt(stage)
        with tempfile.TemporaryDirectory() as temporary:
            report = self.run_control(Path(temporary), run)
        self.assertEqual(calls, ['scheduled-ready-shutdown-jdk', 'scheduled-ready-shutdown-source',
            'scheduled-ready-clock-compile', 'scheduled-ready-clock-boundary', 'scheduled-ready-clock-failure'])
        self.assertEqual(report, {'status': 'JDK-and-SDK-source-controls-passed', 'clockFailure': 'synthetic-host-only',
            'componentExecutionPerformed': False, 'actualGuestBindingsUsed': False})

    def test_missing_and_wrong_receipts_fail_closed(self):
        for stage in ('scheduled-ready-shutdown-jdk', 'scheduled-ready-shutdown-source',
                      'scheduled-ready-clock-boundary', 'scheduled-ready-clock-failure'):
            for bad in ('', 'SKIPPED'):
                with self.subTest(stage=stage, bad=bad), tempfile.TemporaryDirectory() as temporary:
                    calls = []
                    def run(actual, *args):
                        calls.append(actual)
                        return bad if actual == stage else self.receipt(actual)
                    with self.assertRaisesRegex(ValueError, 'Java scheduled ready .* control did not complete'):
                        self.run_control(Path(temporary), run)
                    self.assertEqual(calls[-1], stage)

    def test_changed_clock_hook_is_rejected_before_clock_compile(self):
        original = subject.read_file
        def read(path, *args):
            raw = original(path, *args)
            if path.name == 'ScheduledThreadPoolExecutor.java':
                return raw.replace(b'private long elapsed() { return System.nanoTime() - origin; }', b'changed clock')
            return raw
        calls = []
        def run(stage, *args):
            calls.append(stage)
            return self.receipt(stage)
        with tempfile.TemporaryDirectory() as temporary, patch.object(subject, 'read_file', side_effect=read):
            with self.assertRaisesRegex(ValueError, 'clock source is ambiguous'):
                self.run_control(Path(temporary), run)
        self.assertEqual(calls, ['scheduled-ready-shutdown-jdk', 'scheduled-ready-shutdown-source'])
