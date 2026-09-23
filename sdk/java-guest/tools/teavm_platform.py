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
    'file.c': 'f24a635fda53305cb4c317c7c1518bd072781fd0561da71ff1c3131e36615c08',
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

FILESYSTEM = '''#include "file.h"
/* Ambient filesystem and process-directory discovery are unsupported.
 * These entrypoints cannot fabricate success or access a host path. */
#define LSF_FILE_TRAP(result, name, arguments) result name arguments { __builtin_trap(); }
LSF_FILE_TRAP(int32_t, teavm_file_homeDirectory, (char16_t** a))
LSF_FILE_TRAP(int32_t, teavm_file_workDirectory, (char16_t** a))
LSF_FILE_TRAP(int32_t, teavm_file_tempDirectory, (char16_t** a))
LSF_FILE_TRAP(int32_t, teavm_file_isFile, (char16_t* a, int32_t b))
LSF_FILE_TRAP(int32_t, teavm_file_isDir, (char16_t* a, int32_t b))
LSF_FILE_TRAP(int32_t, teavm_file_exists, (char16_t* a, int32_t b))
LSF_FILE_TRAP(int32_t, teavm_file_canRead, (char16_t* a, int32_t b))
LSF_FILE_TRAP(int32_t, teavm_file_canWrite, (char16_t* a, int32_t b))
LSF_FILE_TRAP(TeaVM_StringList*, teavm_file_listFiles, (char16_t* a, int32_t b))
LSF_FILE_TRAP(int32_t, teavm_file_createDirectory, (char16_t* a, int32_t b))
LSF_FILE_TRAP(int32_t, teavm_file_createFile, (char16_t* a, int32_t b))
LSF_FILE_TRAP(int32_t, teavm_file_delete, (char16_t* a, int32_t b))
LSF_FILE_TRAP(int32_t, teavm_file_rename, (char16_t* a, int32_t b, char16_t* c, int32_t d))
LSF_FILE_TRAP(int64_t, teavm_file_lastModified, (char16_t* a, int32_t b))
LSF_FILE_TRAP(int32_t, teavm_file_setLastModified, (char16_t* a, int32_t b, int64_t c))
LSF_FILE_TRAP(int32_t, teavm_file_setReadonly, (char16_t* a, int32_t b, int32_t c))
LSF_FILE_TRAP(int32_t, teavm_file_length, (char16_t* a, int32_t b))
LSF_FILE_TRAP(int64_t, teavm_file_open, (char16_t* a, int32_t b, int32_t c))
LSF_FILE_TRAP(int32_t, teavm_file_close, (int64_t a))
LSF_FILE_TRAP(int32_t, teavm_file_flush, (int64_t a))
LSF_FILE_TRAP(int32_t, teavm_file_seek, (int64_t a, int32_t b, int32_t c))
LSF_FILE_TRAP(int32_t, teavm_file_tell, (int64_t a))
LSF_FILE_TRAP(int32_t, teavm_file_read, (int64_t a, int8_t* b, int32_t c, int32_t d))
LSF_FILE_TRAP(int32_t, teavm_file_write, (int64_t a, int8_t* b, int32_t c, int32_t d))
LSF_FILE_TRAP(int32_t, teavm_file_truncate, (int64_t a, int32_t b))
LSF_FILE_TRAP(int32_t, teavm_file_isWindows, (void))
LSF_FILE_TRAP(int32_t, teavm_file_canonicalize, (char16_t* a, int32_t b, char16_t** c))
#undef LSF_FILE_TRAP
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
    outputs = {'fiber.c': FIBER, 'time.c': CLOCK, 'memory.c': memory, 'file.c': FILESYSTEM}
    for name, value in outputs.items():
        (generated / name).write_text(value, encoding='utf-8', newline='\n')
    return {name: {'upstreamSha256': PREIMAGES[name],
                   'adaptedSha256': hashlib.sha256(value.encode()).hexdigest()}
            for name, value in outputs.items()}
