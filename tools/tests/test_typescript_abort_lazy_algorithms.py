"""Independent lazy AbortSignal allocation/lifetime controls, not signed evidence."""
from pathlib import Path
import json
import os
import shutil
import subprocess
import tempfile
import unittest

from tools.tests.test_typescript_event_ownership import derive

ROOT = Path(__file__).resolve().parents[2]
NATIVE = ROOT / 'sdk/typescript-guest/activation'


def emitted_functions():
    selected, _ = derive()
    source = selected['StarlingMonkey/builtins/web/abort/abort-signal.cpp']
    functions = []
    for start, end in (
        (b'AbortSignal::AlgorithmList *AbortSignal::algorithms(', b'WeakIndexSet *AbortSignal::source_signals('),
        (b'bool AbortSignal::add_algorithm(', b'bool AbortSignal::is_dependent('),
        (b'JSObject *AbortSignal::create(', b'// https://dom.spec.whatwg.org/#dom-abortsignal-abort'),
        (b'void AbortSignal::finalize(', b'void AbortSignal::trace('),
    ):
        first = source.index(start)
        functions.append(source[first:source.index(end, first)])
    return b'\n'.join(functions)


class LazyAlgorithmSourceTests(unittest.TestCase):
    def test_every_native_caller_uses_the_rooted_lazy_admission_boundary(self):
        selected, receipt = derive()
        self.assertEqual(receipt['abortAlgorithmStorage'],
                         'lazy-independent-owner-before-first-publication')
        for path in ('StarlingMonkey/builtins/web/event/event-target.cpp',
                     'StarlingMonkey/builtins/web/fetch/fetch-api.cpp',
                     'StarlingMonkey/builtins/web/fetch/request-response.cpp'):
            with self.subTest(path=path):
                source = selected[path]
                self.assertIn(b'AbortSignal::add_algorithm(cx, signal,', source)
                self.assertNotIn(b'AbortSignal::add_algorithm(signal,', source)
        source = selected['StarlingMonkey/builtins/web/abort/abort-signal.cpp']
        begin = source.index(b'bool AbortSignal::add_algorithm(')
        end = source.index(b'bool AbortSignal::is_dependent(', begin)
        body = source[begin:end]
        self.assertIn(b'JSContext *cx, HandleObject self', body)
        self.assertIn(b'if (JS_IsExceptionPending(cx)) return false;', body)
        self.assertLess(body.index(b'make_native_container<AlgorithmList>(cx)'),
                        body.index(b'staged->value.append'))
        self.assertLess(body.index(b'staged->value.append'), body.index(b'staged.release()'))
        self.assertNotIn(b'prepare_native_object_allocation', body)
        self.assertNotIn(b'NonIncrementalGC', body)
        self.assertIn(b'algorithms && next < algorithms->length()', source)
        self.assertIn(b'if (!JS_IsExceptionPending(cx)) JS_ReportOutOfMemory(cx);',
                      selected['StarlingMonkey/builtins/web/event/event-target.cpp'])


class LazyAlgorithmLifetimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        compiler = os.environ.get('LSF_TYPESCRIPT_RECORD_CXX') or shutil.which('c++') or shutil.which('cl')
        if not compiler:
            raise RuntimeError('C++ compiler required for lazy algorithm lifetime controls')
        cls.temporary = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temporary.cleanup)
        output = Path(cls.temporary.name)
        template = (ROOT / 'tools/tests/fixtures/typescript_abort_lazy_algorithms.cpp').read_bytes()
        header = (NATIVE / 'native_objects.h').read_bytes()
        begin = header.index(b'template<class T> using NativeContainer')
        factory = header[begin:header.index(b'} // namespace', begin)]
        functions = emitted_functions()
        # Reintroduce the eager physical allocation, not a fictitious counter.
        anchor = b'  SetReservedSlot(self, std::to_underlying(Slots::Algorithms), JS::UndefinedValue());'
        if functions.count(anchor) != 1:
            raise AssertionError('unique empty algorithm publication required')
        eager = functions.replace(anchor,
            b'  auto eager = lsf::typescript::activation::make_native_container<AlgorithmList>(cx);\n'
            b'  if (!eager) return nullptr;\n'
            b'  SetReservedSlot(self, std::to_underlying(Slots::Algorithms), JS::PrivateValue(eager.release()));', 1)
        cls.binaries = {}
        for label, body in (('selected', functions), ('eager', eager)):
            raw = template
            for marker, replacement in ((b'// INSERT_NATIVE_CONTAINER_FACTORY', factory),
                                        (b'// INSERT_EMITTED_FUNCTIONS', body)):
                if raw.count(marker) != 1:
                    raise AssertionError('unique emitted source insertion point required')
                raw = raw.replace(marker, replacement, 1)
            path = output / (label + '.cpp')
            path.write_bytes(raw)
            binary = output / (label + ('.exe' if os.name == 'nt' else ''))
            if Path(compiler).stem.lower() == 'cl':
                command = [compiler, '/nologo', '/std:c++latest', '/EHsc', '/W4', '/WX',
                           '/I' + str(NATIVE), str(path), '/Fe:' + str(binary),
                           '/Fo:' + str(output / (label + '.obj'))]
            else:
                command = [compiler, '-std=c++23', '-Wall', '-Wextra', '-Werror',
                           '-I' + str(NATIVE), str(path), '-o', str(binary)]
            result = subprocess.run(command, capture_output=True, timeout=60)
            if result.returncode or len(result.stdout) + len(result.stderr) > 65536:
                raise AssertionError((result.stdout + result.stderr)[:65536].decode(errors='replace'))
            cls.binaries[label] = binary

    def check(self, label, case, passed):
        result = subprocess.run([str(self.binaries[label]), case], capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0 if passed else 1,
                         (result.stdout + result.stderr)[:65536])
        self.assertEqual(json.loads(result.stdout),
                         {'case': case, 'passed': passed, 'engineQualified': False})

    def test_independent_owners_survive_until_backing_destruction_collection_end_and_ack(self):
        for case in ('empty-signal', 'first-and-second-algorithm', 'quota-refusal',
                     'allocation-refusal', 'first-append-refusal', 'existing-append-refusal',
                     'pending-exception', 'already-aborted', 'partial-signal',
                     'failed-ack-retains-owner', 'ten-signal-recovery-capacity'):
            with self.subTest(case=case):
                self.check('selected', case, True)

    def test_eager_allocation_reproduces_exhausted_recovery_capacity(self):
        for case in ('empty-signal', 'ten-signal-recovery-capacity'):
            with self.subTest(case=case):
                self.check('eager', case, False)


if __name__ == '__main__':
    unittest.main()
