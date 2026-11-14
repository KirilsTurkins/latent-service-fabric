"""Execute pinned native exception bodies with JSAPI fault doubles, not a collector."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from tools.tests.test_typescript_event_ownership import derive, originals

ROOT = Path(__file__).resolve().parents[2]
PATH = 'StarlingMonkey/builtins/web/dom-exception.cpp'


class DOMExceptionFailureControls(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        compiler = os.environ.get('LSF_TYPESCRIPT_RECORD_CXX') or shutil.which('c++') or shutil.which('cl')
        if not compiler:
            raise RuntimeError('C++ compiler required for native DOMException controls')
        cls.temporary = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temporary.cleanup)
        output = Path(cls.temporary.name)
        template = (ROOT/'tools/tests/fixtures/typescript_dom_exception_failure.cpp').read_bytes()
        marker = b'// INSERT_EMITTED_DOM_EXCEPTION'
        if template.count(marker) != 1:
            raise AssertionError('unique emitted native exception insertion point required')
        cls.binaries = {}
        for label, source in (('original', originals()[PATH]), ('selected', derive()[0][PATH])):
            start = source.index(b'JSObject *DOMException::create(')
            end = source.index(b'bool DOMException::init_class(', start)
            path = output/(label+'.cpp')
            path.write_bytes(template.replace(marker, source[start:end], 1))
            binary = output/(label+'.exe' if os.name == 'nt' else label)
            if Path(compiler).stem.lower() == 'cl':
                command = [compiler, '/nologo', '/std:c++17', '/EHsc', '/W4', '/WX',
                           str(path), '/Fe:'+str(binary), '/Fo:'+str(output/(label+'.obj'))]
            else:
                command = [compiler, '-std=c++17', '-Wall', '-Wextra', '-Werror',
                           str(path), '-o', str(binary)]
            completed = subprocess.run(command, capture_output=True, timeout=60)
            if completed.returncode or len(completed.stdout)+len(completed.stderr) > 65536:
                raise AssertionError((completed.stdout+completed.stderr)[:65536].decode(errors='replace'))
            cls.binaries[label] = binary

    def control(self, label, case, passed=True):
        result = subprocess.run([str(self.binaries[label]), case], capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0 if passed else 1, (result.stdout+result.stderr)[:65536])
        self.assertLessEqual(len(result.stdout)+len(result.stderr), 65536)
        self.assertEqual(json.loads(result.stdout), {'case': case, 'passed': passed, 'engineQualified': False})

    def test_factory_raise_and_constructor_preserve_native_failure(self):
        for case in (
                'factory-normal', 'factory-reentry', 'factory-first-oom', 'factory-second-oom',
                'factory-string-pending', 'factory-getter-error', 'factory-getter-fatal',
                'factory-getter-pending', 'factory-construct-error', 'factory-construct-fatal',
                'factory-construct-pending', 'factory-wrong-class', 'factory-null-result',
                'factory-entry-pending', 'raise-normal', 'raise-first-oom', 'raise-getter-error',
                'raise-getter-fatal', 'raise-construct-error', 'raise-construct-fatal',
                'raise-wrong-class', 'raise-entry-pending', 'ctor-normal', 'ctor-default-oom',
                'ctor-conversion-error', 'ctor-name-error', 'ctor-conversion-pending',
                'ctor-object-oom', 'ctor-object-pending', 'ctor-entry-pending'):
            with self.subTest(case=case):
                self.control('selected', case)

    def test_original_reproduces_unchecked_pointer_class_and_pending_boundaries(self):
        for case in ('factory-first-oom', 'factory-second-oom', 'factory-getter-error',
                     'factory-getter-pending', 'factory-wrong-class', 'raise-construct-error',
                     'raise-construct-fatal', 'ctor-default-oom', 'ctor-conversion-pending',
                     'ctor-object-pending', 'ctor-entry-pending'):
            with self.subTest(case=case):
                self.control('original', case, False)
        for case in ('ctor-normal', 'ctor-object-oom', 'ctor-conversion-error', 'ctor-name-error'):
            with self.subTest(positive=case):
                self.control('original', case)

    def test_exception_source_and_event_finalization_are_bound_to_the_recipe(self):
        selected, receipt = derive()
        self.assertIn(PATH, {row['path'] for row in receipt['originalSource']})
        self.assertIn(PATH, {row['path'] for row in receipt['derivedSource']})
        header = selected['StarlingMonkey/builtins/web/event/event-target.h']
        self.assertIn(b'BuiltinImpl<EventTarget, EventTargetClassPolicy>', header)
        policy = header[header.index(b'struct EventTargetClassPolicy'):header.index(b'class EventTarget :')]
        self.assertIn(b'return JSCLASS_FOREGROUND_FINALIZE;', policy)
        self.assertNotIn(b'JSCLASS_BACKGROUND_FINALIZE', policy)
        self.assertEqual(receipt['eventFinalizationOwner'], 'foreground-native-lease-retirement')
        self.assertFalse(receipt['signedLSFComponentQualified'])


if __name__ == '__main__':
    unittest.main()
