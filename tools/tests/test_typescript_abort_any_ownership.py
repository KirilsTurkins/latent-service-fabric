"""AbortSignal.any source and finite-owner controls, not engine qualification."""
from pathlib import Path
import importlib.util
import json
import os
import shutil
import subprocess
import tempfile
import unittest

from tools.typescript_guest import abort_engine

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = Path(__file__).parent/'fixtures/typescript_runtime_profile'
HISTORICAL = (Path(__file__).parent/'fixtures/typescript_clock_profile'/
              'original-sdk-e611'/'abort_engine.py')


def any_function(source):
    start = source.index(b'bool AbortSignal::any(')
    return source[start:source.index(b'\n}', start)+2]


def selected_and_previous():
    raw = (FIXTURES/'original-abort-signal.cpp').read_bytes()
    selected, receipt = abort_engine.derive_abort_timeout(raw)
    spec = importlib.util.spec_from_file_location('historical_typescript_abort_engine', HISTORICAL)
    historical = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(historical)
    previous, _ = historical.derive_abort_timeout(raw)
    return any_function(selected), any_function(previous), receipt


class AbortAnySourceTests(unittest.TestCase):
    def test_only_new_frame_admission_changes_the_previous_any_conversion(self):
        selected, previous, receipt = selected_and_previous()
        declaration = (b'  // The vector must be destroyed before its frame\'s original native owner.\n'
                       b'  lsf::typescript::activation::NativeObjectFrameLease signals_owner;\n')
        owned = b'  bool signals_owned = false;\n'
        admission = (b'    if (!signals_owned && signals.length() == signals.capacity()) {\n'
                     b'      if (!lsf::typescript::activation::admit_native_object(cx, signals_owner.lease())) {\n'
                     b'        iterator.closeThrow();\n'
                     b'        return false;\n'
                     b'      }\n'
                     b'      signals_owned = true;\n'
                     b'    }\n')
        self.assertLess(selected.index(declaration), selected.index(b'  JS::RootedValueVector signals(cx);'))
        self.assertLess(selected.index(admission), selected.index(b'    if (!signals.append(value))'))
        fixed = b'    if (!signals.append(value)) { JS_ReportOutOfMemory(cx); iterator.closeThrow(); return false; }\n'
        original = b'    if (!signals.append(value)) { JS_ReportOutOfMemory(cx); return false; }\n'
        self.assertEqual(selected.count(fixed), 1)
        selected = selected.replace(fixed, original, 1)
        for change in (declaration, owned, admission):
            self.assertEqual(selected.count(change), 1)
            selected = selected.replace(change, b'', 1)
        self.assertEqual(selected, previous)
        self.assertEqual(receipt['anyHeapVectorOwner'], 'one-original-native-count-per-frame-not-byte-accurate')
        self.assertEqual(receipt['anyAllocationFailure'], 'close-iterator-preserving-original-exception')
        self.assertFalse(receipt['signedLSFComponentQualified'])


class AbortAnyOwnershipControls(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        compiler = os.environ.get('LSF_TYPESCRIPT_RECORD_CXX') or shutil.which('c++') or shutil.which('cl')
        if not compiler:
            raise RuntimeError('C++ compiler is required for abort-any ownership controls')
        cls.temporary = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temporary.cleanup)
        output = Path(cls.temporary.name)
        template = (ROOT/'tools/tests/fixtures/typescript_abort_any_ownership.cpp').read_bytes()
        marker = b'// INSERT_EMITTED_ABORT_ANY'
        if template.count(marker) != 1:
            raise AssertionError('unique emitted abort-any insertion point required')
        selected, previous, _ = selected_and_previous()
        fixed = b'if (!signals.append(value)) { JS_ReportOutOfMemory(cx); iterator.closeThrow(); return false; }'
        original = b'if (!signals.append(value)) { JS_ReportOutOfMemory(cx); return false; }'
        if selected.count(fixed) != 1:
            raise AssertionError('unique selected allocation-failure close required')
        pre_fix = selected.replace(fixed, original, 1)
        for label, function in (('selected', selected), ('previous', previous), ('pre_fix', pre_fix)):
            source = output/(label+'.cpp')
            source.write_bytes(template.replace(marker, function, 1))
            binary = output/(label+'.exe' if os.name == 'nt' else label)
            include = str(ROOT/'sdk/typescript-guest/activation')
            if Path(compiler).stem.lower() == 'cl':
                args = [compiler, '/nologo', '/std:c++17', '/EHsc', '/W4', '/WX', '/I'+include,
                        str(source), '/Fe:'+str(binary), '/Fo:'+str(output/(label+'.obj'))]
            else:
                args = [compiler, '-std=c++17', '-Wall', '-Wextra', '-Werror', '-I'+include,
                        str(source), '-o', str(binary)]
            result = subprocess.run(args, capture_output=True, timeout=60)
            if result.returncode or len(result.stdout) + len(result.stderr) > 65536:
                raise AssertionError((result.stdout + result.stderr)[:65536].decode(errors='replace'))
            setattr(cls, label+'_binary', binary)

    def check_case(self, binary, case, passed):
        result = subprocess.run([str(binary), case], capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0 if passed else 1, (result.stdout + result.stderr)[:65536])
        self.assertEqual(json.loads(result.stdout),
                         {'case': case, 'passed': passed, 'engineQualified': False})

    def test_owned_conversion_closes_and_retains_each_frame(self):
        for case in ('inline', 'heap', 'growth', 'refusal', 'uncatchable', 'invalid', 'invalid-grown',
                     'nested', 'nested-refusal', 'return-reentry', 'allocation-failure-first',
                     'allocation-failure', 'allocation-failure-return', 'repeated', 'gc-object'):
            with self.subTest(case=case):
                self.check_case(self.selected_binary, case, True)

    def test_previous_conversion_reproduces_unowned_heap_and_refusal(self):
        for case in ('heap', 'growth', 'refusal', 'nested-refusal'):
            with self.subTest(case=case):
                self.check_case(self.previous_binary, case, False)
        for case in ('inline', 'invalid'):
            with self.subTest(case=case):
                self.check_case(self.previous_binary, case, True)

    def test_previous_selected_conversion_leaves_iterator_open_on_allocation_failure(self):
        for case in ('allocation-failure-first', 'allocation-failure', 'allocation-failure-return'):
            with self.subTest(case=case):
                self.check_case(self.pre_fix_binary, case, False)


if __name__ == '__main__':
    unittest.main()
