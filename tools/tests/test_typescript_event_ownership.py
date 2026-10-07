"""Exact original-source graph lifecycle derivation; not engine qualification."""
from pathlib import Path
import hashlib
import unittest
from tools.typescript_guest import event_engine as events, abort_engine

FIXTURES = Path(__file__).parent/'fixtures/typescript_runtime_profile'


def originals():
    return {name: (FIXTURES/'event-original'/name.removeprefix('StarlingMonkey/')).read_bytes()
            for name in events.PREIMAGES}


def derive():
    source, _ = abort_engine.derive_abort_timeout((FIXTURES/'original-abort-signal.cpp').read_bytes())
    return events.derive_event_ownership(originals(), source)


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
        self.assertIn(b'if (!AbortSignal::add_algorithm(signal, std::move(terminator))) return false;', source)
        self.assertIn(b'if (!list->append(listener))', source)

    def test_original_listener_order_callback_once_and_abort_reason_bodies_are_unchanged(self):
        before = originals()
        derived, _ = derive()
        name = 'StarlingMonkey/builtins/web/event/event-target.cpp'
        start = b'bool EventTarget::inner_invoke('
        end = b'JSObject *EventTarget::create('
        self.assertEqual(before[name][before[name].index(start):before[name].index(end)],
                         derived[name][derived[name].index(start):derived[name].index(end)])
        abort = (FIXTURES/'original-abort-signal.cpp').read_bytes()
        begin = b'bool AbortSignal::abort(JSContext *cx, HandleObject self, HandleValue reason)'
        ending = b'JSObject *AbortSignal::create('
        self.assertEqual(abort[abort.index(begin):abort.index(ending)],
                         derived[abort_engine.PATH][derived[abort_engine.PATH].index(begin):derived[abort_engine.PATH].index(ending)])

    def test_owned_graph_changes_remain_unqualified_and_snapshot_mutation_is_denied(self):
        _, receipt = derive()
        self.assertEqual(receipt['snapshotMutableGraphs'], 'denied')
        self.assertFalse(receipt['supportedAsyncProfile'])
        self.assertFalse(receipt['signedLSFComponentQualified'])
        self.assertEqual(receipt['nativeGraphRetirement'], 'destructor-then-collection-end-then-safe-host-ack')

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


if __name__ == '__main__':
    unittest.main()
