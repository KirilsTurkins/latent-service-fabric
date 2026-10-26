"""Pure ownership and observation controls, without JVM/native execution."""
import copy
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from tools import java_capsule_project, java_dependency_authoring
from tools import java_dependency_resolution as resolution, java_fiber_library_inputs as capture
from tools import java_registry_tls, qualify_java_fibers
from tools import qualify_java_retained_fibers as observed
from tools.java_guest import compiler as compiler_module, compiler_profile_distribution as distribution


class PublishedJavaWorkerOwnership(unittest.TestCase):
    def test_expired_parent_refuses_before_capture_transaction_trust_or_sdk_io(self):
        with patch('time.monotonic', return_value=100), \
                patch.object(capture, 'fresh', side_effect=AssertionError('capture opened')), \
                patch.object(java_dependency_authoring, 'transaction', side_effect=AssertionError('transaction opened')), \
                patch.object(java_registry_tls, 'certificates', side_effect=AssertionError('trust opened')):
            calls = (lambda: capture.capture(Path('absent'), gradle='gradle', _deadline=105),
                lambda: resolution.resolve(Path('absent'), Path('candidate'), _deadline=105),
                lambda: java_registry_tls.prepare(Path('absent'), {}, Path('work'), Path('java'), {}, _deadline=105),
                lambda: distribution.extract(Path('absent'), Path('absent'), _deadline=105),
                lambda: qualify_java_fibers.prepare(Path('absent'), Path('sdk'),
                    fixture='worker-libraries', _deadline=105))
            for call in calls:
                with self.assertRaisesRegex(ValueError, 'deadline'):
                    call()
            with self.assertRaisesRegex(ValueError, 'deadline'):
                qualify_java_fibers.prepare(Path('absent'), Path('sdk'), fixture='threads', _deadline=1000)

    def test_real_resolver_path_clips_each_child_and_preserves_default_timeouts(self):
        class CapturedEnough(Exception):
            pass
        for deadline, expected in ((None, [30, 30, 300]), (1000, [25, 25, 295]), (122, [17, 17, 17])):
            with self.subTest(deadline=deadline), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                app = java_capsule_project.create(root / 'app', 'greeting')
                java_dependency_authoring.edit(app, 'add', coordinate='org.apache.commons:commons-lang3:3.14.0')
                tool = root / 'tool'
                tool.write_bytes(b'source-control-tool-not-executable')
                timeouts = []

                def runner(argv, cwd, env, timeout, maximum):
                    timeouts.append(timeout)
                    if len(timeouts) == 3:
                        self.assertIn('captureRuntime', argv)
                        raise CapturedEnough()
                    version = b'openjdk version "25.0.4.1+1"' if len(timeouts) == 1 else b'Gradle 9.1.0'
                    return SimpleNamespace(returncode=0, stdout=version, stderr=b'')

                with patch.object(resolution.shutil, 'which', return_value=str(tool)), \
                        patch.object(resolution, 'run_bounded_result', side_effect=runner), \
                        patch.object(java_registry_tls, 'prepare', return_value=((), {}, {}, None)) as trust, \
                        patch('time.monotonic', return_value=100):
                    options = {} if deadline is None else {'_deadline': deadline}
                    with self.assertRaises(CapturedEnough):
                        resolution.resolve(app, root / 'candidate.json', gradle=str(tool), **options)
                    self.assertEqual(timeouts, expected)
                    self.assertEqual(trust.call_args.kwargs, options)
                    self.assertFalse((root / 'candidate.json').exists())

    def test_actual_compiler_runner_keeps_original_argv_and_cleanup_inside_selected_caps(self):
        for parent, expected in ((None, 600), (2000, 595), (130, 25)):
            with self.subTest(parent=parent), tempfile.TemporaryDirectory() as temporary:
                compiler = compiler_module.Compiler.__new__(compiler_module.Compiler)
                compiler._parent_deadline, compiler.deadline = parent, 3000
                compiler.directory, compiler.environment = Path(temporary), {}
                compiler.paths, compiler.records, compiler.retained_bytes = {'java': Path('fixed-java')}, [], 0
                result = SimpleNamespace(returncode=0, stdout=b'42', stderr=b'')
                with patch.object(compiler_module, 'run_bounded_result', return_value=result) as run, \
                        patch('time.monotonic', return_value=100):
                    self.assertEqual(compiler.run('reference', 'java', '-cp', 'original', 'Main'), '42\n')
                    self.assertEqual(run.call_args.args[0], ['fixed-java', '-cp', 'original', 'Main'])
                    self.assertEqual(run.call_args.kwargs['timeout_seconds'], expected)
                self.assertEqual(compiler.records[0]['exitCode'], 0)

    def test_closed_worker_rows_require_actual_ids_original_budgets_and_idle_counters(self):
        rows = [{**dict.fromkeys(observed.ZERO_FIELDS, 0),
            'activationId': f'java-worker-libraries-{index // 4}-{index % 4}',
            'iteration': index // 4, 'mode': index % 4, 'value': 42,
            'cpuFuel': 123, 'reportedPeakMemoryBytes': 4096,
            'storesBefore': index, 'storesCreated': index + 1} for index in range(12)]

        def output(values, worker=True):
            case = observed.WORKER_CASE if worker else observed.CASE
            profile = 'teavm-activation-fibers-io-v1' if worker else 'teavm-activation-fibers-v1'
            return ('\n'.join(['test ' + case + ' ... ok',
                profile + ' signed-preparation-setup-micros=1 stores-created=0 guest-activations=0',
                *['LSF_JAVA_RETAINED=' + json.dumps(row) for row in values],
                'test result: ok. 1 passed; 0 failed; 0 ignored; 0 measured; 51 filtered out;']) + '\n').encode()

        self.assertEqual(observed.observations(output(rows), worker=True)['calls'], rows)
        for field, value in (('activationId', rows[0]['activationId']), ('liveStores', 1),
                ('storesBefore', 0), ('cpuFuel', 10_000_000_001), ('cpuFuel', True),
                ('reportedPeakMemoryBytes', 64 * 1024**2 + 1)):
            bad = copy.deepcopy(rows)
            bad[11][field] = value
            with self.assertRaises(ValueError):
                observed.observations(output(bad), worker=True)
        with self.assertRaisesRegex(ValueError, 'exact-case'):
            observed.observations(output(rows, False), worker=True)
        legacy = [{**row, 'activationId': f'java-fibers-{index // 4}-{index % 4}'}
                  for index, row in enumerate(rows)]
        self.assertEqual(observed.observations(output(legacy, False))['calls'], legacy)


if __name__ == '__main__':
    unittest.main()
