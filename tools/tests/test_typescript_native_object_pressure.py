"""Rooted native-allocation pressure boundary; not signed-engine qualification."""
from pathlib import Path
import json
import os
import shutil
import subprocess
import tempfile
import unittest

from tools.tests.test_typescript_event_ownership import derive, emitted_listener_body

ROOT = Path(__file__).resolve().parents[2]
NATIVE = ROOT / 'sdk/typescript-guest/activation'


class NativeObjectPressureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        compiler = os.environ.get('LSF_TYPESCRIPT_RECORD_CXX') or shutil.which('c++') or shutil.which('cl')
        if not compiler:
            raise RuntimeError('A C++ compiler is required for native pressure controls')
        cls.temporary = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temporary.cleanup)
        output = Path(cls.temporary.name)
        source = (ROOT / 'tools/tests/fixtures/typescript_native_object_pressure.cpp').read_bytes()
        engine = (NATIVE / 'native_engine.cpp').read_bytes()
        records = (NATIVE / 'promise_records.h').read_bytes()
        pieces = {
            b'// INSERT_PRESSURE_TEMPLATE': records[records.index(b'template<class Checkpoint>'):records.index(b'class PromiseRecords final')],
            b'// INSERT_COLLECTION_HELPER': engine[engine.index(b'bool collect_before_native_allocation('):engine.index(b'bool before_promise_allocate(')],
            b'// INSERT_PREPARE_AND_ADMIT': engine[engine.index(b'bool prepare_native_object_allocation('):engine.index(b'bool has_pending_promises(')],
        }
        for marker, body in pieces.items():
            if source.count(marker) != 1:
                raise AssertionError('unique production-body insertion point required')
            source = source.replace(marker, body, 1)
        path = output / 'pressure.cpp'
        path.write_bytes(source)
        cls.binary = output / ('pressure.exe' if os.name == 'nt' else 'pressure')
        if Path(compiler).stem.lower() == 'cl':
            command = [compiler, '/nologo', '/std:c++17', '/EHsc', '/W4', '/WX', '/I' + str(NATIVE),
                       str(path), '/Fe:' + str(cls.binary), '/Fo:' + str(output / 'pressure.obj')]
        else:
            command = [compiler, '-std=c++17', '-Wall', '-Wextra', '-Werror', '-I' + str(NATIVE),
                       str(path), '-o', str(cls.binary)]
        result = subprocess.run(command, capture_output=True, timeout=60)
        if result.returncode:
            raise AssertionError((result.stdout + result.stderr)[:65536].decode(errors='replace'))

        template = (ROOT / 'tools/tests/fixtures/typescript_event_publication.cpp').read_bytes()
        selected = derive()[0]['StarlingMonkey/builtins/web/event/event-target.cpp']
        path.write_bytes(template.replace(b'  // INSERT_EMITTED_EVENT_BODY', emitted_listener_body(selected)))
        # The first binary is preserved; compile the same emitted listener body
        # with the finite publication doubles for preparation-failure controls.
        cls.listener_binary = output / ('listener.exe' if os.name == 'nt' else 'listener')
        replacements = {str(cls.binary): str(cls.listener_binary),
                        '/Fe:' + str(cls.binary): '/Fe:' + str(cls.listener_binary)}
        listener_command = [replacements.get(item, item) for item in command]
        result = subprocess.run(listener_command, capture_output=True, timeout=60)
        if result.returncode:
            raise AssertionError((result.stdout + result.stderr)[:65536].decode(errors='replace'))

    def test_pressure_observes_physical_death_and_cannot_expand_admission(self):
        for case in ('below-pressure', 'collect-dead-before-admission', 'reachable-owners-still-refuse',
                     'admission-never-collects-staged-captures', 'physical-death-needs-collection-end',
                     'retirement-refusal-fences-preflight', 'entry-exception-is-preserved',
                     'snapshot-is-not-collected-or-admitted'):
            with self.subTest(case=case):
                result = subprocess.run([str(self.binary), case], capture_output=True, timeout=10)
                self.assertEqual(result.returncode, 0, (result.stdout + result.stderr)[:65536])
                self.assertEqual(json.loads(result.stdout),
                                 {'case': case, 'passed': True, 'engineQualified': False})

    def test_preflight_failure_keeps_original_listener_publication_unchanged(self):
        for case in ('pressure-refusal-before-listener-publication', 'pressure-refusal-keeps-removed-listener'):
            with self.subTest(case=case):
                result = subprocess.run([str(self.listener_binary), case], capture_output=True, timeout=10)
                self.assertEqual(result.returncode, 0, (result.stdout + result.stderr)[:65536])
                self.assertEqual(json.loads(result.stdout),
                                 {'case': case, 'passed': True, 'engineQualified': False})

    def test_abort_preflight_precedes_factory_weak_cursors_and_staged_captures(self):
        source = derive()[0]['StarlingMonkey/builtins/web/abort/abort-signal.cpp']
        start = source.index(b'bool AbortSignal::abort(')
        end = source.index(b'bool AbortSignal::run_abort_steps(', start)
        body = source[start:end]
        preflight = body.index(b'prepare_native_object_allocation(cx)')
        self.assertIn(b'HandleObject self, HandleValue reason)', body[:preflight])
        self.assertLess(body.index(b'if (JS_IsExceptionPending(cx)) return false;'), preflight)
        self.assertLess(body.index(b'if (is_aborted(self)) return true;'), preflight)
        for marker in (b'RootedValue propagated_reason', b'NativeObjectFrameLease dependents_owner',
                       b'JS::RootedObjectVector', b'auto *dep_signals = dependent_signals(self)'):
            self.assertLess(preflight, body.index(marker))
        self.assertEqual(body.count(b'prepare_native_object_allocation(cx)'), 1)
        self.assertNotIn(b'collectNativePressure', body)

    def test_listener_preflight_has_rooted_inputs_and_no_staged_capture_or_iterator(self):
        source = derive()[0]['StarlingMonkey/builtins/web/event/event-target.cpp']
        start = source.index(b'bool EventTarget::add_listener(')
        end = source.index(b'bool EventTarget::remove_listener(', start)
        body = source[start:end]
        preflight = body.index(b'prepare_native_object_allocation(cx)')
        self.assertIn(b'HandleObject self, HandleValue type_val,', body[:preflight])
        self.assertIn(b'HandleValue callback_val, HandleValue opts_val)', body[:preflight])
        self.assertIn(b'RootedValue signal_val(cx);', body[:preflight])
        self.assertIn(b'it = nullptr; // discard the cursor before possible collection', body[:preflight])
        self.assertIn(b'if (it != list->end() && !(*it)->removed) return true;', body[:preflight])
        self.assertNotIn(b'it - list->begin()', body[preflight:])
        self.assertLess(preflight, body.index(b'NativeObjectLease listener_owner;'))
        self.assertLess(preflight, body.index(b'js_new<EventListener>'))
        self.assertEqual(body.count(b'prepare_native_object_allocation(cx)'), 1)
        self.assertNotIn(b'collectNativePressure', body)


if __name__ == '__main__':
    unittest.main()
