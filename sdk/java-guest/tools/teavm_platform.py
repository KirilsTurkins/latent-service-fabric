"""Exact TeaVM 0.15 C platform adaptation for bounded Wasm linear memory.

No Java application is replaced. Unavailable thread scheduling, ambient logging
and timezone discovery trap; the real LSF clock imports remain visible to
admission. Heap reservation is fully backed by the invocation's linear memory.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

PREIMAGES = {
    'fiber.c': 'b7f4592776d780165154c69e75b243ad9f32df0a717eb8bd29a11924fc6bc6df',
    'time.c': '9f4d0ea0a14f0786cb76172acd9bdefd4464aebf58a0372cfa66ff92dcacae2e',
    'memory.c': 'd685e2f0f8b3983d5886b48ece7d83298b864893f3c80701ed11cc779a51ada2',
}

FIBER = '''#include "fiber.h"
void teavm_initFiber(void) { }
void teavm_waitFor(int64_t timeout) { (void)timeout; __builtin_trap(); }
void teavm_interrupt(void) { __builtin_trap(); }
'''

CLOCK = '''#include "time.h"
#include "probe.h"
void teavm_initTime(void) { }
int64_t teavm_currentTimeMillis(void) { return (int64_t)latent_clock_wall_now_unix_millis(); }
int64_t teavm_currentTimeNano(void) { return (int64_t)latent_clock_monotonic_now_nanos(); }
int32_t teavm_timeZoneOffset(void) { __builtin_trap(); }
'''

MEMORY = '''#if defined(LSF_TEAVM_WASM)
    static void* teavm_virtualAlloc(int64_t size) {
        if (size <= 0 || size > 64 * 1024 * 1024) __builtin_trap();
        void* memory = calloc(1, (size_t)size);
        if (!memory) __builtin_trap();
        return memory;
    }
    static void teavm_virtualCommit(void* address, int64_t size) {
        /* Reservation is already fully backed and charged as linear memory. */
        (void)address; (void)size;
    }
    static void teavm_virtualUncommit(void* address, int64_t size) {
        /* Keep the bounded reservation; never pretend to return it to the OS. */
        memset(address, 0, (size_t)size);
    }
    static int64_t teavm_pageSize(void) { return 65536; }
#elif defined(__EMSCRIPTEN__)'''


def adapt(generated: Path) -> dict:
    originals = {}
    for name, expected in PREIMAGES.items():
        path = generated / name
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 65536:
            raise ValueError('unreviewed-teavm-platform-file')
        value = path.read_bytes()
        if hashlib.sha256(value).hexdigest() != expected:
            raise ValueError('unreviewed-teavm-platform-preimage:' + name)
        originals[name] = value.decode('utf-8')
    memory = originals['memory.c'].replace('#if TEAVM_UNIX\n', '#if TEAVM_UNIX && !defined(LSF_TEAVM_WASM)\n', 1)
    memory = memory.replace('#if defined(__EMSCRIPTEN__)', MEMORY, 1)
    outputs = {'fiber.c': FIBER, 'time.c': CLOCK, 'memory.c': memory}
    for name, value in outputs.items():
        (generated / name).write_text(value, encoding='utf-8', newline='\n')
    return {name: {'upstreamSha256': PREIMAGES[name],
                   'adaptedSha256': hashlib.sha256(value.encode()).hexdigest()}
            for name, value in outputs.items()}
