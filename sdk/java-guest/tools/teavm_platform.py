"""Exact TeaVM 0.15 C platform adaptation for bounded Wasm linear memory.

No Java application is replaced. Unavailable thread scheduling, ambient logging
and timezone discovery trap; the real LSF clock imports remain visible to
admission. Heap reservation is fully backed by the invocation's linear memory.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
import re

PREIMAGES = {
    'arrayclass.c': '044dc626c36581887874d0f4cda5070be0dfdcdb703c6ef0893616e568dc0058',
    'fiber.c': 'b7f4592776d780165154c69e75b243ad9f32df0a717eb8bd29a11924fc6bc6df',
    'time.c': '9f4d0ea0a14f0786cb76172acd9bdefd4464aebf58a0372cfa66ff92dcacae2e',
    'memory.c': 'd685e2f0f8b3983d5886b48ece7d83298b864893f3c80701ed11cc779a51ada2',
    'file.c': '49c8a5f152eefffbe2832b607fcd40b225936fc593d1a0d53fb81ed700a30538',
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


def aligned_array_classes(original: str) -> str:
    # TeaVM compresses every class pointer by three bits. Its generated static
    # classes are alignas(8), but the dynamic array-class pool uses native C
    # pointer alignment and can have a 60-byte stride on wasm32. Aligning only
    # the pool base is insufficient: every slot must preserve the low bits.
    replacements = {
        'static TEAVM_OBJECT_CLASS teavm_dynamicClassPool[TEAVM_DYNAMIC_CLASS_POOL_CAPACITY];':
            'typedef struct { alignas(8) TEAVM_OBJECT_CLASS value; } LsfArrayClassSlot;\n'
            '_Static_assert(sizeof(LsfArrayClassSlot) % 8 == 0, "compressed class stride");\n'
            'static LsfArrayClassSlot teavm_dynamicClassPool[TEAVM_DYNAMIC_CLASS_POOL_CAPACITY];',
        '&teavm_dynamicClassPool[teavm_dynamicClassPoolSize++]':
            '&teavm_dynamicClassPool[teavm_dynamicClassPoolSize++].value',
        '&teavm_dynamicClassPool[index].parent':
            '&teavm_dynamicClassPool[index].value.parent',
    }
    for before, after in replacements.items():
        if original.count(before) != 1:
            raise ValueError('unreviewed-array-class-layout')
        original = original.replace(before, after)
    return original


SPILL_DECLARATION = re.compile(
    r'(?m)^[ \t]+(?:[A-Za-z_][A-Za-z_0-9]*[ \t*]+)+teavm_spill_[0-9]+;[ \t]*\r?$')
SPILL_TYPES = {'volatile void*', 'volatile int32_t', 'volatile int64_t',
               'volatile float', 'volatile double'}


def reference_spills(original: str, *, array_references: bool = False) -> tuple[str, int]:
    # TeaVM 0.15 saves Java locals across setjmp/longjmp in teavm_spill_N.
    # Its scalar spills qualify the local correctly, but "volatile void*"
    # qualifies the pointee. With -O2, the pointer saves disappear and a
    # catch/finally continuation can receive an indeterminate Java reference.
    # Change only the pinned generated declaration grammar, never Java source,
    # object layout, exception routing, or the compiler optimization level.
    count = 0

    def replace(match: re.Match) -> str:
        nonlocal count
        declaration = match.group()
        exact = re.fullmatch(r'    (.+) (teavm_spill_[0-9]+);', declaration)
        reviewed = SPILL_TYPES | ({'volatile TeaVM_Array*'} if array_references else set())
        if exact is None or exact[1] not in reviewed:
            raise ValueError('unreviewed-teavm-exception-spill')
        if exact[1] not in ('volatile void*', 'volatile TeaVM_Array*'):
            return declaration
        count += 1
        return '    ' + exact[1].removeprefix('volatile ') + ' volatile ' + exact[2] + ';'

    return SPILL_DECLARATION.sub(replace, original), count


def reference_spill_outputs(generated: Path, *, array_references: bool = False) -> tuple[list, dict]:
    classes = generated / 'c'
    if classes.is_symlink() or not classes.is_dir():
        raise ValueError('unreviewed-teavm-generated-classes')
    outputs, identities = [], []
    entries = total_bytes = scanned = pointers = 0
    for path in classes.rglob('*'):
        entries += 1
        if entries > 65536 or path.is_symlink():
            raise ValueError('unreviewed-teavm-generated-classes')
        if path.suffix != '.c':
            continue
        if not path.is_file() or path.stat().st_size > 16 * 1024 * 1024:
            raise ValueError('unreviewed-teavm-generated-class')
        scanned += 1
        total_bytes += path.stat().st_size
        if scanned > 16384 or total_bytes > 256 * 1024 * 1024:
            raise ValueError('teavm-generated-class-size-limit')
        original = path.read_bytes()
        adapted, count = reference_spills(original.decode('utf-8'), array_references=array_references)
        if not count:
            continue
        value = adapted.encode('utf-8')
        pointers += count
        outputs.append((path, value))
        identities.append({'path': path.relative_to(generated).as_posix(),
                           'upstreamSha256': hashlib.sha256(original).hexdigest(),
                           'adaptedSha256': hashlib.sha256(value).hexdigest(),
                           'pointerSpills': count})
    outputs.sort(key=lambda item: item[0].relative_to(generated).as_posix())
    identities.sort(key=lambda item: item['path'])
    profile = ('teavm-0.15-wasm-sjlj-reference-spills-v2' if array_references
               else 'teavm-0.15-wasm-sjlj-pointer-spills-v1')
    return outputs, {'profile': profile,
                     'scannedClasses': scanned, 'pointerSpills': pointers,
                     'files': identities}


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
    # Validate every generated declaration before changing any platform or
    # class file. The caller has already verified the exact compiler JARs.
    # The byte-verified 0.15 CodeWriter emits TeaVM_Array* for all eight array
    # VariableType categories. Its array saves need the same pointer qualifier.
    # Keep the historical v1 helper boundary; the maintained compiler selects v2.
    spill_outputs, spill_receipt = reference_spill_outputs(generated, array_references=True)
    memory = originals['memory.c'].replace('#if TEAVM_UNIX\n', '#if TEAVM_UNIX && !defined(LSF_TEAVM_WASM)\n', 1)
    memory = memory.replace('#if defined(__EMSCRIPTEN__)', MEMORY, 1)
    outputs = {'fiber.c': FIBER, 'time.c': CLOCK, 'memory.c': memory, 'file.c': FILESYSTEM,
               'arrayclass.c': aligned_array_classes(originals['arrayclass.c'])}
    for name, value in outputs.items():
        (generated / name).write_text(value, encoding='utf-8', newline='\n')
    for path, value in spill_outputs:
        path.write_bytes(value)
    receipt = {name: {'upstreamSha256': PREIMAGES[name],
                     'adaptedSha256': hashlib.sha256(value.encode()).hexdigest()}
               for name, value in outputs.items()}
    receipt['referenceSpills'] = spill_receipt
    return receipt
