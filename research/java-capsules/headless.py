#!/usr/bin/env python3
"""A checked TeaVM 0.15 C reactor experiment, not a qualified Java guest SDK."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil

RUNTIME_HASHES = {
    "definitions.h": "27ba4d5cb22a436ddff7d36971d1068e74794b3646f64853b0196e9867c8fc63",
    "exceptions.h": "024e4fafa0a2cd330911b5d84d1b929f928a88d74730cc265d08cbbb940eb368",
    "memory.c": "d685e2f0f8b3983d5886b48ece7d83298b864893f3c80701ed11cc779a51ada2",
}
SJ_LJ_SHA256 = "1b7dbf4535d7a1aad7d83dccd17b965cea43316f206bb3b2cc1a243c6673bfff"
SJ_LJ_FLAGS = ["-mexception-handling", "-mllvm", "-wasm-enable-sjlj",
               "-mllvm", "-wasm-use-legacy-eh=false"]
MEMORY_BACKEND = """#if defined(__wasi__)
    static void* teavm_virtualAlloc(int64_t size) {
        if (size <= 0 || size > INT32_MAX) __builtin_trap();
        void* pointer = malloc((size_t) size);
        if (pointer == NULL) __builtin_trap();
        return pointer;
    }
    /* All backing memory is allocated above, inside the bounded Wasm memory. */
    static void teavm_virtualCommit(void* address, int64_t size) {
        (void) address;
        (void) size;
    }
    static void teavm_virtualUncommit(void* address, int64_t size) {
        /* Logical shrinking cannot reclaim Wasm pages. Store drop must do that. */
        memset(address, 0, (size_t) size);
    }
    static int64_t teavm_pageSize(void) { return 65536; }
#elif defined(__EMSCRIPTEN__)"""


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def replace_once(text: str, old: str, new: str) -> str:
    if text.count(old) != 1:
        raise ValueError("headless-runtime-layout-drift: " + old.strip())
    return text.replace(old, new, 1)


def inputs(source: Path) -> dict[str, str]:
    if not source.is_dir() or source.is_symlink():
        raise ValueError("headless-input-not-directory")
    files: dict[str, str] = {}
    size = 0
    for path in sorted(source.rglob("*")):
        if path.is_symlink():
            raise ValueError("headless-input-symlink")
        if path.is_dir():
            continue
        if not path.is_file():
            raise ValueError("headless-input-not-regular")
        size += path.stat().st_size
        if len(files) >= 2048 or size > 64 * 1024 * 1024:
            raise ValueError("headless-input-limit")
        files[path.relative_to(source).as_posix()] = sha256(path)
    for name, expected in RUNTIME_HASHES.items():
        if files.get(name) != expected:
            raise ValueError("headless-runtime-hash-drift: " + name)
    for name in ("main.c", "all.c", "classes/dev/latent/probe/Probe.c"):
        if name not in files:
            raise ValueError("headless-missing-generated-input: " + name)
    return files


def prepare(source: Path, output: Path) -> dict:
    """Keep original compiler evidence immutable; modify only runtime scaffolding.

    This profile intentionally targets the maintained research Probe, not arbitrary
    user applications. No Java business method, GC implementation, exception
    dispatch table, WIT contract, or compiler dependency is replaced.
    """
    if source.is_symlink():
        raise ValueError("headless-input-symlink")
    source, output = source.resolve(), output.resolve()
    if output == source or output.is_relative_to(source) or source.is_relative_to(output):
        raise ValueError("headless-output-overlaps-input")
    original = inputs(source)
    edits = {}
    text = (source / "definitions.h").read_text()
    edits["definitions.h"] = text + (
        "\n#if defined(__wasi__)\n#undef TEAVM_UNIX\n#define TEAVM_UNIX 0\n#endif\n")
    edits["exceptions.h"] = replace_once((source / "exceptions.h").read_text(),
        "#if TEAVM_UNIX", "#if TEAVM_UNIX || defined(__wasi__)")
    edits["memory.c"] = replace_once((source / "memory.c").read_text(),
        "#if defined(__EMSCRIPTEN__)", MEMORY_BACKEND)
    main = replace_once((source / "main.c").read_text(),
        "int main(int argc, char** argv)", "int lsf_java_initialize(void)")
    for call in ("    teavm_beforeInit();\n",
                 "    meth_otr_Fiber_startMain(teavm_parseArguments(argc, argv));\n",
                 "    meth_otr_EventQueue_process();\n"):
        main = replace_once(main, call, "")
    edits["main.c"] = main
    shutil.copytree(source, output)
    for name, text in edits.items():
        (output / name).write_text(text, encoding="utf-8")
    bridge = Path(__file__).with_name("headless_bridge.c")
    shutil.copyfile(bridge, output / "headless_bridge.c")
    if inputs(source) != original:
        raise ValueError("headless-source-changed-during-preparation")
    for name, expected in original.items():
        if name not in edits and sha256(output / name) != expected:
            raise ValueError("headless-changed-application-or-generated-code: " + name)
    receipt = {"formatVersion": 1, "qualification": "not-qualified",
               "sourceFiles": original, "runtimeEdits": {
                   name: {"before": original[name], "after": sha256(output / name)}
                   for name in sorted(edits)}, "bridgeSha256": sha256(bridge),
               "heapBytes": {"javaMinimum": 4 * 1024 * 1024,
                             "javaMaximum": 16 * 1024 * 1024,
                             "wasmMaximum": 64 * 1024 * 1024,
                             "linearStack": 256 * 1024},
               "javaExecution": "not-attempted", "lsfExecution": "not-attempted"}
    (output / "port-receipt.json").write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    return receipt


def compile_commands(zig: str, zig_lib: Path, output: Path) -> list[tuple[str, list[str]]]:
    """Compile SJ/LJ support explicitly, then link the unchanged non-EH libc.

    Passing EH to Zig's libc build crashes LLVM 21.1 on its undefined weak tag.
    Compile the exact bundled rt.c with the same SJ/LJ flags as the application;
    this is neither a replacement exception implementation nor a libc patch.
    """
    support = zig_lib / "libc/wasi/libc-top-half/musl/src/setjmp/wasm32/rt.c"
    if not support.is_file():
        raise ValueError("headless-missing-pinned-zig-sjlj-runtime")
    if sha256(support) != SJ_LJ_SHA256:
        raise ValueError("headless-pinned-zig-sjlj-runtime-drift")
    (output / "sjlj-input.json").write_text(json.dumps({
        "path": str(support), "sha256": sha256(support),
        "bytes": support.stat().st_size}, indent=2) + "\n")
    compile_ = [zig, "cc", "-target", "wasm32-wasi", "-O2", *SJ_LJ_FLAGS,
                "-ffunction-sections", "-fdata-sections", "-c"]
    return [
        ("c-headless-compile", [*compile_, str(output / "headless_bridge.c"), "-o", str(output / "probe.o")]),
        ("c-headless-sjlj", [*compile_, str(support), "-o", str(output / "sjlj.o")]),
        ("c-headless-link", [zig, "cc", "-target", "wasm32-wasi", "-O2", "-mexec-model=reactor",
            "-Wl,-z,stack-size=262144", "-Wl,--max-memory=67108864",
            str(output / "probe.o"), str(output / "sjlj.o"), "-o", str(output / "probe.wasm")]),
    ]
