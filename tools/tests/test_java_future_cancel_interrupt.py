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
        self.assertEqual(calls[-1][0], 'scheduled-source-compile')
        argv = calls[-1][1]
        self.assertEqual(argv[:4], ('javac', '-proc:none', '--release', '25'))
        self.assertEqual(argv.count(control), 1)
        self.assertIn(sdk / 'fibers/dev/latent/guest/runtime/concurrent/FutureTask.java', argv)

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
