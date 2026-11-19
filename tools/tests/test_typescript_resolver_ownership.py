"""Pinned resolver derivation and original owner classes, with finite host doubles."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from tools.typescript_guest.promise_engine import instrument_resolving_functions


ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT/'tools/tests/fixtures/typescript_resolver_ownership'
ATTRIBUTION = b'// Pinned Firefox 9dab3d6f643e926a340c391ea30968e940390dec, MPL-2.0.\n'


def selected_compiler():
    return (os.environ.get('LSF_TYPESCRIPT_RESOLVER_CXX') or
            os.environ.get('LSF_TYPESCRIPT_RECORD_CXX') or shutil.which('c++'))


class ResolverCompilerSelectionTests(unittest.TestCase):
    def test_explicit_compiler_then_existing_matrix_selector_then_default(self):
        wrapper = './tools/typescript_runtime_sanitizer_cxx.sh'
        with patch.dict(os.environ, {'LSF_TYPESCRIPT_RECORD_CXX': wrapper}, clear=True), \
                patch('shutil.which', return_value='default-cxx'):
            self.assertEqual(selected_compiler(), wrapper)
            with patch.dict(os.environ, {'LSF_TYPESCRIPT_RESOLVER_CXX': 'explicit-cxx'}):
                self.assertEqual(selected_compiler(), 'explicit-cxx')
            with patch.dict(os.environ, {'LSF_TYPESCRIPT_RECORD_CXX': ''}):
                self.assertEqual(selected_compiler(), 'default-cxx')


class ResolverOwnershipTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        compiler = selected_compiler()
        if compiler is None:
            raise RuntimeError('C++ compiler is required for resolver ownership controls')
        cls.temporary = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temporary.cleanup)
        output = Path(cls.temporary.name)
        create = (FIXTURE/'create.cpp.txt').read_bytes()
        settle = (FIXTURE/'settle.cpp.txt').read_bytes()
        for source, digest in ((create, 'f2d9759bdfa6b7ec818d2b5b93b582f52326abcf939c39af91e1a7be78784c91'),
                               (settle, '36f030c57d587762a377c9775fe70a557b521cebd35c04342d0988d3ae3efe47')):
            if not source.startswith(ATTRIBUTION) or hashlib.sha256(source[len(ATTRIBUTION):]).hexdigest() != digest:
                raise AssertionError('exact pinned Firefox function required')
        derived = instrument_resolving_functions(create)
        harness = (FIXTURE/'derivation_harness.cpp.txt').read_bytes()
        if harness.count(b'/* LSF_SETTLE_TARGET */') != 1 or harness.count(b'/* LSF_CREATE_TARGET */') != 1:
            raise AssertionError('exact pinned fixture markers required')
        cls.binaries = {}
        for label, body in (('old', create), ('new', derived)):
            source = output/(label+'.cpp')
            source.write_bytes(harness.replace(b'/* LSF_SETTLE_TARGET */', settle)
                .replace(b'/* LSF_CREATE_TARGET */', body))
            cls.binaries[label] = cls.compile(compiler, source, output/label)
        cls.binaries['records'] = cls.compile(compiler, FIXTURE/'record_harness.cpp', output/'records',
            (ROOT/'tools/tests/fixtures/typescript_record_retirement', ROOT/'sdk/typescript-guest/activation'))

    @staticmethod
    def compile(compiler, source, output, includes=()):
        binary = output.with_suffix('.exe') if os.name == 'nt' else output
        if Path(compiler).stem.lower() == 'cl':
            args = [compiler, '/nologo', '/std:c++17', '/EHsc', '/W4', '/WX']
            args += ['/I'+str(path) for path in includes]
            args += [str(source), '/Fe:'+str(binary), '/Fo:'+str(output)+'.obj']
        else:
            args = [compiler, '-std=c++17', '-O0', '-Wall', '-Wextra', '-Werror']
            for path in includes:
                args += ['-I', str(path)]
            args += [str(source), '-o', str(binary)]
        result = subprocess.run(args, capture_output=True, timeout=60)
        if result.returncode or len(result.stdout) + len(result.stderr) > 65536:
            raise AssertionError((result.stdout + result.stderr)[:65536].decode(errors='replace'))
        if not binary.is_file() or binary.stat().st_size > 4*1024**2:
            raise AssertionError('finite resolver reference output required')
        return binary

    def run_control(self, binary, case):
        result = subprocess.run([str(self.binaries[binary]), case], capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0, (result.stdout + result.stderr)[:65536])
        value = json.loads(result.stdout)
        self.assertEqual(value['case'], case)
        self.assertIs(value['engineQualified'], False)
        return value

    def test_original_unowned_resolvers_gain_two_independent_admissions(self):
        old = self.run_control('old', 'normal')
        new = self.run_control('new', 'normal')
        self.assertTrue(old['result'] and old['slotsCleared'] and new['result'] and new['slotsCleared'])
        self.assertEqual((old['allocations'], old['admitted'], old['created']), (2, 0, 0))
        self.assertEqual((new['allocations'], new['admitted'], new['created']), (2, 2, 2))

    def test_second_resolver_refusal_preserves_first_allocation(self):
        old = self.run_control('old', 'capacity')
        new = self.run_control('new', 'capacity')
        self.assertTrue(old['result'])
        self.assertFalse(new['result'])
        self.assertTrue(new['exception'] and new['resolvePresent'] and not new['rejectPresent'])
        self.assertEqual((new['allocations'], new['attempts'], new['admitted'], new['created']), (1, 1, 1, 1))

    def test_allocation_failure_keeps_each_accepted_record_for_retirement(self):
        first = self.run_control('new', 'first-oom')
        second = self.run_control('new', 'second-oom')
        self.assertEqual((first['result'], first['admitted'], first['created'], first['failed']), (False, 1, 0, 1))
        self.assertEqual((second['result'], second['admitted'], second['created'], second['failed']), (False, 2, 1, 1))
        self.assertTrue(second['resolvePresent'] and not second['rejectPresent'])

    def test_unselected_engine_retains_original_construction(self):
        for label in ('old', 'new'):
            row = self.run_control(label, 'unselected')
            self.assertTrue(row['result'] and row['slotsCleared'])
            self.assertEqual((row['allocations'], row['admitted'], row['created']), (2, 0, 0))

    def test_pending_native_admission_survives_a_checkpoint(self):
        row = self.run_control('records', 'probe-before-created')
        self.assertEqual((row['live'], row['settled'], row['pending']), (1, 0, True))

    def test_original_owners_survive_creation_reentry_and_independent_collection(self):
        for case in ('creation-reentry', 'gc-during-creation', 'partial-pair-allocation', 'partial-pair-admission',
                     'reaction-creation-reentry', 'snapshot-creation-fence'):
            with self.subTest(case=case):
                self.assertTrue(self.run_control('records', case)['passed'])

    def test_source_shape_drift_fails_closed(self):
        original = (FIXTURE/'create.cpp.txt').read_bytes()
        with self.assertRaises(ValueError):
            instrument_resolving_functions(original.replace(b'NewNativeFunction(cx, RejectPromiseFunction',
                                                            b'NewNativeFunction(cx, ChangedPromiseFunction'))


if __name__ == '__main__':
    unittest.main()
