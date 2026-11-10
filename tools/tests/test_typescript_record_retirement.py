"""Compile the actual owner classes; JS doubles establish no engine semantics."""
import hashlib
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

    def test_captured_callback_stays_charged_until_weak_collection_and_ack(self):
        self.control('captured-native-retention')

    def test_captured_callback_denial_precedes_tracking_allocation(self):
        self.control('captured-native-denial')

    def test_live_snapshot_capture_is_fenced_after_collection(self):
        self.control('snapshot-captured-retained')

    def test_unreachable_snapshot_capture_retires_without_host_ack(self):
        self.control('snapshot-captured-collected')

    def test_snapshot_live_native_owner_fails_before_ack_and_preserves_exception(self):
        self.control('snapshot-live-native-owner-denied')

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


class CombinatorFunctionDerivationTests(unittest.TestCase):
    """Compile the pinned function before/after the real source transformation.

    Native/JS functions are finite doubles; these controls do not execute an
    actual SpiderMonkey collector or a signed component.
    """
    @classmethod
    def setUpClass(cls):
        from tools.typescript_guest.promise_engine import instrument_combinator_element_function
        compiler = os.environ.get('LSF_TYPESCRIPT_RECORD_CXX') or shutil.which('c++')
        if compiler is None:
            raise RuntimeError('C++ compiler is required for combinator ownership controls')
        cls.temporary = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temporary.cleanup)
        output = Path(cls.temporary.name)
        fixture = ROOT/'tools/tests/fixtures/typescript_record_retirement'
        original = (fixture/'combinator_input.cpp.txt').read_bytes()
        attribution = b'// Pinned Firefox 9dab3d6f643e926a340c391ea30968e940390dec, MPL-2.0.\n'
        if (not original.startswith(attribution) or
                hashlib.sha256(original[len(attribution):]).hexdigest() !=
                '0808a6d564f97bf4c740ba131e3178c450491acf976e5889424a85f6472d4195'):
            raise AssertionError('pinned original combinator function required')
        derived = instrument_combinator_element_function(original)
        harness = (fixture/'combinator_harness.cpp.txt').read_bytes()
        marker = b'/* LSF_COMBINATOR_TARGET */\n'
        if harness.count(marker) != 1 or derived == original:
            raise AssertionError('exact old/new combinator controls required')
        cls.binaries = {}
        for label, body in (('old', original), ('new', derived)):
            source = output/(label+'.cpp')
            source.write_bytes(harness.replace(marker, body))
            binary = output/(label+'.exe' if os.name == 'nt' else label)
            if Path(compiler).stem.lower() == 'cl':
                args = [compiler, '/nologo', '/std:c++17', '/EHsc', '/W4', '/WX',
                        str(source), '/Fe:' + str(binary), '/Fo:' + str(output/(label+'.obj'))]
            else:
                args = [compiler, '-std=c++17', '-O0', '-Wall', '-Wextra', '-Werror',
                        str(source), '-o', str(binary)]
            result = subprocess.run(args, capture_output=True, timeout=60)
            if result.returncode or len(result.stdout) + len(result.stderr) > 65536:
                raise AssertionError(result.stderr[:65536].decode(errors='replace'))
            if not binary.is_file() or binary.stat().st_size > 4*1024**2:
                raise AssertionError('finite combinator reference output required')
            cls.binaries[label] = binary

    def control(self, label, case, expected):
        result = subprocess.run([str(self.binaries[label]), case], capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0 if expected else 1,
                         (result.stdout + result.stderr)[:65536])
        self.assertLessEqual(len(result.stdout) + len(result.stderr), 65536)
        value = json.loads(result.stdout)
        self.assertEqual(value['case'], case)
        self.assertIs(value['passed'], expected)
        self.assertIs(value['engineQualified'], False)
        return value

    def test_old_allows_unowned_closure_new_refuses_before_allocation(self):
        old = self.control('old', 'selected-limit', False)
        new = self.control('new', 'selected-limit', True)
        self.assertEqual((old['admitted'], old['allocations']), (0, 3))
        self.assertEqual((new['admitted'], new['allocations']), (2, 2))

    def test_failed_native_allocation_retains_its_accepted_owner(self):
        self.control('old', 'allocation-failure', False)
        self.control('new', 'allocation-failure', True)

    def test_second_paired_callback_denied_before_allocation_keeps_first(self):
        old = self.control('old', 'paired-refusal', False)
        new = self.control('new', 'paired-refusal', True)
        self.assertEqual((old['admitted'], old['allocations']), (0, 2))
        self.assertEqual((new['admitted'], new['allocations']), (1, 1))

    def test_snapshot_capture_fence_follows_original_full_gc(self):
        from tools.typescript_guest.activation_engine import fence_snapshot_captures
        original = b'    JS::NonIncrementalGC(cx(), JS::GCOptions::Normal, JS::GCReason::API);\n  }\n'
        derived = fence_snapshot_captures(original)
        self.assertTrue(derived.startswith(original.splitlines(keepends=True)[0]))
        self.assertLess(derived.index(b'NonIncrementalGC'),
                        derived.index(b'snapshot_captured_functions_empty'))
        self.assertTrue(derived.endswith(b'  }\n'))
        with self.assertRaises(ValueError):
            fence_snapshot_captures(original + original)

    def test_original_path_and_paired_slot_semantics_are_preserved(self):
        self.control('old', 'unselected-original', True)
        self.control('new', 'unselected-original', True)
        self.control('new', 'paired-slots', True)


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


OWNER_RETRY_CASES = (
    'timer-cancel-retry', 'timer-clear-retry',
    'timer-capture-before-host', 'timer-capture-refused-retirement',
    'timer-late-return', 'timer-nested-clear', 'timer-native-limit',
    'import-result-retry', 'import-lowering-retry', 'import-record-retry',
    'import-turn-fence', 'import-lower-fence', 'import-lift-fence',
    'import-partial-admission', 'import-partial-buffer',
    'import-disposer-quarantine', 'lazy-synchronous', 'repeated-generations',
    'native-live-slot', 'snapshot-live-slot', 'accepted-after-root',
    'timer-false-return', 'timer-exception',
)


def write_owner_retry_includes(directory: Path) -> None:
    """Opaque API declarations only; production headers/bodies are not rewritten."""
    (directory / 'js').mkdir(parents=True)
    shutil.copyfile(ROOT / 'tools/tests/fixtures/typescript_record_retirement/owner_retry.h', directory / 'jsapi.h')
    for name in ('Array', 'BigInt', 'CallAndConstruct', 'Class', 'Conversions',
                 'GCAPI', 'Object', 'Promise', 'Realm', 'RootingAPI', 'TypeDecls', 'ValueArray'):
        (directory / 'js' / (name + '.h')).write_text('#pragma once\n#include "../jsapi.h"\n')
    original = ROOT / 'tools/tests/fixtures/typescript_record_retirement/jobs.h'
    (directory / 'jobs.h').write_text(
        '#pragma once\n#include "' + original.as_posix() + '"\n'
        'enum : uint8_t { LATENT_RUNTIME_ACTIVATION_OWNER_KIND_RESULT=6, '
        'LATENT_RUNTIME_ACTIVATION_OWNER_KIND_NATIVE=7 };\n')


class OwnerRetryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        compiler = (os.environ.get('LSF_TYPESCRIPT_RECORD_CXX') or
                    shutil.which('c++') or shutil.which('cl'))
        if compiler is None:
            raise RuntimeError('C++ compiler is required for native owner retry controls')
        cls.temporary = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temporary.cleanup)
        output = Path(cls.temporary.name)
        includes = output / 'include'
        write_owner_retry_includes(includes)
        cls.binary = output / ('owners.exe' if os.name == 'nt' else 'owners')
        source = ROOT / 'sdk/typescript-guest/activation/tests/owner_retry.cpp'
        if Path(compiler).stem.lower() == 'cl':
            command = [compiler, '/nologo', '/std:c++17', '/EHsc', '/W4', '/WX',
                       '/I' + str(includes), str(source), '/Fe:' + str(cls.binary),
                       '/Fo:' + str(output / 'owners.obj')]
        else:
            command = [compiler, '-std=c++17', '-O0', '-Wall', '-Wextra', '-Werror',
                       '-I', str(includes), str(source), '-o', str(cls.binary)]
        result = subprocess.run(command, capture_output=True, timeout=60, check=False)
        if result.returncode or len(result.stdout) + len(result.stderr) > 65536:
            raise AssertionError((result.stdout + result.stderr)[:65536].decode(errors='replace'))
        if not cls.binary.is_file() or cls.binary.stat().st_size > 4 * 1024**2:
            raise AssertionError('finite native reference output required')

    def test_original_owners_survive_refusal_and_fence_dispatch(self):
        for case in OWNER_RETRY_CASES:
            with self.subTest(case=case):
                result = subprocess.run([str(self.binary), case], capture_output=True,
                                        timeout=10, check=False)
                self.assertEqual(result.returncode, 0, (result.stdout + result.stderr)[:65536])
                self.assertLessEqual(len(result.stdout) + len(result.stderr), 65536)
                row = json.loads(result.stdout)
                self.assertEqual(row['case'], case)
                self.assertIs(row['passed'], True)
                self.assertIs(row['engineQualified'], False)
                # Refused non-retryable disposal is retention, never successful
                # cleanup. Every other scenario proves all original ACKs once.
                if case == 'import-disposer-quarantine':
                    self.assertGreater(row['retainedOwners'], 0)
                else:
                    self.assertEqual(row['retainedOwners'], 0)
                if case == 'lazy-synchronous':
                    self.assertEqual(row['peakNativeOwners'], 0)
                    self.assertEqual(row['peakLoweringBufferBytes'], 0)
                    self.assertEqual(row['callbacks'], 0)


class QueueCancellationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        compiler = (os.environ.get('LSF_TYPESCRIPT_RECORD_CXX') or
                    shutil.which('c++') or shutil.which('cl'))
        if compiler is None:
            raise RuntimeError('C++ compiler is required for queue cancellation controls')
        cls.temporary = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temporary.cleanup)
        output = Path(cls.temporary.name)
        includes = output / 'include'
        write_owner_retry_includes(includes)
        cls.binary = output / ('queue.exe' if os.name == 'nt' else 'queue')
        source = ROOT / 'sdk/typescript-guest/activation/tests/queue_cancellation.cpp'
        if Path(compiler).stem.lower() == 'cl':
            command = [compiler, '/nologo', '/std:c++17', '/EHsc', '/W4', '/WX',
                       '/I' + str(includes), str(source), '/Fe:' + str(cls.binary),
                       '/Fo:' + str(output / 'queue.obj')]
        else:
            command = [compiler, '-std=c++17', '-O0', '-Wall', '-Wextra', '-Werror',
                       '-I', str(includes), str(source), '-o', str(cls.binary)]
        result = subprocess.run(command, capture_output=True, timeout=60, check=False)
        if result.returncode or len(result.stdout) + len(result.stderr) > 65536:
            raise AssertionError((result.stdout + result.stderr)[:65536].decode(errors='replace'))
        if not cls.binary.is_file() or cls.binary.stat().st_size > 4 * 1024**2:
            raise AssertionError('finite queue reference output required')

    def test_cancel_fences_admission_without_destroying_an_executing_frame(self):
        for suffix in ('success', 'false', 'exception', 'ack-refusal'):
            case = 'reentrant-cancel-' + suffix
            with self.subTest(case=case):
                result = subprocess.run([str(self.binary), case], capture_output=True,
                                        timeout=10, check=False)
                self.assertEqual(result.returncode, 0, (result.stdout + result.stderr)[:65536])
                self.assertLessEqual(len(result.stdout) + len(result.stderr), 65536)
                row = json.loads(result.stdout)
                self.assertEqual(row, {'case': case, 'passed': True, 'engineQualified': False,
                                       'callbacks': 1, 'retainedRoots': 0, 'retiredTasks': 2})


if __name__ == '__main__':
    unittest.main()
