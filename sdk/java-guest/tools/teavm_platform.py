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
#ifdef LSF_JAVA_ACTIVATION_PROFILE
extern void lsf_java_runtime_wait(int64_t timeout);
void teavm_initFiber(void) { }
void teavm_waitFor(int64_t timeout) { lsf_java_runtime_wait(timeout); }
/* All Java queue producers run in this Store. No host thread or signal owns
 * the event queue, and the pump observes an offered event before a host await. */
void teavm_interrupt(void) { }
#else
void teavm_initFiber(void) { }
void teavm_waitFor(int64_t timeout) { (void)timeout; __builtin_trap(); }
void teavm_interrupt(void) { __builtin_trap(); }
#endif
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

CLASS_SIZE_ALIGNMENT = re.compile(
    r'(?m)^(\s+\.size = \(int32_t\) \(intptr_t\) TEAVM_ALIGN\(sizeof\([A-Za-z_][A-Za-z0-9_]*\), )'
    r'sizeof\(void\*\)(\),\s*)$')
HEAP_ALIGNMENT_FIX = 'konsoletyper/teavm#1281@c197880e951b8ecb6c6ee5bffa7c16563be790f3'
HEAP_ALIGNMENT_RUNTIME = {
    'c/o/t/r/Allocator.c': 'meth_otr_Allocator_allocateArray',
    'c/o/t/r/GC.c': 'meth_otr_GC_objectSize_0',
}
MONITOR_ROOT_ISSUE = 'konsoletyper/teavm#1330'


def _aligned_runtime_function(original: str, function: str) -> str:
    signatures = list(re.finditer(
        r'(?m)^[^\r\n{};]*\b' + re.escape(function) + r'\([^;\r\n]*\) \{\r?$', original))
    if len(signatures) != 1:
        raise ValueError('unreviewed-teavm-heap-alignment-function')
    closing = re.search(r'(?m)^}\r?$', original[signatures[0].end():])
    if closing is None:
        raise ValueError('unreviewed-teavm-heap-alignment-function')
    end = signatures[0].end() + closing.end()
    body = original[signatures[0].start():end]
    candidates = [line for line in body.splitlines(keepends=True)
                  if 'TEAVM_ALIGN' in line and 'sizeof(void*)' in line]
    if len(candidates) != 1 or candidates[0].count('sizeof(void*)') != 1:
        raise ValueError('unreviewed-teavm-heap-alignment-runtime')
    corrected = candidates[0].replace('sizeof(void*)', 'INT32_C(8)')
    return original[:signatures[0].start()] + body.replace(candidates[0], corrected) + original[end:]


def heap_alignment_outputs(generated: Path, overrides: dict[Path, bytes] | None = None) -> tuple[list, dict]:
    """Backport TeaVM's reviewed eight-byte 32-bit heap layout repair.

    The application and class library stay unchanged. This changes only the
    four generated expressions and bundled heap tracer fixed upstream by
    TeaVM #1281, after the exact pinned compiler has produced C.
    """
    overrides = {} if overrides is None else overrides
    if type(overrides) is not dict:
        raise ValueError('unreviewed-teavm-heap-alignment-overrides')
    classes = generated / 'c'
    if classes.is_symlink() or not classes.is_dir():
        raise ValueError('unreviewed-teavm-generated-classes')
    outputs, identities = [], []
    seen_runtime = set()
    entries = total_bytes = scanned = class_sizes = 0
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
        raw = path.read_bytes()
        selected = overrides.get(path, raw)
        if type(selected) is not bytes or path in overrides and hashlib.sha256(raw).digest() == hashlib.sha256(selected).digest():
            raise ValueError('unreviewed-teavm-heap-alignment-overrides')
        original = selected.decode('utf-8')
        adapted, count = CLASS_SIZE_ALIGNMENT.subn(r'\g<1>8\g<2>', original)
        class_sizes += count
        relative = path.relative_to(generated).as_posix()
        if relative in HEAP_ALIGNMENT_RUNTIME:
            adapted = _aligned_runtime_function(adapted, HEAP_ALIGNMENT_RUNTIME[relative])
            seen_runtime.add(relative)
        if adapted == original:
            continue
        value = adapted.encode('utf-8')
        outputs.append((path, value))
        identities.append({'path': relative, 'upstreamSha256': hashlib.sha256(raw).hexdigest(),
            'adaptedSha256': hashlib.sha256(value).hexdigest(), 'classSizeAlignments': count,
            'runtimeArrayAlignment': relative in HEAP_ALIGNMENT_RUNTIME})
    if seen_runtime != set(HEAP_ALIGNMENT_RUNTIME) or class_sizes <= 0:
        raise ValueError('unreviewed-teavm-heap-alignment-closure')

    heaptrace = generated / 'heaptrace.c'
    if heaptrace.is_symlink() or not heaptrace.is_file() or heaptrace.stat().st_size > 65536:
        raise ValueError('unreviewed-teavm-heap-alignment-heaptrace')
    heaptrace_raw = heaptrace.read_bytes()
    heaptrace_source = heaptrace_raw.decode('utf-8')
    before = '    size = TEAVM_ALIGN(size, sizeof(void*));'
    after = '    size = TEAVM_ALIGN(size, 8);'
    if heaptrace_source.count(before) != 1:
        raise ValueError('unreviewed-teavm-heap-alignment-heaptrace')
    heaptrace_value = heaptrace_source.replace(before, after).encode('utf-8')
    outputs.append((heaptrace, heaptrace_value))
    identities.append({'path': 'heaptrace.c', 'upstreamSha256': hashlib.sha256(heaptrace_raw).hexdigest(),
        'adaptedSha256': hashlib.sha256(heaptrace_value).hexdigest(), 'classSizeAlignments': 0,
        'runtimeArrayAlignment': True})
    outputs.sort(key=lambda item: item[0].relative_to(generated).as_posix())
    identities.sort(key=lambda item: item['path'])
    return outputs, {'profile': 'teavm-0.15-wasm32-eight-byte-heap-alignment-v1',
        'upstreamFix': HEAP_ALIGNMENT_FIX, 'scannedClasses': scanned,
        'classSizeAlignments': class_sizes, 'files': identities}


def _generated_function(original: str, function: str) -> tuple[int, int, str]:
    signatures = list(re.finditer(
        r'(?m)^[^\r\n{};]*\b' + re.escape(function) + r'\([^;\r\n]*\) \{\r?$', original))
    if len(signatures) != 1:
        raise ValueError('unreviewed-teavm-monitor-root-function')
    closing = re.search(r'(?m)^}\r?$', original[signatures[0].end():])
    if closing is None:
        raise ValueError('unreviewed-teavm-monitor-root-function')
    end = signatures[0].end() + closing.end()
    return signatures[0].start(), end, original[signatures[0].start():end]


def _field_edge_diagnostics() -> str:
    """Encode one bad parent-class index and field offset in bounded frames."""
    lines = [
        'static volatile int32_t teavm_field_edge_trap_value;',
        '__attribute__((noinline)) static void teavm_field_edge_trap_out_of_range(void) {',
        '    teavm_field_edge_trap_value = INT32_C(-2);',
        '    __builtin_trap();',
        '}',
    ]
    for digit in range(16):
        lines.extend((
            f'__attribute__((noinline)) static void teavm_field_edge_field_low_{digit:x}(void) {{',
            f'    teavm_field_edge_trap_value = INT32_C({digit});',
            '    if (teavm_field_edge_trap_value != INT32_C(-1)) {',
            '        __builtin_trap();',
            '    }',
            '}',
        ))
    for prefix, shift, callee in (
            ('field_high', 0, 'field_low'),
            ('parent_low', 4, 'field_high'),
            ('parent_mid', 0, 'parent_low'),
            ('parent_high', 4, 'parent_mid')):
        for digit in range(16):
            argument = ('teavm_field' if prefix in ('field_high', 'parent_low')
                        else 'teavm_parent')
            passed = ('' if prefix == 'field_high' else
                      'teavm_field' if prefix == 'parent_low' else
                      'teavm_parent, teavm_field')
            signature = ('int32_t teavm_field' if prefix == 'field_high' else
                         'int32_t teavm_parent, int32_t teavm_field')
            lines.append(
                f'__attribute__((noinline)) static void teavm_field_edge_{prefix}_{digit:x}({signature}) {{')
            lines.append(f'    switch (({argument} >> INT32_C({shift})) & INT32_C(15)) {{')
            for next_digit in range(16):
                lines.append(
                    f'        case INT32_C({next_digit}): teavm_field_edge_{callee}_{next_digit:x}({passed}); break;')
            lines.extend((
                '        default: teavm_field_edge_trap_out_of_range();',
                '    }',
                f'    teavm_field_edge_trap_value = INT32_C({digit});',
                '}',
            ))
    lines.extend((
        '__attribute__((noinline)) static void teavm_field_edge_diagnose(',
        '        int32_t teavm_parent, int32_t teavm_field) {',
        '    if (teavm_parent < INT32_C(0) || teavm_parent > INT32_C(4095)',
        '            || teavm_field < INT32_C(0) || teavm_field > INT32_C(255)) {',
        '        teavm_field_edge_trap_out_of_range();',
        '    }',
        '    switch ((teavm_parent >> INT32_C(8)) & INT32_C(15)) {',
    ))
    for digit in range(16):
        lines.append(
            f'        case INT32_C({digit}): teavm_field_edge_parent_high_{digit:x}(teavm_parent, teavm_field); break;')
    lines.extend((
        '        default: teavm_field_edge_trap_out_of_range();',
        '    }',
        '    teavm_field_edge_trap_value = INT32_C(-3);',
        '}',
        '',
    ))
    return '\n'.join(lines)


def monitor_root_outputs(generated: Path, overrides: dict[Path, bytes] | None = None) -> tuple[list, dict]:
    """Keep packed Object.Monitor references live and relocation-correct.

    TeaVM stores a monitor only in the tagged object-header hash. The 0.15 C
    collector visits generated class layouts but neither marks that header
    reference nor rewrites it after compaction. Patch only those two generated
    collector boundaries; application, class library and monitor queues remain
    unchanged.
    """
    overrides = {} if overrides is None else overrides
    if type(overrides) is not dict:
        raise ValueError('unreviewed-teavm-monitor-root-overrides')
    path = generated / 'c/o/t/r/GC.c'
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 16 * 1024 * 1024:
        raise ValueError('unreviewed-teavm-monitor-root-source')
    raw = path.read_bytes()
    selected = overrides.get(path, raw)
    if type(selected) is not bytes or path in overrides and selected == raw:
        raise ValueError('unreviewed-teavm-monitor-root-overrides')
    original = selected.decode('utf-8')

    start, end, body = _generated_function(original, 'meth_otr_GC_markObjectData')
    diagnostics = '''static volatile int32_t teavm_monitor_root_trap_kind;
__attribute__((noinline)) static void teavm_monitor_root_trap_below_heap(void) {
    teavm_monitor_root_trap_kind = INT32_C(1);
    __builtin_trap();
}
__attribute__((noinline)) static void teavm_monitor_root_trap_past_heap(void) {
    teavm_monitor_root_trap_kind = INT32_C(2);
    __builtin_trap();
}
__attribute__((noinline)) static void teavm_monitor_root_trap_truncated_header(void) {
    teavm_monitor_root_trap_kind = INT32_C(3);
    __builtin_trap();
}
__attribute__((noinline)) static void teavm_monitor_root_trap_misaligned(void) {
    teavm_monitor_root_trap_kind = INT32_C(4);
    __builtin_trap();
}
__attribute__((noinline)) static void teavm_monitor_root_trap_free_chunk(void) {
    teavm_monitor_root_trap_kind = INT32_C(5);
    __builtin_trap();
}
__attribute__((noinline)) static void teavm_monitor_root_trap_unknown_class(void) {
    teavm_monitor_root_trap_kind = INT32_C(6);
    __builtin_trap();
}
static int32_t teavm_gc_candidate_has_known_class(void* teavm_candidate) {
    TeaVM_Class* teavm_candidate_class = meth_otr_RuntimeClass_getClass(teavm_candidate);
    int32_t teavm_class_index;
    for (teavm_class_index = INT32_C(0); teavm_class_index < teavm_classReferencesCount;
            ++teavm_class_index) {
        if (teavm_classReferences[teavm_class_index] == teavm_candidate_class) {
            return INT32_C(1);
        }
    }
    return INT32_C(0);
}
static int32_t teavm_gc_candidate_is_valid_unknown_class(void* teavm_candidate) {
    if (teavm_candidate == NULL
            || (uintptr_t) teavm_candidate < (uintptr_t) teavm_gc_heapAddress
            || (uintptr_t) teavm_candidate >= (uintptr_t) TEAVM_ADDRESS_ADD(
                teavm_gc_heapAddress, teavm_gc_availableBytes)
            || (uintptr_t) TEAVM_ADDRESS_ADD(teavm_candidate, sizeof(TeaVM_Object)) >
                (uintptr_t) TEAVM_ADDRESS_ADD(teavm_gc_heapAddress, teavm_gc_availableBytes)
            || (((uintptr_t) teavm_candidate - (uintptr_t) teavm_gc_heapAddress)
                & (INT32_C(8) - INT32_C(1))) != 0
            || TEAVM_FIELD(teavm_candidate, cls_otr_FreeChunk, fld_classReference) == INT32_C(0)) {
        return INT32_C(0);
    }
    return !teavm_gc_candidate_has_known_class(teavm_candidate);
}
static int32_t teavm_gc_known_class_index(void* teavm_class) {
    int32_t teavm_class_index;
    for (teavm_class_index = INT32_C(0); teavm_class_index < teavm_classReferencesCount;
            ++teavm_class_index) {
        if (teavm_classReferences[teavm_class_index] == teavm_class) {
            return teavm_class_index;
        }
    }
    return INT32_C(-1);
}
'''
    declaration = '    void* teavm_local_2;\n'
    class_read = '    teavm_local_2 = meth_otr_RuntimeClass_getClass(teavm_local_1);\n'
    object_return = '        return meth_otr_GC_markObject(teavm_local_2, teavm_local_1);'
    array_return = '    return meth_otr_GC_markArray(teavm_local_2, teavm_local_1);'
    if any(body.count(value) != 1 for value in (declaration, class_read, object_return, array_return)):
        raise ValueError('unreviewed-teavm-monitor-root-mark')
    body = body.replace(declaration, declaration
        + '    void* teavm_monitor;\n    int32_t teavm_marked_monitor;\n')
    body = body.replace(class_read,
        '    teavm_monitor = TEAVM_UNPACK_MONITOR(TEAVM_FIELD(teavm_local_1, TeaVM_Object, hash));\n'
        '    if (teavm_monitor != NULL) {\n'
        '        if ((uintptr_t) teavm_monitor < (uintptr_t) teavm_gc_heapAddress) {\n'
        '            teavm_monitor_root_trap_below_heap();\n'
        '        }\n'
        '        if ((uintptr_t) teavm_monitor >= (uintptr_t) TEAVM_ADDRESS_ADD(\n'
        '                teavm_gc_heapAddress, teavm_gc_availableBytes)) {\n'
        '            teavm_monitor_root_trap_past_heap();\n'
        '        }\n'
        '        if ((uintptr_t) TEAVM_ADDRESS_ADD(teavm_monitor, sizeof(TeaVM_Object)) >\n'
        '                (uintptr_t) TEAVM_ADDRESS_ADD(teavm_gc_heapAddress, teavm_gc_availableBytes)) {\n'
        '            teavm_monitor_root_trap_truncated_header();\n'
        '        }\n'
        '        if ((((uintptr_t) teavm_monitor - (uintptr_t) teavm_gc_heapAddress) &\n'
        '                (INT32_C(8) - INT32_C(1))) != 0) {\n'
        '            teavm_monitor_root_trap_misaligned();\n'
        '        }\n'
        '        if (TEAVM_FIELD(teavm_monitor, cls_otr_FreeChunk, fld_classReference) == INT32_C(0)) {\n'
        '            teavm_monitor_root_trap_free_chunk();\n'
        '        }\n'
        '        if (!teavm_gc_candidate_has_known_class(teavm_monitor)) {\n'
        '            teavm_monitor_root_trap_unknown_class();\n'
        '        }\n'
        '    }\n'
        '    teavm_marked_monitor = teavm_monitor != NULL\n'
        '        ? meth_otr_GC_enqueueMark(teavm_monitor) : INT32_C(0);\n' + class_read)
    body = body.replace(object_return,
        '        return teavm_marked_monitor | meth_otr_GC_markObject(teavm_local_2, teavm_local_1);')
    body = body.replace(array_return,
        '    return teavm_marked_monitor | meth_otr_GC_markArray(teavm_local_2, teavm_local_1);')
    adapted = original[:start] + diagnostics + body + original[end:]

    start, end, body = _generated_function(adapted, 'meth_otr_GC_enqueueMark')
    marked = '    if ((!meth_otr_GC_isMarked(teavm_local_1))) {\n'
    if body.count(marked) != 1:
        raise ValueError('unreviewed-teavm-enqueued-root-mark')
    enqueued_diagnostics = '''static volatile int32_t teavm_enqueued_root_trap_kind;
__attribute__((noinline)) static void teavm_enqueued_root_trap_below_heap(void) {
    teavm_enqueued_root_trap_kind = INT32_C(1);
    __builtin_trap();
}
__attribute__((noinline)) static void teavm_enqueued_root_trap_past_heap(void) {
    teavm_enqueued_root_trap_kind = INT32_C(2);
    __builtin_trap();
}
__attribute__((noinline)) static void teavm_enqueued_root_trap_truncated_header(void) {
    teavm_enqueued_root_trap_kind = INT32_C(3);
    __builtin_trap();
}
__attribute__((noinline)) static void teavm_enqueued_root_trap_misaligned(void) {
    teavm_enqueued_root_trap_kind = INT32_C(4);
    __builtin_trap();
}
__attribute__((noinline)) static void teavm_enqueued_root_trap_free_chunk(void) {
    teavm_enqueued_root_trap_kind = INT32_C(5);
    __builtin_trap();
}
__attribute__((noinline)) static void teavm_enqueued_root_trap_unknown_class(void) {
    teavm_enqueued_root_trap_kind = INT32_C(6);
    __builtin_trap();
}
'''
    validation = (
        '    if ((uintptr_t) teavm_local_1 < (uintptr_t) teavm_gc_heapAddress) {\n'
        '        teavm_enqueued_root_trap_below_heap();\n'
        '    }\n'
        '    if ((uintptr_t) teavm_local_1 >= (uintptr_t) TEAVM_ADDRESS_ADD(\n'
        '            teavm_gc_heapAddress, teavm_gc_availableBytes)) {\n'
        '        teavm_enqueued_root_trap_past_heap();\n'
        '    }\n'
        '    if ((uintptr_t) TEAVM_ADDRESS_ADD(teavm_local_1, sizeof(TeaVM_Object)) >\n'
        '            (uintptr_t) TEAVM_ADDRESS_ADD(teavm_gc_heapAddress, teavm_gc_availableBytes)) {\n'
        '        teavm_enqueued_root_trap_truncated_header();\n'
        '    }\n'
        '    if ((((uintptr_t) teavm_local_1 - (uintptr_t) teavm_gc_heapAddress) &\n'
        '            (INT32_C(8) - INT32_C(1))) != 0) {\n'
        '        teavm_enqueued_root_trap_misaligned();\n'
        '    }\n'
        '    if (TEAVM_FIELD(teavm_local_1, cls_otr_FreeChunk, fld_classReference) == INT32_C(0)) {\n'
        '        teavm_enqueued_root_trap_free_chunk();\n'
        '    }\n'
        '    if (!teavm_gc_candidate_has_known_class(teavm_local_1)) {\n'
        '        teavm_enqueued_root_trap_unknown_class();\n'
        '    }\n')
    body = body.replace(marked, validation + marked)
    adapted = adapted[:start] + enqueued_diagnostics + body + adapted[end:]

    start, end, body = _generated_function(adapted, 'meth_otr_GC_markFields')
    declaration = '    int32_t teavm_local_7;\n'
    edge = ('        teavm_local_4 = (teavm_local_4 | meth_otr_GC_enqueueMark('
            '(*(void**) TEAVM_ADDRESS_ADD(teavm_local_2, teavm_local_7))));\n')
    if body.count(declaration) != 1 or body.count(edge) != 1:
        raise ValueError('unreviewed-teavm-field-edge-mark')
    body = body.replace(declaration, declaration
        + '    void* teavm_field_edge_candidate;\n'
        + '    int32_t teavm_field_edge_parent;\n')
    body = body.replace(edge,
        '        teavm_field_edge_candidate = (*(void**) TEAVM_ADDRESS_ADD(\n'
        '            teavm_local_2, teavm_local_7));\n'
        '        if (teavm_gc_candidate_is_valid_unknown_class(teavm_field_edge_candidate)) {\n'
        '            teavm_field_edge_parent = teavm_gc_known_class_index(teavm_local_1);\n'
        '            teavm_field_edge_diagnose(teavm_field_edge_parent, teavm_local_7);\n'
        '        }\n'
        '        teavm_local_4 = (teavm_local_4 |\n'
        '            meth_otr_GC_enqueueMark(teavm_field_edge_candidate));\n')
    adapted = adapted[:start] + _field_edge_diagnostics() + body + adapted[end:]

    start, end, body = _generated_function(adapted, 'meth_otr_GC_updatePointers')
    opening = 'void meth_otr_GC_updatePointers(void* teavm_local_1, void* teavm_local_2) {\n'
    branch = '    if ((TEAVM_FIELD(teavm_local_1, TeaVM_Class, itemType) == NULL)) {'
    if body.count(opening) != 1 or body.count(branch) != 1:
        raise ValueError('unreviewed-teavm-monitor-root-relocation')
    body = body.replace(opening, opening
        + '    int32_t teavm_monitor_hash;\n    void* teavm_monitor;\n'
        + '    teavm_monitor_hash = TEAVM_FIELD(teavm_local_2, TeaVM_Object, hash);\n'
        + '    teavm_monitor = TEAVM_UNPACK_MONITOR(teavm_monitor_hash);\n'
        + '    if (teavm_monitor != NULL) {\n'
        + '        TEAVM_FIELD(teavm_local_2, TeaVM_Object, hash) =\n'
        + '            TEAVM_PACK_MONITOR(meth_otr_GC_updatePointer(teavm_monitor));\n'
        + '    }\n')
    adapted = adapted[:start] + body + adapted[end:]
    value = adapted.encode('utf-8')
    if value == selected:
        raise ValueError('unreviewed-teavm-monitor-root-closure')
    return [(path, value)], {
        'profile': 'teavm-0.15-c-packed-monitor-gc-root-v4',
        'upstreamIssue': MONITOR_ROOT_ISSUE,
        'path': 'c/o/t/r/GC.c',
        'upstreamSha256': hashlib.sha256(raw).hexdigest(),
        'inputSha256': hashlib.sha256(selected).hexdigest(),
        'adaptedSha256': hashlib.sha256(value).hexdigest(),
        'markPackedMonitor': True,
        'rewriteRelocatedMonitor': True,
        'boundedPackedMonitorValidityTraps': True,
        'packedMonitorValidityTrapKinds': 6,
        'boundedEnqueuedReferenceValidityTraps': True,
        'enqueuedReferenceValidityTrapKinds': 6,
        'boundedFieldEdgeIdentityFrames': True,
        'fieldEdgeParentClassIndexMaximum': 4095,
        'fieldEdgeOffsetMaximum': 255,
    }


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
    spill_map = dict(spill_outputs)
    alignment_outputs, alignment_receipt = heap_alignment_outputs(generated, spill_map)
    alignment_paths = {path for path, _value in alignment_outputs}
    monitor_outputs, monitor_receipt = monitor_root_outputs(generated, dict(alignment_outputs))
    monitor_paths = {path for path, _value in monitor_outputs}
    memory = originals['memory.c'].replace('#if TEAVM_UNIX\n', '#if TEAVM_UNIX && !defined(LSF_TEAVM_WASM)\n', 1)
    memory = memory.replace('#if defined(__EMSCRIPTEN__)', MEMORY, 1)
    outputs = {'fiber.c': FIBER, 'time.c': CLOCK, 'memory.c': memory, 'file.c': FILESYSTEM,
               'arrayclass.c': aligned_array_classes(originals['arrayclass.c'])}
    for name, value in outputs.items():
        (generated / name).write_text(value, encoding='utf-8', newline='\n')
    for path, value in spill_outputs:
        if path in alignment_paths:
            continue
        path.write_bytes(value)
    for path, value in alignment_outputs:
        if path in monitor_paths:
            continue
        path.write_bytes(value)
    for path, value in monitor_outputs:
        path.write_bytes(value)
    receipt = {name: {'upstreamSha256': PREIMAGES[name],
                     'adaptedSha256': hashlib.sha256(value.encode()).hexdigest()}
               for name, value in outputs.items()}
    receipt['referenceSpills'] = spill_receipt
    receipt['heapAlignment'] = alignment_receipt
    receipt['monitorRoots'] = monitor_receipt
    return receipt
