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
        self.assertIn(sdk / 'fibers/conformance/compiler/scheduled-source-control/ExecutorInvokeAllOwnerControl.java', argv)
        reference_argv = next(args for stage, args in calls if stage == 'scheduled-stopped-reference-compile')
        self.assertIn(sdk / 'fibers/conformance/compiler/scheduled-source-control/ExecutorInvokeAllWaitReferenceControl.java',
                      reference_argv)
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
        if stage in ('scheduled-ready-clock-compile', 'scheduled-ready-manual-clock-compile'): return ''
        if stage == 'scheduled-ready-clock-boundary':
            return ('boundary=49:cancelled=true:held=1:1:1:active=none:final=0:0:0\n'
                    'boundary=50:cancelled=false:held=1:2:2:active=1:1:1:final=0:0:0\n'
                    'boundary=51:cancelled=false:held=1:2:2:active=1:1:1:final=0:0:0')
        if stage == 'scheduled-ready-clock-failure':
            return 'clock-failure=propagated:held=1:1:1:laterCancelled=true:final=0:0:0'
        if stage == 'scheduled-ready-clock-post': return 'normal-post:clock-unread;all-settled-once'
        if stage == 'scheduled-ready-clock-manual': return 'manual-post:result-held-until-caller-return;all-settled-once'
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
            'scheduled-ready-clock-compile', 'scheduled-ready-clock-boundary', 'scheduled-ready-clock-failure',
            'scheduled-ready-clock-post', 'scheduled-ready-manual-clock-compile', 'scheduled-ready-clock-manual'])
        self.assertEqual(report, {'status': 'JDK-and-SDK-source-controls-passed', 'clockFailure': 'synthetic-host-only',
            'postDequeue': 'normal-and-manual-source-ledger-passed',
            'componentExecutionPerformed': False, 'actualGuestBindingsUsed': False})

    def test_missing_and_wrong_receipts_fail_closed(self):
        for stage in ('scheduled-ready-shutdown-jdk', 'scheduled-ready-shutdown-source',
                      'scheduled-ready-clock-boundary', 'scheduled-ready-clock-failure',
                      'scheduled-ready-clock-post', 'scheduled-ready-clock-manual'):
            for bad in ('', 'SKIPPED'):
                with self.subTest(stage=stage, bad=bad), tempfile.TemporaryDirectory() as temporary:
                    calls = []
                    def run(actual, *args):
                        calls.append(actual)
                        return bad if actual == stage else self.receipt(actual)
                    with self.assertRaisesRegex(ValueError, 'Java scheduled (ready|post-dequeue|manual post-dequeue) .*control did not complete'):
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

    def test_changed_dequeue_hook_is_rejected_before_manual_compile(self):
        original = subject.read_file
        def read(path, *args):
            raw = original(path, *args)
            if path.name == 'ScheduledThreadPoolExecutor.java':
                return raw.replace(b'queue.remove(index); running++;', b'changed dequeue')
            return raw
        calls = []
        def run(stage, *args):
            calls.append(stage)
            return self.receipt(stage)
        with tempfile.TemporaryDirectory() as temporary, patch.object(subject, 'read_file', side_effect=read):
            with self.assertRaisesRegex(ValueError, 'dequeue source is ambiguous'):
                self.run_control(Path(temporary), run)
        self.assertEqual(calls[-1], 'scheduled-ready-clock-post')
        self.assertNotIn('scheduled-ready-manual-clock-compile', calls)


class ScheduledNoopCancellationControl(unittest.TestCase):
    @staticmethod
    def receipt(stage):
        if stage in ('scheduled-noop-cancel-jdk', 'scheduled-noop-cancel-source'):
            return 'SCHEDULED_NOOP_CANCEL_REFERENCE PASS completed;cancelled;public-monitor'
        owners = {
            'copy': 'completed-copy:cancel=false:withdrawn=true:settled-once=true',
            'cancelled': 'cancelled:returnedWhileHeld=true:settled-once=true',
            'running': 'running:returnedWhileHeld=false:original-owners-held=true:settled-once=true',
            'manual': 'manual:returnedWhileHeld=true:result-held=true:settled-once=true',
            'refused': 'refused:returnedWhileHeld=true:poisoned=true:original-retained=true:attempts=1',
            'lost': 'lost:returnedWhileHeld=true:poisoned=true:original-retained=true:attempts=1'}
        if stage.startswith('scheduled-noop-owner-'): return owners[stage.removeprefix('scheduled-noop-owner-')]
        inflight = {'success': ('0:0:0', 'false'), 'refused': ('1:1:0', 'true'), 'lost': ('1:0:0', 'true')}
        if stage.startswith('scheduled-noop-inflight-'):
            mode = stage.removeprefix('scheduled-noop-inflight-'); remaining, poisoned = inflight[mode]
            return (mode + ':secondReturnedWhileSettlementPending=true:held=1:1:0:settlementAttempts=1:poisoned='
                    + poisoned + ':remaining=' + remaining)
        raise AssertionError(stage)

    def test_all_selected_receipts_and_limits(self):
        calls = []
        def run(stage, *args):
            calls.append(stage)
            return self.receipt(stage)
        report = subject.scheduled_noop_cancel_control(SimpleNamespace(run=run), Path('source'), Path('reference'))
        self.assertEqual(calls, ['scheduled-noop-cancel-jdk', 'scheduled-noop-cancel-source',
            'scheduled-noop-owner-copy', 'scheduled-noop-owner-cancelled', 'scheduled-noop-owner-running',
            'scheduled-noop-owner-manual', 'scheduled-noop-owner-refused', 'scheduled-noop-owner-lost', 'scheduled-noop-inflight-success',
            'scheduled-noop-inflight-refused', 'scheduled-noop-inflight-lost'])
        self.assertEqual(report, {'status': 'JDK-and-SDK-source-controls-passed', 'inflight': 'synthetic-host-only',
            'componentExecutionPerformed': False, 'actualGuestBindingsUsed': False})

    def test_missing_and_wrong_receipts_fail_closed(self):
        for stage in ('scheduled-noop-cancel-jdk', 'scheduled-noop-cancel-source', 'scheduled-noop-owner-copy',
                      'scheduled-noop-owner-cancelled', 'scheduled-noop-owner-running', 'scheduled-noop-owner-manual', 'scheduled-noop-owner-refused',
                      'scheduled-noop-owner-lost', 'scheduled-noop-inflight-success', 'scheduled-noop-inflight-refused',
                      'scheduled-noop-inflight-lost'):
            for bad in ('', 'SKIPPED'):
                with self.subTest(stage=stage, bad=bad):
                    calls = []
                    def run(actual, *args):
                        calls.append(actual)
                        return bad if actual == stage else self.receipt(actual)
                    with self.assertRaisesRegex(ValueError, 'Java scheduled no-op .* control did not complete'):
                        subject.scheduled_noop_cancel_control(SimpleNamespace(run=run), Path('source'), Path('reference'))
                    self.assertEqual(calls[-1], stage)

    def test_process_failure_is_propagated_without_retry(self):
        failure = RuntimeError('owned-process-failed');calls = []
        def run(stage, *args):
            calls.append(stage)
            if stage == 'scheduled-noop-inflight-refused': raise failure
            return self.receipt(stage)
        with self.assertRaises(RuntimeError) as caught:
            subject.scheduled_noop_cancel_control(SimpleNamespace(run=run), Path('source'), Path('reference'))
        self.assertIs(caught.exception, failure)
        self.assertEqual(calls.count('scheduled-noop-inflight-refused'), 1)
        self.assertNotIn('scheduled-noop-inflight-lost', calls)


class ExecutorInvokeAllWaitControl(unittest.TestCase):
    @staticmethod
    def receipt(stage):
        if stage in ('executor-invoke-all-wait-jdk', 'executor-invoke-all-wait-source'):
            return ('INVOKE_ALL_WAIT PASS completed;subclass;late;negative-get;timeout-suffix;'
                    'exception;done-failure;nonpositive')
        if stage in ('executor-invoke-all-owner-timeout', 'executor-invoke-all-owner-optimistic',
                     'executor-invoke-all-owner-prefix'):
            mode = stage.removeprefix('executor-invoke-all-owner-')
            return ('INVOKE_ALL_OWNER ' + mode + ' held=1:1:' + ('1' if mode == 'prefix' else '0')
                    + ' retired=0:0:0 result-settle=1')
        raise AssertionError(stage)

    def test_original_source_and_owner_cases_are_required(self):
        calls = []
        def run(stage, *args):
            calls.append((stage, args)); return self.receipt(stage)
        report = subject.executor_invoke_all_wait_control(SimpleNamespace(run=run), Path('source'), Path('jdk'))
        self.assertEqual([stage for stage, _ in calls], ['executor-invoke-all-wait-jdk',
            'executor-invoke-all-wait-source', 'executor-invoke-all-owner-timeout',
            'executor-invoke-all-owner-optimistic', 'executor-invoke-all-owner-prefix'])
        self.assertEqual(calls[0][1], ('java', '-Xmx256m', '-cp', Path('jdk'),
                                      'ExecutorInvokeAllWaitReferenceControl'))
        self.assertEqual(calls[1][1], ('java', '-Xmx256m', '-cp', Path('source'),
                                      'ExecutorInvokeAllWaitReferenceControl'))
        self.assertEqual(calls[2][1][-2:], ('ExecutorInvokeAllOwnerControl', 'timeout'))
        self.assertEqual(calls[3][1][-2:], ('ExecutorInvokeAllOwnerControl', 'optimistic'))
        self.assertEqual(calls[4][1][-2:], ('ExecutorInvokeAllOwnerControl', 'prefix'))
        self.assertEqual(report, {'status': 'JDK-and-SDK-source-controls-passed',
            'ownership': 'synthetic-host-ledger-only', 'firstSubmissionDeadline': 'unchanged',
            'componentExecutionPerformed': False, 'actualGuestBindingsUsed': False})

    def test_missing_wrong_and_duplicate_receipts_fail_closed(self):
        stages = ('executor-invoke-all-wait-jdk', 'executor-invoke-all-wait-source',
                  'executor-invoke-all-owner-timeout', 'executor-invoke-all-owner-optimistic',
                  'executor-invoke-all-owner-prefix')
        for missing in stages:
            for bad in ('', 'SKIPPED', self.receipt(missing) + '\n' + self.receipt(missing)):
                with self.subTest(stage=missing, bad=bad):
                    calls = []
                    def run(stage, *args):
                        calls.append(stage); return bad if stage == missing else self.receipt(stage)
                    with self.assertRaisesRegex(ValueError, 'Java executor invokeAll .* control did not complete'):
                        subject.executor_invoke_all_wait_control(SimpleNamespace(run=run), Path('source'), Path('jdk'))
                    self.assertEqual(calls[-1], missing)

    def test_process_failure_is_not_retried(self):
        failure = RuntimeError('owned-process-failed'); calls = []
        def run(stage, *args):
            calls.append(stage)
            if stage == 'executor-invoke-all-owner-timeout': raise failure
            return self.receipt(stage)
        with self.assertRaises(RuntimeError) as caught:
            subject.executor_invoke_all_wait_control(SimpleNamespace(run=run), Path('source'), Path('jdk'))
        self.assertIs(caught.exception, failure)
        self.assertEqual(calls.count('executor-invoke-all-owner-timeout'), 1)
        self.assertNotIn('executor-invoke-all-owner-optimistic', calls)


class ExecutorInvokeAnyReadyControl(unittest.TestCase):
    @staticmethod
    def receipt(stage):
        if stage in ('executor-invoke-any-ready-jdk', 'executor-invoke-any-ready-source'):
            return ('EXECUTOR_INVOKE_ANY_READY PASS one;zero;failure;rejection;all-failed;'
                    'null-rule;iterator-observed')
        owners = {
            'parallel': 'parallel:result=42:held=1:0:1:pending=true:cancelInterrupt=true:after=0:0:0',
            'timeout': 'timeout:outcome=timeout:held=1:2:0:pending=true:after=0:0:0',
            'interrupt': 'interrupt:outcome=interrupted:held=1:2:0:pending=true:after=0:0:0',
            'accepted-throw': 'accepted-throw:held=1:1:0:pending=true:callbacks=0:after=0:0:0',
        }
        if stage.startswith('executor-invoke-any-owner-'):
            return owners[stage.removeprefix('executor-invoke-any-owner-')]
        raise AssertionError(stage)

    def test_all_selected_receipts_and_limits(self):
        calls = []
        def run(stage, *args):
            calls.append((stage, args))
            return self.receipt(stage)
        source = Path('source'); reference = Path('reference')
        report = subject.executor_invoke_any_ready_control(SimpleNamespace(run=run), source, reference)
        self.assertEqual([stage for stage, _ in calls], ['executor-invoke-any-ready-jdk',
            'executor-invoke-any-ready-source', 'executor-invoke-any-owner-parallel',
            'executor-invoke-any-owner-timeout', 'executor-invoke-any-owner-interrupt',
            'executor-invoke-any-owner-accepted-throw'])
        self.assertEqual(calls[0][1], ('java', '-Xmx256m', '-cp', reference,
                                       'ExecutorInvokeAnyReadyReferenceControl', 'jdk'))
        self.assertEqual(calls[1][1], ('java', '-Xmx256m', '-cp', source,
                                       'ExecutorInvokeAnyReadyReferenceControl', 'source'))
        self.assertEqual(calls[3][1][-2:], ('InvokeAnyPendingOwnerProbe', 'timeout'))
        self.assertEqual(calls[4][1][-2:], ('InvokeAnyPendingOwnerProbe', 'interrupt'))
        self.assertEqual(report, {'status': 'JDK-and-SDK-source-controls-passed',
            'iterator': 'SDK-validates-after-ready-JDK-returns-early', 'ownership': 'synthetic-host-ledger-only',
            'componentExecutionPerformed': False, 'actualGuestBindingsUsed': False})

    def test_every_missing_wrong_or_duplicate_receipt_fails_closed(self):
        stages = ('executor-invoke-any-ready-jdk', 'executor-invoke-any-ready-source',
                  'executor-invoke-any-owner-parallel', 'executor-invoke-any-owner-timeout',
                  'executor-invoke-any-owner-interrupt', 'executor-invoke-any-owner-accepted-throw')
        for missing in stages:
            for bad in ('', 'SKIPPED', self.receipt(missing) + '\n' + self.receipt(missing)):
                with self.subTest(stage=missing, bad=bad):
                    calls = []
                    def run(stage, *args):
                        calls.append(stage)
                        return bad if stage == missing else self.receipt(stage)
                    with self.assertRaisesRegex(ValueError, 'Java executor invokeAny .* control did not complete'):
                        subject.executor_invoke_any_ready_control(SimpleNamespace(run=run), Path('source'), Path('reference'))
                    self.assertEqual(calls[-1], missing)

    def test_failure_is_propagated_without_retry(self):
        failure = RuntimeError('owned-process-failed'); calls = []
        def run(stage, *args):
            calls.append(stage)
            if stage == 'executor-invoke-any-owner-timeout': raise failure
            return self.receipt(stage)
        with self.assertRaises(RuntimeError) as caught:
            subject.executor_invoke_any_ready_control(SimpleNamespace(run=run), Path('source'), Path('reference'))
        self.assertIs(caught.exception, failure)
        self.assertEqual(calls.count('executor-invoke-any-owner-timeout'), 1)
        self.assertNotIn('executor-invoke-any-owner-interrupt', calls)
