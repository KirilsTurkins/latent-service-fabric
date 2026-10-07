"""Exact source derivation for the private native Promise queue experiment.

This is deliberately separate from Compiler's supported ordinary-value path.
The queue experiment is not yet a supported async runtime selection: timer,
root/drain and pending-Promise lifecycle qualification remain required.
"""
from __future__ import annotations

import hashlib
from pathlib import PurePosixPath

COMPONENTIZE_TREE = "4b8d6eb465b5cded6b97c67aaf6fdaa8b62001e2"
STARLING_COMMIT = "9dda8ba7fcda2e17c6795d402f0478cf4c1f7f37"
FIREFOX_COMMIT = "9dab3d6f643e926a340c391ea30968e940390dec"
PROFILE = "spidermonkey-activation-promises-v1"

PREIMAGES = {
    "CMakeLists.txt": "0d10488ba42890d869b1c6c443d977e9b2df1f84e6183b6808906397692602f8",
    "StarlingMonkey/runtime/engine.cpp": "91bfc4d7e6376c802e2c9abc5e62554d52c804b50f5eabb07ccca6916af0626d",
    "StarlingMonkey/runtime/event_loop.cpp": "22a6a46ed762f64dd23665f5bcff089ac147e26d691fe65fa30fa85abbe57471",
    "embedding/embedding.cpp": "0c083624ba85778cafe9aadbf81a3b9db63d6b632bb1760088098dd3a0b82cbb",
    "StarlingMonkey/builtins/web/timers.cpp": "86ea5d06379182db1d4f2563b388fd4c4d1fbb1788a8b47b42ff6d6761d84c6a",
    "StarlingMonkey/builtins/web/timers.h": "bc4f4867fa647a1fa7814f6d013801adc24a11fcc824e1babee92cdd55b5054b",
}
NATIVE_SOURCES = (
    "native_job_queue.h", "broker_accounting.h", "native_engine.h", "native_engine.cpp",
    "promise_hooks.h", "promise_records.h", "promise_accounting.h",
    "reaction_records.h", "native_readiness.h", "native_timers.h",
)


def identity(files: dict[str, bytes]) -> list[dict]:
    rows = []
    for name, raw in sorted(files.items()):
        path = PurePosixPath(name)
        if (not isinstance(raw, bytes) or path.is_absolute() or ".." in path.parts
                or str(path) != name):
            raise ValueError("invalid exact engine material")
        rows.append({"path": name, "bytes": len(raw),
                     "sha256": hashlib.sha256(raw).hexdigest()})
    return rows


def replace_once(raw: bytes, old: bytes, new: bytes, label: str) -> bytes:
    if raw.count(old) != 1:
        raise ValueError("pinned engine hook shape differs:" + label)
    return raw.replace(old, new, 1)


def derive_queue_experiment(original: dict[str, bytes], native: dict[str, bytes],
                            generated: dict[str, bytes]) -> tuple[dict[str, bytes], dict]:
    """Return a new source carrier, preserving every input byte separately.

    The caller must supply authenticated full upstream carriers and the exact
    current wit-bindgen0.62 jobs outputs. This function performs no download,
    process execution, global installation or supported-profile promotion.
    """
    before = identity(original)
    if not PREIMAGES.keys() <= original.keys():
        raise ValueError("missing pinned engine source")
    for name, expected in PREIMAGES.items():
        if hashlib.sha256(original[name]).hexdigest() != expected:
            raise ValueError("unreviewed original engine source:" + name)
    if set(native) != set(NATIVE_SOURCES):
        raise ValueError("exact SDK native queue source selection required")
    if set(generated) != {"jobs.h", "jobs.c", "jobs_component_type.o"}:
        raise ValueError("exact generated current activation ABI required")
    identity(native)
    identity(generated)
    if any(name.startswith("lsf/") for name in original):
        raise ValueError("engine carrier already contains a private SDK extension")

    result = dict(original)
    from tools.typescript_guest.timer_engine import derive_activation_timers
    timer_sources, timer_receipt = derive_activation_timers({
        name: original[name] for name in (
            "StarlingMonkey/builtins/web/timers.cpp", "StarlingMonkey/builtins/web/timers.h")})
    result.update(timer_sources)
    engine = result["StarlingMonkey/runtime/engine.cpp"]
    engine = replace_once(engine, b'#include "event_loop.h"',
                          b'#include "event_loop.h"\n#include "native_engine.h"', "include")
    engine = replace_once(engine, b'bool init_js(const EngineConfig& config) {\n  JS_Init();',
        b'bool init_js(const EngineConfig& config) {\n'
        b'  lsf::typescript::activation::configure_job_dispatch();\n  JS_Init();', "dispatch-pref")
    engine = replace_once(engine,
        b'  if (!create_content_global(cx) || !create_initializer_global(ENGINE)) {',
        b'  if (!lsf::typescript::activation::install_job_dispatch(cx)) return false;\n\n'
        b'  if (!create_content_global(cx) || !create_initializer_global(ENGINE)) {', "queue-install")
    engine = replace_once(engine, b'  SCRIPT_VALUE = ns;\n  this->run_event_loop();',
        b'  SCRIPT_VALUE = ns;\n  if (!this->run_event_loop()) return false;', "snapshot-event-result")
    engine = replace_once(engine, b'    if (state == JS::PromiseState::Rejected) {',
        b'    if (state == JS::PromiseState::Pending &&\n'
        b'        this->state() == EngineState::ScriptPreInitializing) {\n'
        b'      JS_ReportErrorASCII(cx(), "activation-runtime-pending-tla-during-snapshot-denied");\n'
        b'      return false;\n    }\n'
        b'    if (state == JS::PromiseState::Rejected) {', "pending-tla")
    engine = replace_once(engine, b'  if (state() == EngineState::ScriptPreInitializing) {\n'
                                 b'    JS::PrepareForFullGC(cx());',
        b'  if (state() == EngineState::ScriptPreInitializing) {\n'
        b'    if (!lsf::typescript::activation::snapshot_jobs_empty(cx())) return false;\n'
        b'    JS::PrepareForFullGC(cx());', "snapshot-job-empty")
    result["StarlingMonkey/runtime/engine.cpp"] = engine

    embedding = result["embedding/embedding.cpp"]
    embedding = replace_once(embedding, b'#include "embedding.h"\n',
        b'#include "embedding.h"\n#include "native_engine.h"\n', "root-embedding-include")
    embedding = replace_once(embedding,
        b"  Runtime.engine->decr_event_loop_interest();\n  return true;\n",
        b"  if (!lsf::typescript::activation::settle_root(cx)) return false;\n"
        b"  Runtime.engine->decr_event_loop_interest();\n  return true;\n", "actual-root-fulfilled")
    embedding = replace_once(embedding,
        b"  Runtime.engine->decr_event_loop_interest();\n"
        b"  Runtime.engine->dump_error(args.get(0), stderr);\n  return false;\n",
        b"  JS_SetPendingException(cx, args.get(0));\n"
        b"  if (!lsf::typescript::activation::settle_root(cx)) return false;\n"
        b"  Runtime.engine->decr_event_loop_interest();\n"
        b"  Runtime.engine->dump_error(args.get(0), stderr);\n  return false;\n", "actual-root-rejected")
    embedding = replace_once(embedding,
        b"  JSAutoRealm ar(Runtime.cx, Runtime.engine->global());\n\n"
        b"  JS::RootedVector<JS::Value> args(Runtime.cx);\n",
        b"  JSAutoRealm ar(Runtime.cx, Runtime.engine->global());\n\n"
        b"  if (!lsf::typescript::activation::begin_root(Runtime.cx))\n"
        b'    Runtime.engine->abort("(call) activation root admission denied");\n'
        b"  JS::RootedVector<JS::Value> args(Runtime.cx);\n", "root-admit-before-lowering-frame")
    embedding = replace_once(embedding, b"  // all calls are async functions returning promises\n",
        b"  if (!lsf::typescript::activation::park_root(Runtime.cx))\n"
        b'    Runtime.engine->abort("(call) activation root park denied");\n\n'
        b"  // all calls are async functions returning promises\n", "actual-root-frame-suspended")
    embedding = replace_once(embedding, b"  Runtime.free_list.clear();\n  RootedValue result(Runtime.cx);\n",
        b"  Runtime.free_list.clear();\n"
        b"  if (!lsf::typescript::activation::acknowledge_result_retirement(Runtime.cx))\n"
        b'    Runtime.engine->abort("(post_call) actual result retirement denied");\n'
        b"  RootedValue result(Runtime.cx);\n", "actual-post-call-result-retirement")
    result["embedding/embedding.cpp"] = embedding

    event_loop = result["StarlingMonkey/runtime/event_loop.cpp"]
    event_loop = replace_once(event_loop, b'#include "event_loop.h"\n',
        b'#include "event_loop.h"\n#include "native_engine.h"\n', "event-loop-promise-include")
    event_loop = replace_once(event_loop, b"    js::RunJobs(cx);\n",
        b"    if (!lsf::typescript::activation::acknowledge_promise_retirement(cx)) {\n"
        b"      exit_event_loop();\n      return false;\n    }\n"
        b"    js::RunJobs(cx);\n"
        b"    if (!lsf::typescript::activation::acknowledge_promise_retirement(cx)) {\n"
        b"      exit_event_loop();\n      return false;\n    }\n", "non-gc-retirement-checkpoint")
    event_loop = replace_once(event_loop,
        b"    if (interest_complete()) {\n      exit_event_loop();\n      return true;\n    }\n",
        b"    if (interest_complete()) {\n"
        b"      const bool drained = lsf::typescript::activation::root_work_drained(cx);\n"
        b"      exit_event_loop();\n      return drained;\n    }\n", "root-versus-accepted-work-drain")
    event_loop = replace_once(event_loop,
        b"    // if there is no interest in the event loop at all, just run one tick\n",
        b"    // Timers are accepted work even after the root Promise settles.\n"
        b"    // Dispatch one ordinary callback, then the next genuine microtask\n"
        b"    // checkpoint. P3 readiness suspends only an idle native pump.\n"
        b"    if (lsf::typescript::activation::has_pending_timer_work()) {\n"
        b"      if (!lsf::typescript::activation::run_timer_turn(cx)) {\n"
        b"        exit_event_loop();\n        return false;\n      }\n"
        b"      continue;\n    }\n"
        b"    // if there is no interest in the event loop at all, just run one tick\n",
        "actual-timer-before-root-drain")
    event_loop = replace_once(event_loop,
        b"    auto *const tasks = &queue.get().tasks;\n",
        b"    auto *const tasks = &queue.get().tasks;\n"
        b"    if (!tasks->empty()) {\n"
        b'      JS_ReportErrorASCII(cx, "activation-runtime-unselected-native-async-task-denied");\n'
        b"      exit_event_loop();\n      return false;\n    }\n",
        "unsupported-legacy-host-task-fence")
    result["StarlingMonkey/runtime/event_loop.cpp"] = event_loop

    cmake = result["CMakeLists.txt"]
    cmake = replace_once(cmake, b'project(ComponentizeJS)\n',
        b'project(ComponentizeJS)\n\n'
        b'target_sources(starling-raw.wasm PRIVATE\n'
        b'  "${CMAKE_CURRENT_SOURCE_DIR}/lsf/native_engine.cpp"\n'
        b'  "${CMAKE_CURRENT_SOURCE_DIR}/lsf/jobs.c"\n'
        b'  "${CMAKE_CURRENT_SOURCE_DIR}/lsf/jobs_component_type.o")\n'
        b'target_include_directories(starling-raw.wasm PRIVATE "${CMAKE_CURRENT_SOURCE_DIR}/lsf")\n',
        "private-native-source")
    result["CMakeLists.txt"] = cmake
    for name, raw in (native | generated).items():
        result["lsf/" + name] = raw
    receipt = {
        "format": "latent.typescript.native-job-experiment.v1",
        "intendedProfile": PROFILE,
        "componentizeTree": COMPONENTIZE_TREE, "starlingCommit": STARLING_COMMIT,
        "firefoxCommit": FIREFOX_COMMIT,
        "originalSource": before, "derivedSource": identity(result),
        "nativeQueueSource": identity(native), "generatedActivationABI": identity(generated),
        "selectedTimerDerivation": timer_receipt,
        "ordinaryCompilerSelectionChanged": False,
        "supportedAsyncProfile": False,
        "qualification": "pending-real-engine-and-signed-component-controls",
        "remaining": ["pending-promise-lifecycle", "root-and-accepted-work-drain",
                      "native-async-task-accounting", "standard-timers-and-stop-acknowledgements",
                      "actual-async-import-continuations", "matching-signed-component-qualification"],
    }
    return result, receipt
