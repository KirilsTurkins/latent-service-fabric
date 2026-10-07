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
}
NATIVE_SOURCES = (
    "native_job_queue.h", "broker_accounting.h", "native_engine.h", "native_engine.cpp",
    "promise_hooks.h", "promise_records.h", "promise_accounting.h",
    "reaction_records.h",
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

    event_loop = result["StarlingMonkey/runtime/event_loop.cpp"]
    event_loop = replace_once(event_loop, b'#include "event_loop.h"\n',
        b'#include "event_loop.h"\n#include "native_engine.h"\n', "event-loop-promise-include")
    event_loop = replace_once(event_loop, b"    js::RunJobs(cx);\n",
        b"    if (!lsf::typescript::activation::acknowledge_promise_retirement(cx)) {\n"
        b"      exit_event_loop();\n      return false;\n    }\n"
        b"    js::RunJobs(cx);\n"
        b"    if (!lsf::typescript::activation::acknowledge_promise_retirement(cx)) {\n"
        b"      exit_event_loop();\n      return false;\n    }\n", "non-gc-retirement-checkpoint")
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
        "ordinaryCompilerSelectionChanged": False,
        "supportedAsyncProfile": False,
        "qualification": "pending-real-engine-and-signed-component-controls",
        "remaining": ["pending-promise-lifecycle", "root-and-accepted-work-drain",
                      "native-async-task-accounting", "standard-timers-and-stop-acknowledgements",
                      "actual-async-import-continuations", "matching-signed-component-qualification"],
    }
    return result, receipt
