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
        b'#include "js/ForOfIterator.h"\n', 'abort-native-include')
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
    if (!signals.append(value)) { JS_ReportOutOfMemory(cx); return false; }
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
    source = replace_once(source,
        b'  set_reason(cx, self, reason);\n',
        b'  if (!set_reason(cx, self, reason)) return false;\n',
        'abort-root-reason-before-dependent-mutation')
    source = replace_once(source,
        b'  RootedObject event(cx, Event::create(cx, type_val, JS::NullHandleValue));\n'
        b'  RootedValue event_val(cx, JS::ObjectValue(*event));\n',
        b'  RootedObject event(cx, Event::create(cx, type_val, JS::NullHandleValue));\n'
        b'  if (!event) return false;\n'
        b'  RootedValue event_val(cx, JS::ObjectValue(*event));\n',
        'abort-event-allocation-before-dereference')
    source = replace_once(source,
        b'  run_abort_steps(cx, self);\n',
        b'  // With no newly aborted dependents there is no later abort work to skip.\n'
        b'  if (!run_abort_steps(cx, self) && dep_signals_to_abort.empty()) return false;\n',
        'preserve-root-abort-error-when-no-dependent-work-remains')
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
        'staticAbortReasonOptional': True,
        'rootAbortFailureWithoutNewDependents': 'propagate-original-failure',
        'rootReasonAllocationFailure': 'return-before-direct-reason-slot-write',
        'abortEventAllocationFailure': 'return-after-original-algorithm-cleanup',
        'dependentAbortAndReasonAllocationFailures': 'not-qualified',
        'timerOrResultOwnerRetirement': 'same-original-host-stop-subtask-drop-acknowledgements',
        'supportedAsyncProfile': False, 'signedLSFComponentQualified': False}
