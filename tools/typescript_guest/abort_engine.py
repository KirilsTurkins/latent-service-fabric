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
        b'#include "../timers.h"\n#include "native_timeout.h"\n#include "native_engine.h"\n', 'abort-native-include')
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
    return source, {'format': 'latent.typescript.abort-timeout-source-derivation.v1',
        'starlingCommit': STARLING_COMMIT, 'originalSource': identity({PATH: raw}),
        'derivedSource': identity({PATH: source}),
        'checkedUnsignedMillisecondsBeforeSignalAllocation': True,
        'fractionalMilliseconds': 'truncate-toward-zero-after-ToNumber',
        'nonfiniteNegativeOrUint64Overflow': 'TypeError',
        'unrepresentableNanoseconds': 'explicit-profile-TypeError',
        'maximumRepresentableMilliseconds': (2**64-1)//1000000,
        'originalAbortAlgorithmsListenersAndTimeoutReasonRetained': True,
        'timerOrResultOwnerRetirement': 'same-original-host-stop-subtask-drop-acknowledgements',
        'supportedAsyncProfile': False, 'signedLSFComponentQualified': False}
