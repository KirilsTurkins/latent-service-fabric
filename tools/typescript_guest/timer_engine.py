"""Exact timer backend derivation for the private activation Promise engine.

The original callable globals and AbortSignal timer entrypoints remain ordinary
runtime APIs. The selected backend owns no ambient clock or host callback.
"""
from __future__ import annotations

import hashlib
from tools.typescript_guest.activation_engine import identity, replace_once, STARLING_COMMIT

PREIMAGES = {
    "StarlingMonkey/builtins/web/timers.cpp": "86ea5d06379182db1d4f2563b388fd4c4d1fbb1788a8b47b42ff6d6761d84c6a",
    "StarlingMonkey/builtins/web/timers.h": "bc4f4867fa647a1fa7814f6d013801adc24a11fcc824e1babee92cdd55b5054b",
}


def derive_activation_timers(original: dict[str, bytes]) -> tuple[dict[str, bytes], dict]:
    before = identity(original)
    if set(original) != set(PREIMAGES):
        raise ValueError("exact original timer implementation and public declarations required")
    for name, expected in PREIMAGES.items():
        if hashlib.sha256(original[name]).hexdigest() != expected:
            raise ValueError("unreviewed original timer source:" + name)
    result = dict(original)
    source = original["StarlingMonkey/builtins/web/timers.cpp"]
    namespace = b"namespace builtins::web::timers {\n"
    if source.count(namespace) != 1:
        raise ValueError("original timer namespace differs")
    source = (b'#include "timers.h"\n#include "native_engine.h"\n\n'
              b'static api::Engine* ENGINE;\n\n' +
              source[source.index(namespace):])
    start = source.index(b"template <bool repeat>\nbool set_timeout_or_interval")
    end = source.index(b"bool set_timeout(JSContext *cx", start)
    source = source[:start] + b"""template <bool repeat>
bool set_timeout_or_interval(JSContext *cx, HandleObject handler, JS::HandleValueVector handle_args,
                             int32_t delay_ms, int32_t *timer_id) {
  const auto arguments = JS::HandleValueArray::fromMarkedLocation(
      handle_args.length(), handle_args.begin());
  return lsf::typescript::activation::start_timer(
      cx, handler, arguments, delay_ms, repeat, timer_id);
}

""" + source[end:]
    source = replace_once(source, b"""  JS::RootedValueVector handler_args(cx);
  if (args.length() > 2 && !handler_args.initCapacity(args.length() - 2)) {
    JS_ReportOutOfMemory(cx);
    return false;
  }
  for (size_t i = 2; i < args.length(); i++) {
    handler_args.infallibleAppend(args[i]);
  }

""", b"""  // CallArgs are already traced by the native frame. Reserve the timer and
  // native capture record before copying arguments or allocating another vector.
  const auto handler_args = args.length() > 2
      ? JS::HandleValueArray::subarray(JS::HandleValueArray(args), 2, args.length() - 2)
      : JS::HandleValueArray::empty();

""", "precharged-original-global-captures")
    source = replace_once(source,
        b"  if (!set_timeout_or_interval<repeat>(cx, handler, handler_args, delay_ms, &timer_id)) {",
        b"  if (!lsf::typescript::activation::start_timer(\n"
        b"          cx, handler, handler_args, delay_ms, repeat, &timer_id)) {",
        "original-global-native-backend")
    source = replace_once(source,
        b"""  if (!args.requireAtLeast(cx, interval ? "clearInterval" : "clearTimeout", 1)) {
    return false;
  }

""", b"""  if (args.length() == 0) {
    args.rval().setUndefined();
    return true;
  }

""", "standard-clear-without-arguments")
    source = replace_once(source, b"  clear_timeout_or_interval(id);\n",
        b"  if (!lsf::typescript::activation::clear_timer(cx, id)) return false;\n",
        "actual-clear-stop-acknowledgement")
    source = replace_once(source,
        b"void clear_timeout_or_interval(int32_t timer_id) { TimerTask::clear(timer_id); }",
        b"void clear_timeout_or_interval(int32_t timer_id) {\n"
        b"  (void)lsf::typescript::activation::clear_timer(ENGINE->cx(), timer_id);\n}",
        "retained-original-abort-helper")
    source = replace_once(source,
        b"  TIMERS_MAP.init(engine->cx(), js::MakeUnique<TimersMap>());\n",
        b"", "lazy-selected-timer-storage")
    result["StarlingMonkey/builtins/web/timers.cpp"] = source
    return result, {
        "format": "latent.typescript.activation-timer-source-derivation.v1",
        "starlingCommit": STARLING_COMMIT, "originalSource": before,
        "derivedSource": identity(result),
        "originalTimerHeaderUnchanged": True,
        "originalCallableGlobalNamesAndNumericIDsRetained": True,
        "additionalArgumentCopyAfterNativeAndTimerAdmission": True,
        "clearWithoutArguments": "no-op",
        "timeoutDelayConversion": "original-pinned-ToInt32-then-clamp-negative",
        "intervalPolicy": "fixed-rate-coalescing-minimum-one-millisecond-period",
        "intervalCatchUpQueueOrOverlappingCallback": False,
        "timerNextReadiness": "actual-p3-subtask-return-unjoin-drop",
        "hostCallbackOrAmbientClock": False,
        "supportedAsyncProfile": False, "signedLSFComponentQualified": False,
    }

