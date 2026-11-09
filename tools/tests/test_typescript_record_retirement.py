"""Compile the actual owner classes; JS doubles establish no engine semantics."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]


class RecordRetirementTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        compiler = os.environ.get('LSF_TYPESCRIPT_RECORD_CXX') or shutil.which('c++')
        if compiler is None:
            if os.name == 'nt':
                raise unittest.SkipTest('Set LSF_TYPESCRIPT_RECORD_CXX for the finite C++ reference')
            raise RuntimeError('C++ compiler is required for record lifetime controls')
        cls.temporary = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temporary.cleanup)
        output = Path(cls.temporary.name)
        msvc = Path(compiler).stem.lower() == 'cl'
        cls.binary = output / ('records.exe' if os.name == 'nt' else 'records')
        args = [compiler]
        args += ['-std=c++17', '-O0', '-Wall', '-Wextra', '-Werror',
                 '-I', str(ROOT/'tools/tests/fixtures/typescript_record_retirement'),
                 str(ROOT/'sdk/typescript-guest/activation/tests/record_retirement.cpp')]
        args += ['-o', str(cls.binary)]
        if msvc:
            args = [compiler, '/nologo', '/std:c++17', '/EHsc', '/W4', '/WX',
                    '/I' + str(ROOT/'tools/tests/fixtures/typescript_record_retirement'),
                    str(ROOT/'sdk/typescript-guest/activation/tests/record_retirement.cpp'),
                    '/Fe:' + str(cls.binary), '/Fo:' + str(output/'records.obj')]
        result = subprocess.run(args, capture_output=True, timeout=60)
        if result.returncode or len(result.stdout) + len(result.stderr) > 65536:
            raise AssertionError(result.stderr[:65536].decode(errors='replace'))
        if not cls.binary.is_file() or cls.binary.stat().st_size > 4*1024**2:
            raise AssertionError('finite record reference output required')

    def control(self, case):
        command = [str(self.binary), case]
        result = subprocess.run(command, capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0, (result.stdout + result.stderr)[:65536])
        self.assertLessEqual(len(result.stdout) + len(result.stderr), 65536)
        self.assertEqual(json.loads(result.stdout),
                         {'case': case, 'passed': True, 'engineQualified': False})

    def test_promise_tracking_allocation_dies_before_refund(self):
        self.control('promise-ack-after-delete')

    def test_promise_refused_ack_retains_exact_owner_without_allocation(self):
        self.control('promise-refused-ack-retains-owner')

    def test_reaction_tracking_allocation_dies_before_refund(self):
        self.control('reaction-ack-after-delete')

    def test_reaction_partial_ack_cannot_double_refund_job_owners(self):
        self.control('reaction-partial-ack-retains-owner')

    def test_completed_job_destroys_callable_root_before_refund(self):
        self.control('job-ack-after-delete')

    def test_failed_job_destroys_callable_root_before_refund(self):
        self.control('job-error-ack-after-delete')

    def test_cancelled_job_destroys_callable_root_before_refund(self):
        self.control('job-cancel-ack-after-delete')

    def test_completed_job_retains_partial_ack_without_replaying_frame(self):
        self.control('job-partial-ack-retains-owner')

    def test_cancelled_job_retains_partial_ack_without_replaying_callback(self):
        self.control('job-cancel-partial-ack-retains-owner')


class TimerSetupRetirementTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        compiler = os.environ.get('LSF_TYPESCRIPT_RECORD_CXX') or shutil.which('c++')
        if compiler is None:
            if os.name == 'nt':
                raise unittest.SkipTest('Set LSF_TYPESCRIPT_RECORD_CXX for the finite C++ reference')
            raise RuntimeError('C++ compiler is required for timer setup controls')
        cls.temporary = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temporary.cleanup)
        output = Path(cls.temporary.name)
        cls.binary = output / ('timer-setup.exe' if os.name == 'nt' else 'timer-setup')
        fixture = ROOT/'tools/tests/fixtures/typescript_record_retirement'
        source = ROOT/'sdk/typescript-guest/activation/tests/timer_setup.cpp'
        if Path(compiler).stem.lower() == 'cl':
            args = [compiler, '/nologo', '/std:c++17', '/EHsc', '/W4', '/WX',
                    '/I' + str(fixture), str(source), '/Fe:' + str(cls.binary),
                    '/Fo:' + str(output/'timer-setup.obj')]
        else:
            args = [compiler, '-std=c++17', '-O0', '-Wall', '-Wextra', '-Werror',
                    '-I', str(fixture), str(source), '-o', str(cls.binary)]
        result = subprocess.run(args, capture_output=True, timeout=60)
        if result.returncode or len(result.stdout) + len(result.stderr) > 65536:
            raise AssertionError(result.stderr[:65536].decode(errors='replace'))
        if not cls.binary.is_file() or cls.binary.stat().st_size > 4*1024**2:
            raise AssertionError('finite timer setup reference output required')

    def control(self, case):
        result = subprocess.run([str(self.binary), case], capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0, (result.stdout + result.stderr)[:65536])
        self.assertLessEqual(len(result.stdout) + len(result.stderr), 65536)
        self.assertEqual(json.loads(result.stdout),
                         {'case': case, 'passed': True, 'engineQualified': False})

    def test_failed_stop_retains_timer_and_closes_new_admission(self):
        self.control('refused-stop')

    def test_successful_cleanup_allows_new_timer(self):
        self.control('successful-cleanup')

    def test_failed_native_settlement_retains_owner_and_closes_admission(self):
        self.control('refused-native-settlement')

    def test_ready_fairness_shared_events_checkpoint_and_retirement(self):
        compiler = os.environ.get('LSF_TYPESCRIPT_RECORD_CXX') or shutil.which('c++')
        if compiler is None:
            raise RuntimeError('compiler selection changed after timer setup')
        output = Path(self.temporary.name)
        binary = output / ('timer-fairness.exe' if os.name == 'nt' else 'timer-fairness')
        fixture = ROOT/'tools/tests/fixtures/typescript_record_retirement'
        source = ROOT/'sdk/typescript-guest/activation/tests/timer_fairness.cpp'
        engine = (ROOT/'sdk/typescript-guest/activation/native_engine.cpp').read_text(encoding='utf-8')
        begin = 'bool run_timer_turn(JSContext* cx) {'
        end = '\n}\n\nbool begin_root'
        if engine.count(begin) != 1 or engine.count(end) != 1:
            raise AssertionError('exact selected native pump source required')
        start = engine.index(begin)
        finish = engine.index(end, start) + 2
        (output/'run_timer_turn.inc').write_text(engine[start:finish]+'\n', encoding='utf-8')
        if Path(compiler).stem.lower() == 'cl':
            args = [compiler, '/nologo', '/std:c++17', '/EHsc', '/W4', '/WX',
                    '/I'+str(ROOT), '/I'+str(output), '/I'+str(fixture), str(source),
                    '/Fe:'+str(binary), '/Fo:'+str(output/'timer-fairness.obj')]
        else:
            args = [compiler, '-std=c++17', '-O0', '-Wall', '-Wextra', '-Werror',
                    '-I', str(ROOT), '-I', str(output), '-I', str(fixture), str(source),
                    '-o', str(binary)]
        compiled = subprocess.run(args, capture_output=True, timeout=60)
        if compiled.returncode or len(compiled.stdout) + len(compiled.stderr) > 65536:
            raise AssertionError(compiled.stderr[:65536].decode(errors='replace'))
        if not binary.is_file() or binary.stat().st_size > 4*1024**2:
            raise AssertionError('finite timer fairness reference output required')
        for case in ('immediate', 'delivered', 'queued', 'noevent', 'selfclear',
                     'otherclear', 'import-ready', 'import-queued', 'cancelled',
                     'two-import-ready', 'two-import-nojob'):
            with self.subTest(case=case):
                result = subprocess.run([str(binary), case], capture_output=True, timeout=10)
                self.assertEqual(result.returncode, 0, (result.stdout + result.stderr)[:65536])
                self.assertLessEqual(len(result.stdout) + len(result.stderr), 65536)
                observed = json.loads(result.stdout)
                self.assertEqual(observed['case'], case)
                self.assertIs(observed['passed'], True)
                self.assertIs(observed['clean'], True)


class SubtaskStartUncertaintyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        compiler = os.environ.get('LSF_TYPESCRIPT_RECORD_CXX') or shutil.which('c++')
        if compiler is None:
            # Reuse the established Windows skip / other-platform failure path.
            TimerSetupRetirementTests.setUpClass.__func__(cls)
            raise RuntimeError('compiler selection changed during setup')
        cls.temporary = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temporary.cleanup)
        output = Path(cls.temporary.name)
        cls.binary = output / ('subtask-start.exe' if os.name == 'nt' else 'subtask-start')
        fixture = ROOT/'tools/tests/fixtures/typescript_record_retirement'
        source = ROOT/'sdk/typescript-guest/activation/tests/subtask_start.cpp'
        if Path(compiler).stem.lower() == 'cl':
            args = [compiler, '/nologo', '/std:c++17', '/EHsc', '/W4', '/WX',
                    '/I' + str(fixture), str(source), '/Fe:' + str(cls.binary),
                    '/Fo:' + str(output/'subtask-start.obj')]
        else:
            args = [compiler, '-std=c++17', '-O0', '-Wall', '-Wextra', '-Werror',
                    '-I', str(fixture), str(source), '-o', str(cls.binary)]
        result = subprocess.run(args, capture_output=True, timeout=60)
        if result.returncode or len(result.stdout) + len(result.stderr) > 65536:
            raise AssertionError(result.stderr[:65536].decode(errors='replace'))
        if not cls.binary.is_file() or cls.binary.stat().st_size > 4*1024**2:
            raise AssertionError('finite subtask-start reference output required')

    def control(self, case):
        result = subprocess.run([str(self.binary), case], capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0, (result.stdout + result.stderr)[:65536])
        self.assertLessEqual(len(result.stdout) + len(result.stderr), 65536)
        self.assertEqual(json.loads(result.stdout),
                         {'case': case, 'passed': True, 'engineQualified': False})

    def test_unknown_start_state_remains_unresolved_without_a_guessed_intrinsic(self):
        for owner in ('subtask', 'import', 'timer'):
            for suffix in ('unknown', 'unknownzero'):
                with self.subTest(owner=owner, status=suffix):
                    self.control(owner+'-'+suffix)

    def test_nonterminal_start_without_handle_remains_unresolved(self):
        for owner in ('subtask', 'import', 'timer'):
            for suffix in ('zero', 'zero-starting'):
                with self.subTest(owner=owner, status=suffix):
                    self.control(owner+'-'+suffix)

    def test_valid_immediate_timer_still_retires_its_original_owner(self):
        self.control('valid-immediate')


if __name__ == '__main__':
    unittest.main()
