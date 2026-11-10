"""Pinned Abort/Event physical graph ownership, independent of API qualification."""
from __future__ import annotations
import hashlib
from tools.typescript_guest.activation_engine import identity, replace_once, STARLING_COMMIT

FETCH_SOURCE_SHA256 = '0992832f377bd45986e79447f463f1de2ff609f32d53723e0ef04de2c7178cf2'

PREIMAGES = {
    'StarlingMonkey/builtins/web/event/event-target.cpp': '0b22572ccb4de19fb1476073d0586d1afe03c856454a466d0d2c6607ace20ffd',
    'StarlingMonkey/builtins/web/event/event-target.h': 'ca9f9ed1fc9facad0308be0e8e86daada19d8b1715c727f90da8db4e60141e63',
    'StarlingMonkey/builtins/web/abort/abort-signal.h': 'ba8b1ce78deaabf0e86dae56b9eaf79e59e55f179b8a0deda3ef6bed4f8f9b46',
    'StarlingMonkey/builtins/web/event/global-event-target.cpp': 'ed9af74351155434a340f9489395c63a4a609e78bf706e13e6b02a2a7053fe9c',
    'StarlingMonkey/builtins/web/fetch/fetch-api.cpp': FETCH_SOURCE_SHA256,
    'StarlingMonkey/builtins/web/fetch/request-response.cpp': 'eefae62cdbc31616df620d2d788ba3d27ccbeaf47a58fb53b04aefc08fff05b5',
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
    source = replace_once(source,
        b'class EventTarget : public BuiltinImpl<EventTarget, TraceableClassPolicy> {\n',
        b'class EventTarget : public BuiltinImpl<EventTarget, TraceableClassPolicy> {\n'
        b'  friend struct Terminator; // removes the exact admitted record without JS conversion\n',
        'abort-terminator-private-list-access')
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
    original_terminator_start = original[name].index(b'struct Terminator : AbortAlgorithm {')
    original_terminator_end = original[name].index(b'\n};', original_terminator_start) + len(b'\n};')
    source = replace_once(original[name], original[name][original_terminator_start:original_terminator_end],
        b'''struct Terminator : AbortAlgorithm {
  Heap<JSObject *> target;
  // A strong native reference prevents ABA reuse after remove/re-add. The
  // listener's own lease stays live until this reference is physically gone.
  RefPtr<EventListener> listener;

  Terminator(lsf::typescript::activation::NativeObjectLease&& owner,
             HandleObject target, const RefPtr<EventListener>& listener)
      : AbortAlgorithm(std::move(owner)), target(target), listener(listener) {}

  bool run(JSContext *cx) override {
    // DOM abort steps capture the listener record, not mutable WebIDL inputs.
    // No ToString, option getter, allocation, or callback can run during removal.
    RootedObject self(cx, target);
    auto *list = EventTarget::listeners(self);
    listener->removed = true;
    for (auto it = list->begin(); it != list->end(); ++it) {
      if (it->get() == listener.get()) {
        list->erase(it);
        break;
      }
    }
    return true;
  }

  void trace(JSTracer *trc) override {
    JS::TraceEdge(trc, &target, "EventTarget Terminator target");
    listener->trace(trc);
  }
};''', 'abort-terminator-captures-exact-physical-listener')
    source = replace_once(source,
        b'  auto *list = static_cast<ListenerList *>(\n'
        b'      JS::GetReservedSlot(self, static_cast<size_t>(EventTarget::Slots::Listeners)).toPrivate());\n',
        b'  const auto slot = JS::GetReservedSlot(self, static_cast<size_t>(EventTarget::Slots::Listeners));\n'
        b'  if (slot.isNullOrUndefined()) return nullptr;\n'
        b'  auto *owned = static_cast<OwnedListenerList *>(slot.toPrivate());\n'
        b'  auto *list = &owned->value;\n', 'original-list-view-inside-physical-wrapper')
    source = replace_once(source,
        b'''  if (it == list->end()) {
    auto listener = mozilla::MakeRefPtr<EventListener>();
    listener->callback = callback_val;
    listener->signal = signal_val;
    listener->type = type;
    listener->passive = passive;
    listener->capture = capture;
    listener->once = once;
    listener->removed = false;

    list->append(listener);
  } else if((*it)->removed) {
    // if existing listener was marked for removal, then move it to the end of the list
    // and update its removed flag. This is done to ensure the order of listeners. We only
    // update listener's properties that are not check for listener equality.
    (*it)->signal = signal_val;
    (*it)->passive = passive;
    (*it)->once = once;
    (*it)->removed = false;

    list->erase(it);
    list->append(*it);
  }

  // - If listener's signal is not null, then add the following abort steps to it:
  //  Remove an event listener with eventTarget and listener.
  if (signal_val.isObject() && AbortSignal::is_instance(signal_val)) {
    auto terminator = js::MakeUnique<Terminator>(cx, self, type_val, callback_val, opts_val);
    RootedObject signal(cx, &signal_val.toObject());
    AbortSignal::add_algorithm(signal, std::move(terminator));
  }
''',
        b'''  // Duplicate active registrations do not adopt a new signal or an abort
  // algorithm. Removed records may still be in a dispatch snapshot: never
  // reactivate their identity or let an old signal remove their replacement.
  if (it != list->end() && !(*it)->removed) return true;
  if (signal_val.isObject() && AbortSignal::is_instance(signal_val)) {
    RootedObject signal(cx, &signal_val.toObject());
    // Converting the event type may have run script after the earlier check.
    if (AbortSignal::is_aborted(signal)) return true;
  }
  const bool replacing_removed = it != list->end();
  lsf::typescript::activation::NativeObjectLease listener_owner;
  if (!lsf::typescript::activation::admit_native_object(cx, listener_owner)) return false;
  RefPtr<EventListener> staged = js_new<EventListener>(std::move(listener_owner));
  if (!staged) { JS_ReportOutOfMemory(cx); return false; }
  staged->type = type;
  staged->passive = passive;
  staged->capture = capture;
  staged->once = once;
  staged->removed = false;
  // No fallible listener-vector growth can follow abort registration. reserve
  // can invalidate `it`, so retain only the index of an old removed record.
  const size_t removed_index = replacing_removed ? size_t(it - list->begin()) : 0;
  if (!list->reserve(list->length() + (replacing_removed ? 0 : 1))) {
    JS_ReportOutOfMemory(cx);
    return false;
  }

  if (signal_val.isObject() && AbortSignal::is_instance(signal_val)) {
    RootedObject signal(cx, &signal_val.toObject());
    lsf::typescript::activation::NativeObjectLease accepted;
    if (!lsf::typescript::activation::admit_native_object(cx, accepted)) return false;
    auto terminator = js::MakeUnique<Terminator>(std::move(accepted), self, staged);
    if (!terminator) { JS_ReportOutOfMemory(cx); return false; }
    if (!AbortSignal::add_algorithm(signal, std::move(terminator))) {
      JS_ReportOutOfMemory(cx);
      return false;
    }
  }

  // All fallible admission and allocation has succeeded. The old record remains
  // removed in any active dispatch clone or old signal's abort algorithm.
  // Heap edges are initialized only after admission, with inputs still rooted.
  staged->callback = callback_val;
  staged->signal = signal_val;
  if (replacing_removed) list->erase(list->begin() + removed_index);
  list->infallibleAppend(staged);
''', 'listener-and-abort-publication-after-admission')
    source = replace_once(source,
        b'  auto *list = listeners(target);\n'
        b'  JS::RootedVector<ListenerRef> list_clone(cx);\n'
        b'  if (!list_clone.reserve(list->length())) {\n',
        b'  auto *list = listeners(target);\n'
        b'  // The owner outlives the rooted vector and its backing allocation.\n'
        b'  lsf::typescript::activation::NativeObjectFrameLease clone_owner;\n'
        b'  JS::RootedVector<ListenerRef> list_clone(cx);\n'
        b'  if (list->length() > list_clone.capacity() &&\n'
        b'      !lsf::typescript::activation::admit_native_object(cx, clone_owner.lease())) return false;\n'
        b'  if (!list_clone.reserve(list->length())) {\n', 'dispatch-clone-owner-before-vector-growth')
    source = replace_once(source,
        b'    if (Event::has_flag(event, EventFlag::StopImmediatePropagation)) {\n'
        b'      return true;\n'
        b'    }\n',
        b'    if (Event::has_flag(event, EventFlag::StopImmediatePropagation)) {\n'
        b'      break; // remove already-fired once listeners before returning\n'
        b'    }\n', 'finish-once-listener-retirement-after-immediate-stop')
    source = replace_once(source, b'  bool listeners_removed = false;\n',
        b'  bool listeners_removed = false;\n  bool invocation_failed = false;\n',
        'retain-once-listener-cleanup-on-callback-lookup-error')
    source = replace_once(source,
        b'      if (!JS_GetProperty(cx, callback_obj, "handleEvent", &handle_fn)) {\n'
        b'        return false;\n'
        b'      }\n',
        b'      if (!JS_GetProperty(cx, callback_obj, "handleEvent", &handle_fn)) {\n'
        b'        Event::set_flag(event, Event::EventFlag::InPassiveListener, false);\n'
        b'        invocation_failed = true;\n'
        b'        break;\n'
        b'      }\n', 'finish-once-listener-retirement-after-callback-lookup-error')
    source = replace_once(source,
        b'                               JS::HandleVector<ListenerRef> list, bool *found) {\n',
        b'                               JS::HandleVector<ListenerRef> list, bool *found) {\n'
        b'  if (JS_IsExceptionPending(cx)) return false;\n',
        'listener-invocation-rejects-preexisting-pending-failure')
    source = replace_once(source,
        b'    if (JS::IsCallable(callback_obj)) {\n',
        b'    bool called = false;\n'
        b'    if (JS::IsCallable(callback_obj)) {\n', 'retain-native-callback-outcome')
    for call in (b'JS::Call(cx, global, callback_val, args, &rval)',
                 b'JS::Call(cx, callback_val, handle_fn, args, &rval)'):
        source = replace_once(source, b'      '+call+b';\n',
            b'      called = '+call+b';\n', 'check-each-native-callback-outcome')
    source = replace_once(source,
        b'      if (!JS_GetProperty(cx, callback_obj, "handleEvent", &handle_fn)) {\n',
        b'      if (!JS_GetProperty(cx, callback_obj, "handleEvent", &handle_fn) ||\n'
        b'          JS_IsExceptionPending(cx)) {\n', 'callback-lookup-cannot-hide-pending-failure')
    source = replace_once(source, b'    if (JS_IsExceptionPending(cx)) {\n',
        b'    // Catchable listener exceptions retain ordinary DOM reporting below.\n'
        b'    // A false/no-pending native termination is not a listener exception: it\n'
        b'    // must fence later callbacks, including independent abort dependents.\n'
        b'    if (!called && !JS_IsExceptionPending(cx)) {\n'
        b'      Event::set_flag(event, Event::EventFlag::InPassiveListener, false);\n'
        b'      invocation_failed = true;\n'
        b'      break;\n'
        b'    }\n\n'
        b'    if (JS_IsExceptionPending(cx)) {\n', 'uncatchable-listener-failure-fences-dispatch')
    source = replace_once(source, b'  return true;\n}\n\nJSObject *EventTarget::create(',
        b'  return !invocation_failed;\n}\n\nJSObject *EventTarget::create(',
        'preserve-callback-lookup-failure-after-retirement')
    source = replace_once(source,
        b'  if (!invoke_listeners(cx, target, event)) {\n    return false;\n  }\n',
        b'  const bool invoked = invoke_listeners(cx, target, event);\n',
        'restore-dispatch-state-after-listener-error')
    source = replace_once(source,
        b'  rval.setBoolean(!Event::has_flag(event, EventFlag::Canceled));\n',
        b'  if (!invoked || JS_IsExceptionPending(cx)) return false; // preserve the original failure\n'
        b'  rval.setBoolean(!Event::has_flag(event, EventFlag::Canceled));\n',
        'return-original-listener-error-after-dispatch-cleanup')
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

    # The pinned carrier has two more AbortAlgorithm subclasses in fetch.
    # Every derived allocation transfers an admitted lease into the base;
    # adding an uncharged default constructor would hide missing ownership.
    name = 'StarlingMonkey/builtins/web/fetch/fetch-api.cpp'
    source = replace_once(original[name],
        b'  Terminator(const mozilla::WeakPtr<ResponseFutureTask>& task) : task(task) {}',
        b'  Terminator(lsf::typescript::activation::NativeObjectLease&& owner,\n'
        b'             const mozilla::WeakPtr<ResponseFutureTask>& task)\n'
        b'      : AbortAlgorithm(std::move(owner)), task(task) {}', 'fetch-terminator-owned-base')
    source = replace_once(source,
        b'                 HostString method, HostString url) {\n',
        b'                 HostString method, HostString url) {\n'
        b'  lsf::typescript::activation::NativeObjectLease abort_owner;\n'
        b'  if (!lsf::typescript::activation::admit_native_object(cx, abort_owner)) return false;\n',
        'fetch-abort-owner-before-request-and-send')
    source = replace_once(source,
        b'    AbortSignal::add_algorithm(signal, js::MakeUnique<Terminator>(weak));\n',
        b'    auto algorithm = js::MakeUnique<Terminator>(std::move(abort_owner), weak);\n'
        b'    if (!algorithm) { JS_ReportOutOfMemory(cx); return false; }\n'
        b'    if (!AbortSignal::add_algorithm(signal, std::move(algorithm))) return false;\n',
        'fetch-terminator-allocation-and-publication-results')
    publication = (b'  SetReservedSlot(request_obj, static_cast<uint32_t>(Request::Slots::ResponsePromise),\n'
                   b'                  ObjectValue(*response_promise));\n'
                   b'  SetReservedSlot(request_obj, static_cast<uint32_t>(Request::Slots::PendingResponseHandle),\n'
                   b'                  PrivateValue(pending_handle));\n')
    source = replace_once(source, publication, b'', 'fetch-original-task-context-publication')
    anchor = b'  // If the request body is streamed, we need to wait for streaming to complete\n'
    source = replace_once(source, anchor, publication+b'\n'+anchor,
        'fetch-task-context-before-accepted-work-and-fallible-abort-allocation')
    result[name] = source

    name = 'StarlingMonkey/builtins/web/fetch/request-response.cpp'
    source = replace_once(original[name],
        b'  ResponseAborter(HandleObject promise, HandleObject response, HandleObject signal)\n'
        b'      : promise(promise), response(response), signal(signal) {}',
        b'  ResponseAborter(lsf::typescript::activation::NativeObjectLease&& owner,\n'
        b'                  HandleObject promise, HandleObject response, HandleObject signal)\n'
        b'      : abort::AbortAlgorithm(std::move(owner)), promise(promise), response(response), signal(signal) {}',
        'response-aborter-owned-base')
    source = replace_once(source,
        b'  RootedObject response_promise(cx, Request::response_promise(request));\n\n'
        b'  auto res = future_->maybe_response();',
        b'  RootedObject response_promise(cx, Request::response_promise(request));\n'
        b'  RootedObject signal(cx, Request::signal(request));\n'
        b'  lsf::typescript::activation::NativeObjectLease abort_owner;\n'
        b'  if (AbortSignal::is_instance(signal) &&\n'
        b'      !lsf::typescript::activation::admit_native_object(cx, abort_owner)) return false;\n\n'
        b'  auto res = future_->maybe_response();', 'response-abort-owner-before-future-result')
    source = replace_once(source,
        b'  RootedObject signal(cx, Request::signal(request));\n'
        b'  if (AbortSignal::is_instance(signal)) {\n'
        b'    auto algorithm = js::MakeUnique<ResponseAborter>(response_promise, response_obj, signal);\n'
        b'    AbortSignal::add_algorithm(signal, std::move(algorithm));\n',
        b'  if (AbortSignal::is_instance(signal)) {\n'
        b'    auto algorithm = js::MakeUnique<ResponseAborter>(\n'
        b'        std::move(abort_owner), response_promise, response_obj, signal);\n'
        b'    if (!algorithm) { JS_ReportOutOfMemory(cx); return false; }\n'
        b'    if (!AbortSignal::add_algorithm(signal, std::move(algorithm))) return false;\n',
        'response-aborter-allocation-and-publication-results')
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
        'dispatchCloneAdmission':'before-backing-vector-growth',
        'dispatchCloneRetirement':'frame-destructor-then-safe-host-ack',
        'dispatchCloneOwner':'one-original-native-count-not-byte-accurate',
        'uncatchableListenerFailure':'cleanup-then-fence-dispatch-and-abort-dependents',
        'catchableListenerException':'original-DOM-reporting-retained',
        'hostImportsDuringGC':False,
        'abortListenerIdentity': 'exact-record-not-reconverted-type-callback-or-options',
        'abortListenerCustody': 'strong-native-ref-retains-original-listener-lease-until-destruction',
        'duplicateListenerSignal': 'ignored-without-new-native-admission',
        'removedListenerReregistration': 'fresh-identity-without-reactivating-dispatch-snapshot',
        'originalPublicAPISurfaceRetained':True,
        'snapshotMutableGraphs':'denied','supportedAsyncProfile':False,'signedLSFComponentQualified':False}
