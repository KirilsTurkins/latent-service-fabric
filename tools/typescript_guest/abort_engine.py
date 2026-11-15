"""Pinned ordinary AbortSignal timeout over the selected native timer backend."""
from __future__ import annotations
import hashlib
from tools.typescript_guest.activation_engine import identity, replace_once, STARLING_COMMIT

PREIMAGE = '1a732263119c393d59953ccb254cc9ebedc99bd9bbd98ba8e231422cb8cff088'
PATH = 'StarlingMonkey/builtins/web/abort/abort-signal.cpp'


def derive_abort_timeout(raw: bytes) -> tuple[bytes, dict]:
    if hashlib.sha256(raw).hexdigest() != PREIMAGE:
        raise ValueError('unreviewed-original-AbortSignal-source')
    source = replace_once(raw, b'#include "../timers.h"\n',
        b'#include "../timers.h"\n#include "native_timeout.h"\n#include "native_engine.h"\n'
        b'#include "native_objects.h"\n'
        b'#include "js/ForOfIterator.h"\n#include "js/Exception.h"\n'
        b'#include "mozilla/Maybe.h"\n#include <utility>\n', 'abort-native-include')
    source = replace_once(source,
        b'    JS_SetPendingException(cx, reason);\n  }\n\n  return true;\n}',
        b'    JS_SetPendingException(cx, reason);\n    return false;\n  }\n\n  return true;\n}',
        'throw-original-abort-reason-with-failed-native-return')
    source = replace_once(source,
        b'  if (!args.requireAtLeast(cx, "abort", 1)) {\n    return false;\n  }\n\n',
        b'', 'optional-static-abort-reason')
    source = replace_once(source,
        b'  RootedObject self(cx, create_with_signals(cx, args));\n',
        b'''  JS::ForOfIterator iterator(cx);
  if (!iterator.init(args.get(0))) return false;
  // The vector must be destroyed before its frame's original native owner.
  lsf::typescript::activation::NativeObjectFrameLease signals_owner;
  JS::RootedValueVector signals(cx);
  bool signals_owned = false;
  while (true) {
    JS::RootedValue value(cx);
    bool done = false;
    if (!iterator.next(&value, &done)) return false;
    if (done) break;
    if (!value.isObject() || !is_instance(&value.toObject())) {
      api::throw_error(cx, api::Errors::TypeError, "AbortSignal.any", "signals",
                       "contain only AbortSignal objects");
      iterator.closeThrow();
      return false;
    }
    if (!signals_owned && signals.length() == signals.capacity()) {
      if (!lsf::typescript::activation::admit_native_object(cx, signals_owner.lease())) {
        iterator.closeThrow();
        return false;
      }
      signals_owned = true;
    }
    if (!signals.append(value)) { JS_ReportOutOfMemory(cx); iterator.closeThrow(); return false; }
  }
  RootedObject self(cx, create_with_signals(cx, JS::HandleValueArray(signals)));
''', 'standard-any-sequence-conversion-before-signal-allocation')
    source = replace_once(source,
        b'''  // 1. Let signal be a new AbortSignal object.
  RootedObject self(cx, create(cx));
  if (!self) {
    return nullptr;
  }

  double ms = 0;
  if (!JS::ToNumber(cx, timeout, &ms)) {
    return nullptr;
  }
''',
        b'''  // Convert before allocating the signal graph or admitting a timer.
  // Native result/capture storage is then reserved by the same timer backend.
  uint64_t nanos = 0;
  if (!lsf::typescript::activation::timeout_nanoseconds(cx, timeout, &nanos))
    return nullptr;
  RootedObject self(cx, create(cx));
  if (!self) return nullptr;
''', 'checked-timeout-before-signal-allocation')
    source = replace_once(source,
        b'  if (!timers::set_timeout(cx, handler, args, ms, &timer_id)) {',
        b'  if (!lsf::typescript::activation::start_timeout_nanoseconds(\n'
        b'          cx, handler, JS::HandleValueArray(args), nanos, &timer_id)) {',
        'actual-AbortSignal-native-timer-readiness')
    handler_start = raw.index(b'bool AbortSignal::onabort_set(')
    handler_end = raw.index(b'// https://dom.spec.whatwg.org/#dom-abortsignal-timeout', handler_start)
    source = replace_once(source, raw[handler_start:handler_end],
        b'''// Property handlers have their own stable listener, distinct from a callback
// registered through addEventListener. Replacing the value must not reorder it.
bool AbortSignal::onabort_invoke(JSContext *cx, unsigned argc, JS::Value *vp) {
  METHOD_HEADER(1);
  if (JS_IsExceptionPending(cx)) return false;
  RootedValue callback(cx, JS::GetReservedSlot(self, std::to_underlying(Slots::OnAbort)));
  // Web IDL LegacyTreatNonObjectAsNull retains non-callable objects but invokes
  // them as a no-op; it must not look up a handleEvent property on those objects.
  if (!callback.isObject() || !JS::IsCallable(&callback.toObject())) {
    args.rval().setUndefined();
    return true;
  }
  JS::RootedValueArray<1> event_args(cx);
  event_args[0].set(args.get(0));
  RootedValue result(cx);
  if (!JS::Call(cx, self, callback, event_args, &result) || JS_IsExceptionPending(cx)) return false;
  if (result.isBoolean() && !result.toBoolean()) {
    RootedObject event(cx, &event_args[0].toObject());
    Event::set_canceled(event, true);
  }
  args.rval().setUndefined();
  return true;
}

bool AbortSignal::onabort_set(JSContext *cx, unsigned argc, JS::Value *vp) {
  METHOD_HEADER(1);
  if (JS_IsExceptionPending(cx)) return false;
  RootedValue callback(cx, args.get(0));
  if (!callback.isObject()) callback.setNull();
  RootedValue listener(cx, JS::GetReservedSlot(self, std::to_underlying(Slots::OnAbortListener)));
  RootedValue type(cx, JS::StringValue(abort_type_atom));
  RootedValue opts(cx, JS::FalseValue());
  if (callback.isNull()) {
    if (listener.isObject() &&
        (!EventTarget::remove_listener(cx, self, type, listener, opts) || JS_IsExceptionPending(cx)))
      return false;
    listener.setNull();
  } else if (!listener.isObject()) {
    JS::RootedFunction handler(cx, JS_NewFunction(cx, onabort_invoke, 1, 0, nullptr));
    if (!handler || JS_IsExceptionPending(cx)) return false;
    listener.setObject(*JS_GetFunctionObject(handler));
    if (!EventTarget::add_listener(cx, self, type, listener, opts) || JS_IsExceptionPending(cx))
      return false;
  }
  // Admissions/allocations succeeded. No script runs between listener mutation
  // and these slot writes; failed installation cannot replace the old value.
  JS::SetReservedSlot(self, std::to_underlying(Slots::OnAbort), callback);
  JS::SetReservedSlot(self, std::to_underlying(Slots::OnAbortListener), listener);
  args.rval().setUndefined();
  return true;
}

''', 'stable-property-abort-listener-and-transactional-handler-value')
    source = replace_once(source,
        b'  SetReservedSlot(self, std::to_underlying(Slots::OnAbort), JS::NullValue());\n',
        b'  SetReservedSlot(self, std::to_underlying(Slots::OnAbort), JS::NullValue());\n'
        b'  SetReservedSlot(self, std::to_underlying(Slots::OnAbortListener), JS::NullValue());\n',
        'initialize-distinct-property-handler-listener-slot')
    abort_start = raw.index(b'bool AbortSignal::abort(JSContext *cx, HandleObject self, HandleValue reason) {')
    abort_end = raw.index(b'// https://dom.spec.whatwg.org/#run-the-abort-steps', abort_start)
    source = replace_once(source, raw[abort_start:abort_end],
        b'''// The pinned DOMException::create dereferences unchecked string/constructor
// results and writes slots on an unchecked constructor result. Keep its observable
// constructor lookup/reentry, but guard every failure and native-class boundary.
static JSObject *create_abort_exception(JSContext *cx, const char *name) {
  using Exception = dom_exception::DOMException;
  if (JS_IsExceptionPending(cx)) return nullptr;
  RootedString text(cx, JS_NewStringCopyZ(cx, name));
  // A rooted string result is not permission to look up a mutable constructor
  // with a pending exception. Preserve the failure before any possible reentry.
  if (!text || JS_IsExceptionPending(cx)) return nullptr;
  JS::RootedValueArray<2> args(cx);
  args[0].setString(text);
  args[1].setString(text);
  RootedObject constructor(cx, JS_GetConstructor(cx, Exception::proto_obj));
  if (!constructor || JS_IsExceptionPending(cx)) return nullptr;
  RootedValue ctor(cx, JS::ObjectValue(*constructor));
  RootedObject exception(cx);
  if (!JS::Construct(cx, ctor, args, &exception) || JS_IsExceptionPending(cx)) return nullptr;
  if (!Exception::is_instance(exception)) {
    api::throw_error(cx, api::Errors::TypeError, "AbortSignal", "DOMException constructor",
                     "return a DOMException");
    return nullptr;
  }
  // No further allocation or user code between class validation and slot writes.
  JS::SetReservedSlot(exception, static_cast<size_t>(Exception::Slots::Message), args[0]);
  JS::SetReservedSlot(exception, static_cast<size_t>(Exception::Slots::Name), args[1]);
  return exception;
}

bool AbortSignal::abort(JSContext *cx, HandleObject self, HandleValue reason) {
  MOZ_ASSERT(is_instance(self));
  // Never convert a pre-existing failure into a successful no-op.
  if (JS_IsExceptionPending(cx)) return false;
  if (is_aborted(self)) return true;

  // Default-error construction can re-enter JS through the pinned factory.
  // Do not overwrite a nested abort, repeat its steps, or keep weak iterators
  // across that construction. The eventual reason remains rooted throughout.
  RootedValue propagated_reason(cx, reason);
  if (propagated_reason.isUndefined()) {
    RootedObject exception(cx, create_abort_exception(cx, "AbortError"));
    if (!exception || JS_IsExceptionPending(cx)) return false;
    propagated_reason.setObject(*exception);
    if (is_aborted(self)) return true;
  }

  // Stage the entire fan-out before publishing any abort reason. Admission and
  // reservation cannot leave an aborted signal whose steps were never run.
  // Declare custody first so the rooted vector and backing die before its owner.
  lsf::typescript::activation::NativeObjectFrameLease dependents_owner;
  JS::RootedObjectVector dep_signals_to_abort(cx);
  auto *dep_signals = dependent_signals(self);
  size_t pending_dependents = 0;
  for (auto const &sig : dep_signals->items()) {
    if (!is_aborted(sig)) ++pending_dependents;
  }
  if (pending_dependents > dep_signals_to_abort.capacity()) {
    if (!lsf::typescript::activation::admit_native_object(cx, dependents_owner.lease())) return false;
    if (!dep_signals_to_abort.reserve(pending_dependents)) {
      JS_ReportOutOfMemory(cx);
      return false;
    }
  }
  for (auto const &sig : dep_signals->items()) {
    RootedObject signal(cx, sig);
    if (!is_aborted(signal)) dep_signals_to_abort.infallibleAppend(signal);
  }

  // The normalized reason is non-undefined: these slot writes cannot allocate
  // or execute JS. Every dependent is already aborted when the root steps run.
  if (!set_reason(cx, self, propagated_reason)) return false;
  for (auto &sig : dep_signals_to_abort) {
    RootedObject signal(cx, sig);
    if (!set_reason(cx, signal, propagated_reason)) return false;
  }

  // Finish accepted dependent work without running JS with a pending exception.
  // Keep the first catchable failure and its original stack in one rooted frame.
  // An uncatchable failure fences further work and must not be hidden by it.
  // AutoSaveExceptionState owns a RootedObject for the exception stack. Its
  // roots must be popped before this reusable signal root (strict JSAPI LIFO).
  // Do not emplace it inside the lifetime of a per-iteration RootedObject.
  RootedObject current_signal(cx);
  mozilla::Maybe<JS::AutoSaveExceptionState> first_failure;
  auto run_steps = [&](HandleObject signal) {
    const bool succeeded = run_abort_steps(cx, signal);
    if (succeeded && !JS_IsExceptionPending(cx)) return true;
    if (!JS_IsExceptionPending(cx)) {
      if (first_failure) first_failure->drop();
      return false;
    }
    if (!first_failure) first_failure.emplace(cx);
    else JS_ClearPendingException(cx);
    return true;
  };
  if (!run_steps(self)) return false;
  for (auto &sig : dep_signals_to_abort) {
    current_signal.set(sig);
    if (!run_steps(current_signal)) return false;
  }
  if (first_failure) {
    first_failure->restore();
    return false;
  }
  return true;
}

''', 'admitted-fanout-before-abort-publication-and-preserved-first-failure')
    # The same guarded factory covers static abort() and the timeout reason.
    for name in ('AbortError', 'TimeoutError'):
        source = replace_once(source,
            ('dom_exception::DOMException::create(cx, "'+name+'", "'+name+'")').encode(),
            ('create_abort_exception(cx, "'+name+'")').encode(),
            'guarded-original-'+name+'-construction')
    steps_start = raw.index(b'bool AbortSignal::run_abort_steps(')
    steps_end = raw.index(b"// Set signal's abort reason to reason if it is given;", steps_start)
    source = replace_once(source, raw[steps_start:steps_end],
        b'''bool AbortSignal::run_abort_steps(JSContext *cx, HandleObject self) {
  if (JS_IsExceptionPending(cx)) return false;
  // Every persistent root precedes the lazily engaged exception-state roots.
  // A later event allocation must not pop roots below the saved first failure.
  RootedValue res_val(cx);
  RootedValue type_val(cx, JS::StringValue(abort_type_atom));
  RootedObject event(cx);
  RootedValue event_val(cx);
  mozilla::Maybe<JS::AutoSaveExceptionState> first_failure;
  auto remember_failure = [&](bool ok) {
    if (ok && !JS_IsExceptionPending(cx)) return true;
    if (!JS_IsExceptionPending(cx)) {
      if (first_failure) first_failure->drop();
      return false; // native termination fences all remaining work
    }
    if (!first_failure) first_failure.emplace(cx);
    else JS_ClearPendingException(cx);
    return true;
  };
  auto finish = [&]() {
    if (first_failure) { first_failure->restore(); return false; }
    return !JS_IsExceptionPending(cx);
  };

  auto *algorithms = AbortSignal::algorithms(self);
  size_t completed = 0;
  for (size_t next = 0; next < algorithms->length(); ++next) {
    const bool ok = (*algorithms)[next]->run(cx);
    if (ok && !JS_IsExceptionPending(cx)) {
      // Compact completed records into a prefix without allocating another
      // vector, exposing null trace entries, or destroying any capture while
      // later algorithms execute. Keep failed records in original order.
      for (size_t index = next; index > completed; --index)
        std::swap((*algorithms)[index], (*algorithms)[index - 1]);
      ++completed;
    } else if (!remember_failure(ok)) {
      if (completed) algorithms->erase(algorithms->begin(), algorithms->begin() + completed);
      return false;
    }
  }
  // Only completed algorithms are physically destroyed. Failed records may
  // still capture accepted work; retain their original leases and GC edges.
  if (completed) algorithms->erase(algorithms->begin(), algorithms->begin() + completed);

  event = Event::create(cx, type_val, JS::NullHandleValue);
  if (!event || JS_IsExceptionPending(cx)) {
    if (!remember_failure(false)) return false;
    return finish();
  }
  event_val.setObject(*event);
  if (!remember_failure(EventTarget::dispatch_event(cx, self, event_val, &res_val))) return false;
  return finish();
}

''', 'drain-independent-algorithms-retain-failures-and-restore-first-exception')
    any_start = raw.index(b'JSObject *AbortSignal::create_with_signals(')
    any_end = raw.index(b'bool AbortSignal::constructor(', any_start)
    source = replace_once(source, raw[any_start:any_end],
        b'''JSObject *AbortSignal::create_with_signals(JSContext *cx, HandleValueArray signals) {
  if (JS_IsExceptionPending(cx)) return nullptr;
  RootedObject self(cx, create(cx));
  if (!self || JS_IsExceptionPending(cx)) return nullptr;

  // Already-aborted inputs select the first reason without touching any source.
  for (size_t i = 0; i < signals.length(); ++i) {
    RootedObject signal(cx, &signals[i].toObject());
    if (is_aborted(signal)) {
      SetReservedSlot(self, std::to_underlying(Slots::Reason), reason(signal));
      return self;
    }
  }

  // Stage/deduplicate sources in the result's already admitted native set.
  // Publishing backlinks here would retain an unreachable partial result after
  // an allocation failure. Weak sweep is not a transaction rollback.
  // No second temporary heap vector or additional owner is needed.
  auto *our_signals = source_signals(self);
  for (size_t i = 0; i < signals.length(); ++i) {
    RootedObject signal(cx, &signals[i].toObject());
    if (!is_dependent(signal)) {
      if (!our_signals->insert(signal)) { JS_ReportOutOfMemory(cx); return nullptr; }
    } else {
      for (auto const &source : source_signals(signal)->items()) {
        MOZ_ASSERT(!is_aborted(source) && !is_dependent(source));
        if (!our_signals->insert(source)) { JS_ReportOutOfMemory(cx); return nullptr; }
      }
    }
  }

  // Reserve every backlink before publishing any. These SystemAllocPolicy
  // operations cannot run script or collect JS objects; self roots the staged
  // source edges. On failure only owned capacity may have grown, not the graph.
  for (auto const &source : our_signals->items()) {
    auto &links = dependent_signals(source)->items();
    if (!links.reserve(links.length() + 1)) {
      JS_ReportOutOfMemory(cx);
      return nullptr;
    }
  }
  SetReservedSlot(self, std::to_underlying(Slots::Dependent), JS::TrueValue());
  for (auto const &source : our_signals->items()) {
    // Sources are unique and self is new: no duplicate backlink can exist.
    dependent_signals(source)->items().infallibleAppend(self.get());
  }
  return self;
}

''', 'stage-and-reserve-complete-dependent-graph-before-backlink-publication')
    return source, {'format': 'latent.typescript.abort-timeout-source-derivation.v1',
        'starlingCommit': STARLING_COMMIT, 'originalSource': identity({PATH: raw}),
        'derivedSource': identity({PATH: source}),
        'checkedUnsignedMillisecondsBeforeSignalAllocation': True,
        'fractionalMilliseconds': 'truncate-toward-zero-after-ToNumber',
        'nonfiniteNegativeOrUint64Overflow': 'TypeError',
        'unrepresentableNanoseconds': 'explicit-profile-TypeError',
        'maximumRepresentableMilliseconds': (2**64-1)//1000000,
        'originalAbortAlgorithmsListenersAndTimeoutReasonRetained': True,
        'throwIfAbortedPreservesOriginalReasonIdentity': True,
        'anyConvertsOneIterableAndChecksSignalInstances': True,
        'anyHeapVectorOwner': 'one-original-native-count-per-frame-not-byte-accurate',
        'anyAllocationFailure': 'close-iterator-preserving-original-exception',
        'anyGraphPublication': 'deduplicate-in-owned-source-set-reserve-all-backlinks-then-infallible-commit',
        'anyGraphAllocationFailure': 'no-published-backlink-no-unreachable-result-retained-by-inputs',
        'staticAbortReasonOptional': True,
        'onabortHandler': 'stable-distinct-listener-with-transactional-value-and-WebIDL-conversion',
        'rootAbortFailureWithoutNewDependents': 'propagate-original-failure',
        'rootReasonAllocationFailure': 'return-before-direct-reason-slot-write',
        'dependentAbortReason': 'rooted-root-reason-identity',
        'dependentFanoutAdmission': 'before-vector-growth-and-reason-publication',
        'dependentFanoutOwner': 'one-original-native-count-per-heap-frame-not-byte-accurate',
        'dependentFanoutRetirement': 'frame-unwind-then-safe-host-ack',
        'defaultReasonReentrancy': 'first-completed-abort-wins',
        'defaultReasonFactory': 'checked-lookup-construction-and-native-class-before-slot-writes',
        'catchableAbortStepFailure': 'drain-dependents-then-restore-first-exception-and-stack',
        'savedExceptionRootOrder': 'reusable-signal-root-before-lazy-exception-state',
        'abortAlgorithmFailure': 'drain-independent-steps-retain-failed-records-and-preserve-first-exception',
        'abortAlgorithmRetirement': 'completed-prefix-destruction-only-no-extra-vector-or-owner',
        'pendingExceptionAtAbortEntry': 'fail-without-mutation-or-callbacks',
        'uncatchableAbortStepFailure': 'fence-without-restoring-earlier-catchable-failure',
        'abortEventAllocationFailure': 'return-after-original-algorithm-cleanup',
        'dependentAbortAndReasonAllocationFailures': 'not-qualified',
        'timerOrResultOwnerRetirement': 'same-original-host-stop-subtask-drop-acknowledgements',
        'supportedAsyncProfile': False, 'signedLSFComponentQualified': False}
