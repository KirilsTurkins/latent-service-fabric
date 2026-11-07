"""Exact original-source graph lifecycle derivation; not engine qualification."""
from pathlib import Path
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from tools.typescript_guest import event_engine as events, abort_engine

FIXTURES = Path(__file__).parent/'fixtures/typescript_runtime_profile'


def originals():
    return {name: (FIXTURES/'event-original'/name.removeprefix('StarlingMonkey/')).read_bytes()
            for name in events.PREIMAGES}


def derive():
    source, _ = abort_engine.derive_abort_timeout((FIXTURES/'original-abort-signal.cpp').read_bytes())
    return events.derive_event_ownership(originals(), source)


def emitted_listener_body(source):
    function = source.index(b'bool EventTarget::add_listener(')
    start = source.index(b'  auto *it = std::find_if(', function)
    end = source.index(b'\n  return true;\n}\n\n// https://dom.spec.whatwg.org/#dom-eventtarget-removeeventlistener', start)
    return source[start:end]


class TypeScriptEventOwnershipTests(unittest.TestCase):
    def test_original_declaration_or_native_source_drift_is_rejected(self):
        value = originals()
        for name in value:
            changed = dict(value, **{name: value[name]+b'changed'})
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, 'unreviewed-original-Event-source'):
                events.derive_event_ownership(changed, b'not-used')

    def test_each_abort_container_is_admitted_before_publication(self):
        derived, _ = derive()
        source = derived[abort_engine.PATH]
        start = source.index(b'JSObject *AbortSignal::create(')
        end = source.index(b'// https://dom.spec.whatwg.org/#dom-abortsignal-abort', start)
        body = source[start:end]
        self.assertEqual(body.count(b'make_native_container<'), 3)
        self.assertLess(body.index(b'if (!dependents) return nullptr;'), body.index(b'algorithms.release()'))
        self.assertNotIn(b'new AlgorithmList', source)
        self.assertNotIn(b'new WeakIndexSet', source)

    def test_abort_finalizer_physically_destroys_all_three_containers_without_host_calls(self):
        derived, receipt = derive()
        source = derived[abort_engine.PATH]
        body = source[source.index(b'void AbortSignal::finalize('):source.index(b'void AbortSignal::trace(')]
        self.assertIn(b'Slots::Algorithms, Slots::SourceSignals, Slots::DependentSignals', body)
        self.assertIn(b'delete static_cast<OwnedAlgorithmList *>', body)
        self.assertIn(b'delete static_cast<OwnedWeakSet *>', body)
        self.assertIn(b'EventTarget::finalize(gcx, self);', body)
        self.assertNotIn(b'latent_runtime_activation_', body)
        self.assertFalse(receipt['hostImportsDuringGC'])

    def test_listener_vector_views_preserve_original_elements_and_gc_trace(self):
        derived, _ = derive()
        source = derived['StarlingMonkey/builtins/web/event/event-target.cpp']
        header = derived['StarlingMonkey/builtins/web/event/event-target.h']
        self.assertIn(b'using ListenerList = JS::GCVector<ListenerRef, 0, js::SystemAllocPolicy>;', header)
        self.assertIn(b'auto *list = &owned->value;', source)
        self.assertIn(b'list->trace(trc);', source)
        self.assertEqual(source.count(b'make_native_container<ListenerList>(cx)'), 3)
        self.assertIn(b'delete static_cast<OwnedListenerList *>(slot.toPrivate());', source)

    def test_listener_and_abort_algorithm_admission_precedes_all_native_captures(self):
        derived, _ = derive()
        source = derived['StarlingMonkey/builtins/web/event/event-target.cpp']
        listener = source.index(b'js_new<EventListener>(')
        self.assertLess(source.rindex(b'admit_native_object(cx, accepted)', 0, listener), listener)
        terminator = source.index(b'js::MakeUnique<Terminator>(')
        self.assertLess(source.rindex(b'admit_native_object(cx, accepted)', 0, terminator), terminator)
        self.assertIn(b'if (!AbortSignal::add_algorithm(signal, std::move(terminator))) {', source)
        self.assertLess(source.index(b'if (!list->reserve(list->length() + 1))'), terminator)
        self.assertLess(terminator, source.index(b'list->infallibleAppend(staged);', terminator))
        self.assertLess(source.index(b'if (!AbortSignal::add_algorithm(signal, std::move(terminator)))'),
                        source.index(b'staged->callback = callback_val;'))

    def test_all_original_abort_subclasses_transfer_ownership_and_keep_callback_bodies(self):
        before = originals()
        selected, _ = derive()
        for name, declaration in (
                ('StarlingMonkey/builtins/web/event/event-target.cpp', b'struct Terminator : AbortAlgorithm'),
                ('StarlingMonkey/builtins/web/fetch/fetch-api.cpp', b'struct Terminator : AbortAlgorithm'),
                ('StarlingMonkey/builtins/web/fetch/request-response.cpp', b'struct ResponseAborter : abort::AbortAlgorithm')):
            with self.subTest(name=name):
                original = before[name][before[name].index(declaration):]
                derived = selected[name][selected[name].index(declaration):]
                original = original[:original.index(b'\n};')]
                derived = derived[:derived.index(b'\n};')]
                self.assertEqual(derived.count(b'AbortAlgorithm(std::move(owner))'), 1)
                self.assertEqual(original[original.index(b'  bool run('):], derived[derived.index(b'  bool run('):])
        header = selected['StarlingMonkey/builtins/web/abort/abort-signal.h']
        self.assertNotIn(b'\n  AbortAlgorithm() = default;', header)
        self.assertIn(b'AbortAlgorithm(const AbortAlgorithm &) = delete;', header)

    def test_fetch_abort_owner_denial_precedes_request_effect_and_checks_publication(self):
        selected, _ = derive()
        source = selected['StarlingMonkey/builtins/web/fetch/fetch-api.cpp']
        admitted = source.index(b'admit_native_object(cx, abort_owner)')
        self.assertLess(admitted, source.index(b'host_api::HttpOutgoingRequest::make('))
        self.assertLess(admitted, source.index(b'request->send()'))
        self.assertEqual(source.count(b'request->send()'), 1)
        self.assertIn(b'js::MakeUnique<Terminator>(std::move(abort_owner), weak)', source)
        allocation = source.index(b'auto algorithm = js::MakeUnique<Terminator>')
        failure = source.index(b'if (!algorithm) { JS_ReportOutOfMemory(cx); return false; }', allocation)
        publication = source.index(b'if (!AbortSignal::add_algorithm(signal, std::move(algorithm))) return false;', allocation)
        self.assertLess(allocation, failure)
        self.assertLess(failure, publication)
        # Original accepted response work remains owned by its engine queue.
        queued = source.index(b'ENGINE->queue_async_task(task.release());')
        self.assertLess(queued, allocation)
        # Both original context fields must be published even when a later
        # allocation or vector insertion fails after accepted work is queued.
        sent = source.index(b'pending_handle = res.unwrap();')
        for field in (b'Request::Slots::ResponsePromise', b'Request::Slots::PendingResponseHandle'):
            self.assertEqual(source.count(field), 1)
            self.assertLess(sent, source.index(field))
            self.assertLess(source.index(field), queued)

    def test_response_abort_owner_denial_precedes_result_consumption_and_keeps_raii(self):
        selected, _ = derive()
        source = selected['StarlingMonkey/builtins/web/fetch/request-response.cpp']
        admitted = source.index(b'admit_native_object(cx, abort_owner)')
        self.assertLess(admitted, source.index(b'future_->maybe_response()'))
        self.assertIn(b'if (AbortSignal::is_instance(signal) &&\n'
                      b'      !lsf::typescript::activation::admit_native_object(cx, abort_owner)) return false;', source)
        self.assertIn(b'std::move(abort_owner), response_promise, response_obj, signal', source)
        self.assertIn(b'if (!algorithm) { JS_ReportOutOfMemory(cx); return false; }', source)
        self.assertIn(b'if (!AbortSignal::add_algorithm(signal, std::move(algorithm))) return false;', source)

    def test_original_listener_order_callback_once_and_abort_reason_bodies_are_unchanged(self):
        before = originals()
        derived, _ = derive()
        name = 'StarlingMonkey/builtins/web/event/event-target.cpp'
        start = b'bool EventTarget::inner_invoke('
        end = b'JSObject *EventTarget::create('
        original = before[name][before[name].index(start):before[name].index(end)]
        changed = derived[name][derived[name].index(start):derived[name].index(end)]
        previous = b'      return true;\n'
        replacement = b'      break; // remove already-fired once listeners before returning\n'
        self.assertEqual(changed.count(replacement), 1)
        changed = changed.replace(replacement, previous, 1)
        changed = changed.replace(b'  bool listeners_removed = false;\n  bool invocation_failed = false;\n',
                                  b'  bool listeners_removed = false;\n', 1)
        changed = changed.replace(b'        invocation_failed = true;\n        break;\n',
                                  b'        return false;\n', 1)
        changed = changed.replace(b'  return !invocation_failed;\n', b'  return true;\n', 1)
        self.assertEqual(changed, original)
        dispatch_start = b'bool EventTarget::dispatch(JSContext *cx'
        dispatch_end = b'bool EventTarget::invoke_listeners('
        original_dispatch = before[name][before[name].index(dispatch_start):before[name].index(dispatch_end)]
        changed_dispatch = derived[name][derived[name].index(dispatch_start):derived[name].index(dispatch_end)]
        changed_dispatch = changed_dispatch.replace(b'  const bool invoked = invoke_listeners(cx, target, event);\n',
            b'  if (!invoke_listeners(cx, target, event)) {\n    return false;\n  }\n', 1)
        changed_dispatch = changed_dispatch.replace(
            b'  if (!invoked) return false; // preserve the original pending exception\n', b'', 1)
        self.assertEqual(changed_dispatch, original_dispatch)
        invoke_start = b'bool EventTarget::invoke_listeners('
        invoke_end = b'// https://dom.spec.whatwg.org/#concept-event-listener-inner-invoke'
        original_invoke = before[name][before[name].index(invoke_start):before[name].index(invoke_end)]
        changed_invoke = derived[name][derived[name].index(invoke_start):derived[name].index(invoke_end)]
        addition = (b'  // The owner outlives the rooted vector and its backing allocation.\n'
                    b'  lsf::typescript::activation::NativeObjectFrameLease clone_owner;\n')
        admission = (b'  if (list->length() > list_clone.capacity() &&\n'
                     b'      !lsf::typescript::activation::admit_native_object(cx, clone_owner.lease())) return false;\n')
        self.assertEqual(changed_invoke.count(addition), 1)
        self.assertEqual(changed_invoke.count(admission), 1)
        self.assertEqual(changed_invoke.replace(addition, b'', 1).replace(admission, b'', 1), original_invoke)
        abort = (FIXTURES/'original-abort-signal.cpp').read_bytes()
        begin = b'bool AbortSignal::abort(JSContext *cx, HandleObject self, HandleValue reason)'
        ending = b'JSObject *AbortSignal::create('
        original_abort = abort[abort.index(begin):abort.index(ending)]
        changed_abort = derived[abort_engine.PATH][derived[abort_engine.PATH].index(begin):derived[abort_engine.PATH].index(ending)]
        replacement = (b'  // With no newly aborted dependents there is no later abort work to skip.\n'
                       b'  if (!run_abort_steps(cx, self) && dep_signals_to_abort.empty()) return false;\n')
        self.assertEqual(changed_abort.count(replacement), 1)
        reason_check = b'  if (!set_reason(cx, self, reason)) return false;\n'
        rooted_reason = b'  RootedValue propagated_reason(cx, AbortSignal::reason(self));\n'
        dependent_reason = b'      if (!set_reason(cx, signal, propagated_reason)) return false;\n'
        null_check = b'  if (!event) return false;\n'
        self.assertEqual(changed_abort.count(reason_check), 1)
        self.assertEqual(changed_abort.count(rooted_reason), 1)
        self.assertEqual(changed_abort.count(dependent_reason), 1)
        self.assertLess(changed_abort.index(reason_check), changed_abort.index(rooted_reason))
        self.assertLess(changed_abort.index(rooted_reason), changed_abort.index(dependent_reason))
        self.assertEqual(changed_abort.count(null_check), 1)
        changed_abort = changed_abort.replace(replacement, b'  run_abort_steps(cx, self);\n', 1)
        changed_abort = changed_abort.replace(rooted_reason, b'', 1)
        changed_abort = changed_abort.replace(dependent_reason, b'      set_reason(cx, signal, reason);\n', 1)
        changed_abort = changed_abort.replace(reason_check, b'  set_reason(cx, self, reason);\n', 1)
        self.assertEqual(changed_abort.replace(null_check, b'', 1), original_abort)

    def test_owned_graph_changes_remain_unqualified_and_snapshot_mutation_is_denied(self):
        _, receipt = derive()
        self.assertEqual(receipt['snapshotMutableGraphs'], 'denied')
        self.assertFalse(receipt['supportedAsyncProfile'])
        self.assertFalse(receipt['signedLSFComponentQualified'])
        self.assertEqual(receipt['nativeGraphRetirement'], 'destructor-then-collection-end-then-safe-host-ack')
        self.assertEqual(receipt['dispatchCloneRetirement'], 'frame-destructor-then-safe-host-ack')
        self.assertEqual(receipt['dispatchCloneOwner'], 'one-original-native-count-not-byte-accurate')

    def test_global_listener_graph_is_lazy_and_not_frozen_during_compiler_snapshot(self):
        derived, _ = derive()
        source = derived['StarlingMonkey/builtins/web/event/global-event-target.cpp']
        start = source.index(b'bool global_event_target_init(')
        body = source[start:]
        self.assertNotIn(b'EventTarget::create(cx)', body)
        self.assertIn(b'GLOBAL_EVENT_TARGET.init(cx);', body)
        self.assertEqual(source.count(b'if (!ensure_global_event_target(cx)) return false;'), 3)
        self.assertIn(b'if (!created) return false;', source)
        self.assertIn(b'GLOBAL_EVENT_TARGET = created;', source)

    def test_all_new_native_and_derivation_inputs_are_captured_by_builder(self):
        from tools.typescript_guest.activation_engine import engine_input_paths
        from tools.typescript_guest.build import RECIPE
        for name in ('sdk/typescript-guest/activation/native_objects.h',
                     'sdk/typescript-guest/activation/native_retirement.h',
                     'tools/typescript_guest/event_engine.py'):
            self.assertIn(name, engine_input_paths())
            self.assertIn(name, RECIPE)


class AbortFailureControls(unittest.TestCase):
    """Run both emitted abort functions against finite doubles, not an engine."""
    @classmethod
    def setUpClass(cls):
        compiler = os.environ.get('LSF_TYPESCRIPT_RECORD_CXX') or shutil.which('c++') or shutil.which('cl')
        if not compiler:
            if os.name == 'nt':
                raise unittest.SkipTest('A C++ compiler is required for abort failure controls')
            raise RuntimeError('C++ compiler is required for abort failure controls')
        cls.temporary = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temporary.cleanup)
        output = Path(cls.temporary.name)
        template = (Path(__file__).parent/'fixtures/typescript_abort_failure.cpp').read_bytes()
        abort_start = b'bool AbortSignal::abort(JSContext *cx, HandleObject self, HandleValue reason)'
        steps_start = b'bool AbortSignal::run_abort_steps('
        steps_end = b'// Set signal\'s abort reason to reason if it is given;'
        abort_end = b'// https://dom.spec.whatwg.org/#run-the-abort-steps'
        original = (FIXTURES/'original-abort-signal.cpp').read_bytes()
        selected = derive()[0][abort_engine.PATH]
        for label, source in (('selected', selected), ('original', original)):
            body = source[source.index(abort_start):source.index(abort_end)]
            steps = source[source.index(steps_start):source.index(steps_end)]
            fixture = template
            for marker, code in ((b'// INSERT_EMITTED_ABORT_FUNCTION\n', body),
                                 (b'// INSERT_EMITTED_ABORT_STEPS_FUNCTION\n', steps)):
                if fixture.count(marker) != 1:
                    raise AssertionError('unique emitted abort insertion point required')
                fixture = fixture.replace(marker, code, 1)
            source_file = output/(label+'.cpp')
            source_file.write_bytes(fixture)
            binary = output/(label+'.exe' if os.name == 'nt' else label)
            if Path(compiler).stem.lower() == 'cl':
                args = [compiler, '/nologo', '/std:c++17', '/EHsc', '/W4', '/WX',
                        str(source_file), '/Fe:'+str(binary), '/Fo:'+str(output/(label+'.obj'))]
            else:
                args = [compiler, '-std=c++17', '-Wall', '-Wextra', '-Werror',
                        str(source_file), '-o', str(binary)]
            result = subprocess.run(args, capture_output=True, timeout=60)
            if result.returncode or len(result.stdout) + len(result.stderr) > 65536:
                raise AssertionError((result.stdout + result.stderr)[:65536].decode(errors='replace'))
            setattr(cls, label+'_binary', binary)

    def test_failure_preserves_original_exception_and_completed_or_retained_work(self):
        for case in ('success', 'dispatch-failure', 'event-failure', 'reason-failure',
                     'algorithm-failure', 'dependent-continuation', 'default-reason',
                     'explicit-reason', 'already-aborted'):
            with self.subTest(case=case):
                result = subprocess.run([str(self.selected_binary), case], capture_output=True, timeout=10)
                self.assertEqual(result.returncode, 0, (result.stdout + result.stderr)[:65536])
                self.assertEqual(json.loads(result.stdout),
                                 {'case': case, 'passed': True, 'engineQualified': False})

    def test_pinned_original_reproduces_narrow_failure_boundaries(self):
        for case in ('dispatch-failure', 'event-failure', 'reason-failure', 'algorithm-failure', 'default-reason'):
            with self.subTest(case=case):
                result = subprocess.run([str(self.original_binary), case], capture_output=True, timeout=10)
                self.assertEqual(result.returncode, 1, (result.stdout + result.stderr)[:65536])
                self.assertEqual(json.loads(result.stdout),
                                 {'case': case, 'passed': False, 'engineQualified': False})
        for case in ('success', 'dependent-continuation', 'explicit-reason', 'already-aborted'):
            with self.subTest(case=case):
                result = subprocess.run([str(self.original_binary), case], capture_output=True, timeout=10)
                self.assertEqual(result.returncode, 0, (result.stdout + result.stderr)[:65536])


class EventPublicationControls(unittest.TestCase):
    """Execute emitted C++ with finite doubles, not a signed-engine witness."""
    @classmethod
    def setUpClass(cls):
        compiler = os.environ.get('LSF_TYPESCRIPT_RECORD_CXX') or shutil.which('c++') or shutil.which('cl')
        if not compiler:
            if os.name == 'nt':
                raise unittest.SkipTest('A C++ compiler is required for event publication controls')
            raise RuntimeError('C++ compiler is required for event publication controls')
        cls.temporary = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temporary.cleanup)
        output = Path(cls.temporary.name)
        root = Path(__file__).resolve().parents[2]
        template = (root/'tools/tests/fixtures/typescript_event_publication.cpp').read_bytes()
        marker = b'  // INSERT_EMITTED_EVENT_BODY'
        if template.count(marker) != 1:
            raise AssertionError('unique production-body insertion point required')
        selected = derive()[0]['StarlingMonkey/builtins/web/event/event-target.cpp']
        source = output/'event_publication.cpp'
        source.write_bytes(template.replace(marker, emitted_listener_body(selected)))
        cls.binary = output/('event_publication.exe' if os.name == 'nt' else 'event_publication')
        if Path(compiler).stem.lower() == 'cl':
            args = [compiler, '/nologo', '/std:c++17', '/EHsc', '/W4', '/WX',
                    str(source), '/Fe:' + str(cls.binary), '/Fo:' + str(output/'event_publication.obj')]
        else:
            args = [compiler, '-std=c++17', '-Wall', '-Wextra', '-Werror',
                    str(source), '-o', str(cls.binary)]
        result = subprocess.run(args, capture_output=True, timeout=60)
        if result.returncode or len(result.stdout) + len(result.stderr) > 65536:
            raise AssertionError((result.stdout + result.stderr)[:65536].decode(errors='replace'))

        invoke_start = b'bool EventTarget::invoke_listeners('
        invoke_end = b'// https://dom.spec.whatwg.org/#concept-event-listener-inner-invoke'
        template = (root/'tools/tests/fixtures/typescript_event_clone_ownership.cpp').read_bytes()
        marker = b'// INSERT_EMITTED_INVOKE_LISTENERS'
        if template.count(marker) != 1:
            raise AssertionError('unique invoke-listeners insertion point required')
        original = originals()['StarlingMonkey/builtins/web/event/event-target.cpp']
        for label, input_source in (('clone_selected', selected), ('clone_original', original)):
            emitted = input_source[input_source.index(invoke_start):input_source.index(invoke_end)]
            clone_source = output/(label+'.cpp')
            clone_source.write_bytes(template.replace(marker, emitted))
            binary = output/(label+'.exe' if os.name == 'nt' else label)
            if Path(compiler).stem.lower() == 'cl':
                args = [compiler, '/nologo', '/std:c++17', '/EHsc', '/W4', '/WX',
                        '/I'+str(root/'sdk/typescript-guest/activation'), str(clone_source),
                        '/Fe:'+str(binary), '/Fo:'+str(output/(label+'.obj'))]
            else:
                args = [compiler, '-std=c++17', '-Wall', '-Wextra', '-Werror',
                        '-I'+str(root/'sdk/typescript-guest/activation'), str(clone_source), '-o', str(binary)]
            result = subprocess.run(args, capture_output=True, timeout=60)
            if result.returncode or len(result.stdout) + len(result.stderr) > 65536:
                raise AssertionError((result.stdout + result.stderr)[:65536].decode(errors='replace'))
            setattr(cls, label+'_binary', binary)
        if not cls.binary.is_file() or cls.binary.stat().st_size > 4*1024**2:
            raise AssertionError('finite event publication control required')
        inner = selected.index(b'bool EventTarget::inner_invoke(')
        stop_start = selected.index(b'    if (Event::has_flag(event, EventFlag::StopImmediatePropagation)) {', inner)
        stop_end = selected.index(b'\n    }', stop_start) + len(b'\n    }')
        cleanup_start = selected.index(b'  if (listeners_removed) {', stop_end)
        cleanup_end = selected.index(b'\n  }', cleanup_start) + len(b'\n  }')
        getter_start = selected.index(b'      if (!JS_GetProperty(cx, callback_obj, "handleEvent", &handle_fn)) {', inner)
        getter_end = selected.index(b'\n      }', getter_start) + len(b'\n      }')
        failure_flag = (b'    bool invocation_failed = false;' if
                        b'  bool invocation_failed = false;' in selected[inner:stop_start] else b'')
        return_start = selected.index(b'  return ', cleanup_end)
        return_end = selected.index(b'\n', return_start)
        dispatch = (root/'tools/tests/fixtures/typescript_once_dispatch.cpp').read_bytes()
        for marker, actual in ((b'      // INSERT_EMITTED_STOP_BLOCK', selected[stop_start:stop_end]),
                               (b'    // INSERT_EMITTED_CLEANUP_BLOCK', selected[cleanup_start:cleanup_end]),
                               (b'    // INSERT_FAILURE_FLAG', failure_flag),
                               (b'        // INSERT_EMITTED_GETTER_BLOCK', selected[getter_start:getter_end]),
                               (b'    // INSERT_EMITTED_INNER_RETURN', selected[return_start:return_end])):
            if dispatch.count(marker) != 1:
                raise AssertionError('unique emitted dispatch insertion point required')
            dispatch = dispatch.replace(marker, actual)
        dispatch_source = output/'once_dispatch.cpp'
        dispatch_source.write_bytes(dispatch)
        cls.dispatch_binary = output/('once_dispatch.exe' if os.name == 'nt' else 'once_dispatch')
        if Path(compiler).stem.lower() == 'cl':
            args = [compiler, '/nologo', '/std:c++17', '/EHsc', '/W4', '/WX', str(dispatch_source),
                    '/Fe:' + str(cls.dispatch_binary), '/Fo:' + str(output/'once_dispatch.obj')]
        else:
            args = [compiler, '-std=c++17', '-Wall', '-Wextra', '-Werror',
                    str(dispatch_source), '-o', str(cls.dispatch_binary)]
        result = subprocess.run(args, capture_output=True, timeout=60)
        if result.returncode or len(result.stdout) + len(result.stderr) > 65536:
            raise AssertionError((result.stdout + result.stderr)[:65536].decode(errors='replace'))
        dispatch_function = selected.index(b'bool EventTarget::dispatch(JSContext *cx')
        completion_start = selected.index(b'  // 7. Set event\'s eventPhase attribute to NONE.', dispatch_function)
        invoked_start = selected.rfind(b'  const bool invoked = ', dispatch_function, completion_start)
        if invoked_start < 0:
            invoked_start = selected.index(b'  if (!invoke_listeners(cx, target, event)) {', dispatch_function)
        completion_end = selected.index(b'\n}', completion_start)
        event_fixture = (root/'tools/tests/fixtures/typescript_event_dispatch_error.cpp').read_bytes()
        event_marker = b'  // INSERT_EMITTED_DISPATCH_COMPLETION'
        if event_fixture.count(event_marker) != 1:
            raise AssertionError('unique dispatch completion insertion point required')
        event_source = output/'event_error_dispatch.cpp'
        event_source.write_bytes(event_fixture.replace(event_marker, selected[invoked_start:completion_end]))
        cls.event_binary = output/('event_error_dispatch.exe' if os.name == 'nt' else 'event_error_dispatch')
        if Path(compiler).stem.lower() == 'cl':
            args = [compiler, '/nologo', '/std:c++17', '/EHsc', '/W4', '/WX', str(event_source),
                    '/Fe:' + str(cls.event_binary), '/Fo:' + str(output/'event_error_dispatch.obj')]
        else:
            args = [compiler, '-std=c++17', '-Wall', '-Wextra', '-Werror',
                    str(event_source), '-o', str(cls.event_binary)]
        result = subprocess.run(args, capture_output=True, timeout=60)
        if result.returncode or len(result.stdout) + len(result.stderr) > 65536:
            raise AssertionError((result.stdout + result.stderr)[:65536].decode(errors='replace'))

    def test_registration_and_reactivation_failure_boundaries(self):
        for case in (
            'native-refusal-before-listener-publication',
            'algorithm-refusal-before-listener-publication',
            'vector-refusal-before-algorithm-publication',
            'successful-registration-retains-both-owners',
            'once-listener-reinserted-after-original-neighbor',
            'reactivation-refusal-keeps-existing-listener',
            'signal-aborted-during-type-conversion',
        ):
            with self.subTest(case=case):
                result = subprocess.run([str(self.binary), case], capture_output=True, timeout=10)
                self.assertEqual(result.returncode, 0, (result.stdout + result.stderr)[:65536])
                self.assertEqual(json.loads(result.stdout),
                                 {'case': case, 'passed': True, 'engineQualified': False})

    def test_once_listener_physically_retires_after_immediate_stop(self):
        for case in ('once-immediate-stop-retires-listener', 'once-without-stop-cleans-up',
                     'ordinary-stop-keeps-listeners'):
            with self.subTest(case=case):
                result = subprocess.run([str(self.dispatch_binary), case], capture_output=True, timeout=10)
                self.assertEqual(result.returncode, 0, (result.stdout + result.stderr)[:65536])
                self.assertEqual(json.loads(result.stdout),
                                 {'case': case, 'passed': True, 'engineQualified': False})

    def test_listener_lookup_error_runs_retirement_and_dispatch_cleanup(self):
        for binary, cases in (
                (self.dispatch_binary, ('once-getter-failure-retires-listener',)),
                (self.event_binary, ('lookup-error-resets-dispatch', 'success-resets-dispatch',
                                     'success-preserves-canceled-result'))):
            for case in cases:
                with self.subTest(case=case):
                    result = subprocess.run([str(binary), case], capture_output=True, timeout=10)
                    self.assertEqual(result.returncode, 0, (result.stdout + result.stderr)[:65536])
                    self.assertEqual(json.loads(result.stdout),
                                     {'case': case, 'passed': True, 'engineQualified': False})

    def test_dispatch_clone_owns_each_heap_frame_and_retains_original_failure(self):
        for case in ('inline', 'heap', 'refusal', 'reserve-failure', 'nested', 'nested-refusal',
                     'repeated', 'gc-object-not-retired', 'callback-failure', 'ack-refusal'):
            with self.subTest(case=case):
                result = subprocess.run([str(self.clone_selected_binary), case], capture_output=True, timeout=10)
                self.assertEqual(result.returncode, 0, (result.stdout + result.stderr)[:65536])
                self.assertEqual(json.loads(result.stdout),
                                 {'case': case, 'passed': True, 'engineQualified': False})

    def test_pinned_original_reproduces_unowned_heap_clone_and_nested_refusal_gap(self):
        for case in ('heap', 'refusal', 'nested-refusal'):
            with self.subTest(case=case):
                result = subprocess.run([str(self.clone_original_binary), case], capture_output=True, timeout=10)
                self.assertEqual(result.returncode, 1, (result.stdout + result.stderr)[:65536])
                self.assertEqual(json.loads(result.stdout),
                                 {'case': case, 'passed': False, 'engineQualified': False})


if __name__ == '__main__':
    unittest.main()
