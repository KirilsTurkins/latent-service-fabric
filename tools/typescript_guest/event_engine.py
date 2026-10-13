"""Pinned Abort/Event physical graph ownership, independent of API qualification."""
from __future__ import annotations
import hashlib
from tools.typescript_guest.activation_engine import identity, replace_once, STARLING_COMMIT

PREIMAGES = {
    'StarlingMonkey/builtins/web/event/event-target.cpp': '0b22572ccb4de19fb1476073d0586d1afe03c856454a466d0d2c6607ace20ffd',
    'StarlingMonkey/builtins/web/event/event-target.h': 'ca9f9ed1fc9facad0308be0e8e86daada19d8b1715c727f90da8db4e60141e63',
    'StarlingMonkey/builtins/web/abort/abort-signal.h': 'ba8b1ce78deaabf0e86dae56b9eaf79e59e55f179b8a0deda3ef6bed4f8f9b46',
    'StarlingMonkey/builtins/web/event/global-event-target.cpp': 'ed9af74351155434a340f9489395c63a4a609e78bf706e13e6b02a2a7053fe9c',
}


def derive_event_ownership(original: dict[str, bytes], timeout_source: bytes) -> tuple[dict[str, bytes], dict]:
    if set(original) != set(PREIMAGES):
        raise ValueError('exact-pinned-Event-and-Abort-declarations-required')
    for name, expected in PREIMAGES.items():
        if hashlib.sha256(original[name]).hexdigest() != expected:
            raise ValueError('unreviewed-original-Event-source:'+name)
    result = dict(original)
    name = 'StarlingMonkey/builtins/web/event/event-target.h'
    source = replace_once(original[name], b'#include "extension-api.h"\n',
        b'#include "extension-api.h"\n#include "native_objects.h"\n', 'event-owned-declarations')
    source = replace_once(source, b'struct EventListener : public js::RefCounted<EventListener> {\n',
        b'struct EventListener : public js::RefCounted<EventListener> {\n'
        b'  lsf::typescript::activation::NativeObjectLease native_owner;\n'
        b'  explicit EventListener(lsf::typescript::activation::NativeObjectLease&& owner)\n'
        b'      : native_owner(std::move(owner)) {}\n', 'physical-listener-owner-first-member')
    source = replace_once(source,
        b'  using ListenerList = JS::GCVector<ListenerRef, 0, js::SystemAllocPolicy>;\n',
        b'  using ListenerList = JS::GCVector<ListenerRef, 0, js::SystemAllocPolicy>;\n'
        b'  using OwnedListenerList = lsf::typescript::activation::NativeContainer<ListenerList>;\n',
        'physical-listener-list-container')
    result[name] = source

    name = 'StarlingMonkey/builtins/web/event/global-event-target.cpp'
    source = replace_once(original[name],
        b'bool global_event_target_init(JSContext *cx, HandleObject global) {\n'
        b'  RootedObject global_event(cx, EventTarget::create(cx));\n'
        b'  if (!global_event) {\n    return false;\n  }\n\n'
        b'  GLOBAL_EVENT_TARGET.init(cx, global_event);\n',
        b'bool global_event_target_init(JSContext *cx, HandleObject global) {\n'
        b'  // Freeze only the callable globals; mutable graph is activation-local.\n'
        b'  GLOBAL_EVENT_TARGET.init(cx);\n', 'no-global-listener-container-in-shared-snapshot')
    anchor = b'static bool addEventListener(JSContext *cx, unsigned argc, Value *vp) {\n'
    source = replace_once(source, anchor,
        b'static bool ensure_global_event_target(JSContext *cx) {\n'
        b'  if (GLOBAL_EVENT_TARGET) return true;\n'
        b'  RootedObject created(cx, EventTarget::create(cx));\n'
        b'  if (!created) return false;\n'
        b'  GLOBAL_EVENT_TARGET = created;\n'
        b'  return true;\n}\n\n'+anchor, 'lazy-actual-global-listener-graph')
    for before in (
        b'  return EventTarget::add_listener(cx, GLOBAL_EVENT_TARGET, type, callback, opts);',
        b'  return EventTarget::remove_listener(cx, GLOBAL_EVENT_TARGET, type, callback, opts);',
        b'  return EventTarget::dispatch_event(cx, GLOBAL_EVENT_TARGET, event, args.rval());'):
        source = replace_once(source, before,
            b'  if (!ensure_global_event_target(cx)) return false;\n'+before, 'actual-global-operation-lazy-admission')
    result[name] = source

    name = 'StarlingMonkey/builtins/web/abort/abort-signal.h'
    source = replace_once(original[name], b'  AbortAlgorithm() = default;\n',
        b'  lsf::typescript::activation::NativeObjectLease native_owner;\n'
        b'  explicit AbortAlgorithm(lsf::typescript::activation::NativeObjectLease&& owner)\n'
        b'      : native_owner(std::move(owner)) {}\n', 'original-algorithm-owner-before-derived-captures')
    source = replace_once(source, b'  AbortAlgorithm(const AbortAlgorithm &) = default;\n',
                          b'  AbortAlgorithm(const AbortAlgorithm &) = delete;\n', 'no-copied-native-owner')
    source = replace_once(source, b'  AbortAlgorithm &operator=(const AbortAlgorithm &) = default;\n',
                          b'  AbortAlgorithm &operator=(const AbortAlgorithm &) = delete;\n', 'no-copied-native-owner-assignment')
    source = replace_once(source,
        b'  using AlgorithmList = JS::GCVector<js::UniquePtr<AbortAlgorithm>, 0, js::SystemAllocPolicy>;\n',
        b'  using AlgorithmList = JS::GCVector<js::UniquePtr<AbortAlgorithm>, 0, js::SystemAllocPolicy>;\n'
        b'  using OwnedAlgorithmList = lsf::typescript::activation::NativeContainer<AlgorithmList>;\n'
        b'  using OwnedWeakSet = lsf::typescript::activation::NativeContainer<WeakIndexSet>;\n',
        'original-algorithm-and-weak-set-owned-containers')
    result[name] = source

    name = 'StarlingMonkey/builtins/web/event/event-target.cpp'
    source = replace_once(original[name],
        b'  Terminator(JSContext *cx, HandleObject target, HandleValue type, HandleValue callback, HandleValue opts)\n'
        b'      : target(target), type(type), callback(callback), opts(opts) {}',
        b'  Terminator(lsf::typescript::activation::NativeObjectLease&& owner, JSContext *cx,\n'
        b'             HandleObject target, HandleValue type, HandleValue callback, HandleValue opts)\n'
        b'      : AbortAlgorithm(std::move(owner)), target(target), type(type), callback(callback), opts(opts) {}',
        'terminator-admitted-owner')
    source = replace_once(source,
        b'  auto *list = static_cast<ListenerList *>(\n'
        b'      JS::GetReservedSlot(self, static_cast<size_t>(EventTarget::Slots::Listeners)).toPrivate());\n',
        b'  const auto slot = JS::GetReservedSlot(self, static_cast<size_t>(EventTarget::Slots::Listeners));\n'
        b'  if (slot.isNullOrUndefined()) return nullptr;\n'
        b'  auto *owned = static_cast<OwnedListenerList *>(slot.toPrivate());\n'
        b'  auto *list = &owned->value;\n', 'original-list-view-inside-physical-wrapper')
    source = replace_once(source, b'    auto listener = mozilla::MakeRefPtr<EventListener>();\n',
        b'    lsf::typescript::activation::NativeObjectLease accepted;\n'
        b'    if (!lsf::typescript::activation::admit_native_object(cx, accepted)) return false;\n'
        b'    RefPtr<EventListener> listener = js_new<EventListener>(std::move(accepted));\n'
        b'    if (!listener) { JS_ReportOutOfMemory(cx); return false; }\n', 'listener-admit-before-record-allocation')
    source = replace_once(source, b'    list->append(listener);\n',
        b'    if (!list->append(listener)) { JS_ReportOutOfMemory(cx); return false; }\n', 'listener-append-actual-allocation-result')
    source = replace_once(source,
        b'    auto terminator = js::MakeUnique<Terminator>(cx, self, type_val, callback_val, opts_val);\n'
        b'    RootedObject signal(cx, &signal_val.toObject());\n'
        b'    AbortSignal::add_algorithm(signal, std::move(terminator));\n',
        b'    lsf::typescript::activation::NativeObjectLease accepted;\n'
        b'    if (!lsf::typescript::activation::admit_native_object(cx, accepted)) return false;\n'
        b'    auto terminator = js::MakeUnique<Terminator>(\n'
        b'        std::move(accepted), cx, self, type_val, callback_val, opts_val);\n'
        b'    if (!terminator) { JS_ReportOutOfMemory(cx); return false; }\n'
        b'    RootedObject signal(cx, &signal_val.toObject());\n'
        b'    if (!AbortSignal::add_algorithm(signal, std::move(terminator))) return false;\n',
        'abort-listener-terminator-before-capture-allocation')
    # All three original list construction sites use exactly the same wrapper.
    for function, failing in [('create', b'nullptr'), ('init', b'false'), ('constructor', b'false')]:
        start = source.index(b'EventTarget::'+function.encode()+b'(')
        end = source.find(b'\n}\n', start)+3
        body = source[start:end]
        before = b'  auto list = js::MakeUnique<ListenerList>();\n'
        assert body.count(before) == 1
        body = body.replace(before,
            b'  auto list = lsf::typescript::activation::make_native_container<ListenerList>(cx);\n'
            b'  if (!list) return '+failing+b';\n', 1)
        source = source[:start]+body+source[end:]
    source = replace_once(source,
        b'  auto *list = listeners(self);\n  if (list) {\n    js_delete(list);\n  }\n',
        b'  const auto slot = JS::GetReservedSlot(self, std::to_underlying(Slots::Listeners));\n'
        b'  if (!slot.isNullOrUndefined()) {\n'
        b'    delete static_cast<OwnedListenerList *>(slot.toPrivate());\n'
        b'    JS::SetReservedSlot(self, std::to_underlying(Slots::Listeners), JS::UndefinedValue());\n'
        b'  }\n', 'physical-listener-vector-destruction-before-safe-ack')
    result[name] = source

    name = 'StarlingMonkey/builtins/web/abort/abort-signal.cpp'
    source = timeout_source
    for typename in ('AlgorithmList', 'WeakIndexSet'):
        if typename == 'AlgorithmList':
            source = replace_once(source,
                b'  return static_cast<AlgorithmList *>(JS::GetReservedSlot(self, std::to_underlying(Slots::Algorithms)).toPrivate());',
                b'  return &static_cast<OwnedAlgorithmList *>(JS::GetReservedSlot(self, std::to_underlying(Slots::Algorithms)).toPrivate())->value;',
                'owned-algorithm-original-vector-view')
        else:
            source = replace_once(source,
                b'  return static_cast<WeakIndexSet *>(JS::GetReservedSlot(self, std::to_underlying(Slots::SourceSignals)).toPrivate());',
                b'  return &static_cast<OwnedWeakSet *>(JS::GetReservedSlot(self, std::to_underlying(Slots::SourceSignals)).toPrivate())->value;',
                'owned-source-weak-set-original-view')
            source = replace_once(source,
                b'  return static_cast<WeakIndexSet *>(\n      JS::GetReservedSlot(self, std::to_underlying(Slots::DependentSignals)).toPrivate());',
                b'  return &static_cast<OwnedWeakSet *>(\n      JS::GetReservedSlot(self, std::to_underlying(Slots::DependentSignals)).toPrivate())->value;',
                'owned-dependent-weak-set-original-view')
    # Allocate every charged native container before attaching any pointer to
    # the JS graph. Partial failures destroy exact previous wrappers by RAII.
    anchor = b'  // An AbortSignal object has an associated abort reason, which is initially undefined.\n'
    source = replace_once(source, anchor,
        b'  auto algorithms = lsf::typescript::activation::make_native_container<AlgorithmList>(cx);\n'
        b'  if (!algorithms) return nullptr;\n'
        b'  auto sources = lsf::typescript::activation::make_native_container<WeakIndexSet>(cx);\n'
        b'  if (!sources) return nullptr;\n'
        b'  auto dependents = lsf::typescript::activation::make_native_container<WeakIndexSet>(cx);\n'
        b'  if (!dependents) return nullptr;\n'+anchor, 'all-abort-containers-before-graph-publication')
    for old,new,label in [
        (b'JS::PrivateValue(new AlgorithmList)',b'JS::PrivateValue(algorithms.release())','owned-algorithm-publication'),
        (b'JS::PrivateValue(new WeakIndexSet)',b'JS::PrivateValue(sources.release())','owned-source-set-publication')]:
        if old==b'JS::PrivateValue(new WeakIndexSet)':
            assert source.count(old)==2
            source=source.replace(old,new,1).replace(old,b'JS::PrivateValue(dependents.release())',1)
        else: source=replace_once(source,old,new,label)
    # Both weak-link sides report their actual allocation failures. The graph
    # stays attached to its exact owners until GC physically destroys it.
    for before in (b'      our_signals->insert(signal);', b'      their_signals->insert(self);',
                   b'        our_signals->insert(source);', b'        their_signals->insert(self);'):
        indentation = before[:len(before)-len(before.lstrip())]
        operation = before.strip().removesuffix(b';')
        source = replace_once(source, b'\n'+before+b'\n',
            b'\n'+indentation+b'if (!'+operation+b') { JS_ReportOutOfMemory(cx); return nullptr; }\n',
            'checked-original-weak-graph-allocation')
    source = replace_once(source,
        b'  EventTarget::finalize(gcx, self);\n',
        b'  // Destructors never invoke the activation host while GC is running.\n'
        b'  for (auto slot : {Slots::Algorithms, Slots::SourceSignals, Slots::DependentSignals}) {\n'
        b'    const auto value = JS::GetReservedSlot(self, std::to_underlying(slot));\n'
        b'    if (value.isNullOrUndefined()) continue;\n'
        b'    if (slot == Slots::Algorithms) delete static_cast<OwnedAlgorithmList *>(value.toPrivate());\n'
        b'    else delete static_cast<OwnedWeakSet *>(value.toPrivate());\n'
        b'    JS::SetReservedSlot(self, std::to_underlying(slot), JS::UndefinedValue());\n'
        b'  }\n'
        b'  EventTarget::finalize(gcx, self);\n', 'actual-three-abort-container-destructions')
    result[name] = source
    return result, {'format':'latent.typescript.event-native-source-derivation.v1',
        'starlingCommit':STARLING_COMMIT,'originalSource':identity(original),
        'checkedTimeoutSourceSha256':hashlib.sha256(timeout_source).hexdigest(),
        'derivedSource':identity(result),'nativeGraphAdmission':'before-physical-allocation',
        'nativeGraphRetirement':'destructor-then-collection-end-then-safe-host-ack',
        'hostImportsDuringGC':False,'originalAPIAndListenerAlgorithmsRetained':True,
        'snapshotMutableGraphs':'denied','supportedAsyncProfile':False,'signedLSFComponentQualified':False}
