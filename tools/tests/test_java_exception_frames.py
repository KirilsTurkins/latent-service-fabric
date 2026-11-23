"""Storage lifetime controls; native C tests do not qualify signed Java guests."""
from pathlib import Path
import hashlib
import re
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from tools.java_guest import enum_guard as guard

FIXTURES = Path(__file__).with_name('fixtures')
HEADER = (FIXTURES / 'teavm_0_15_exceptions.h').read_bytes()
PROGRAM = (FIXTURES / 'java_exception_frames.c').read_bytes()
CORE = '''#pragma once
#include <stdint.h>
#include <stddef.h>
#include <stdlib.h>
#include <setjmp.h>
typedef struct TeaVM_LongjmpDesc {
    jmp_buf buffer;
    struct TeaVM_LongjmpDesc *previous;
} TeaVM_LongjmpDesc;
typedef struct TeaVM_StackFrame {
    struct TeaVM_StackFrame *next;
    TeaVM_LongjmpDesc *jmpTarget;
} TeaVM_StackFrame;
static TeaVM_StackFrame *teavm_stackTop;
#define TEAVM_ALLOC_STACK(n) struct { TeaVM_StackFrame header; } teavm_shadowStack = {{teavm_stackTop, NULL}}; teavm_stackTop = &teavm_shadowStack.header
#define TEAVM_RELEASE_STACK (teavm_stackTop = teavm_shadowStack.header.next)
#define TEAVM_ARRAY_LENGTH(array) 0
static void teavm_throwNullPointerException(void) { abort(); }
static void teavm_throwArrayIndexOutOfBoundsException(void) { abort(); }
'''
SIMPLE = b'''void example(void) {
    TEAVM_ALLOC_STACK(INT32_C(0));
    TEAVM_TRY
        work();
    TEAVM_CATCH
        case 1: break;
    TEAVM_END_TRY
    TEAVM_RELEASE_STACK;
}
'''


class ExceptionFrameControls(unittest.TestCase):
    def stage(self, root, source=PROGRAM):
        (root / 'c').mkdir()
        (root / 'c/control.c').write_bytes(source)
        (root / 'exceptions.h').write_bytes(HEADER)
        (root / 'definitions.h').write_text('#define TEAVM_USE_SETJMP 1\n#define TEAVM_UNIX 1\n')
        (root / 'core.h').write_text(CORE)
        (root / 'all.c').write_text('#define _XOPEN_SOURCE\n#define __USE_XOPEN\n'
                                   '#define _GNU_SOURCE\n#include "c/control.c"\n')

    def test_exact_upstream_header_and_all_unchanged_dispatch_macros(self):
        self.assertEqual(hashlib.sha256(HEADER).hexdigest(), guard.EXCEPTION_HEADER_SHA256)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.stage(root)
            receipt = guard.compact_exception_frames(root)
            adapted = (root / 'exceptions.h').read_bytes()
            self.assertEqual(adapted.replace(b'\n' + guard.EXCEPTION_TRY_SLOT.encode(), b''), HEADER)
            self.assertEqual(receipt['handlerSites'], sum(line.strip() == b'TEAVM_TRY' for line in PROGRAM.splitlines()))
            self.assertLess(receipt['functionLocalSlots'], receipt['handlerSites'])
            self.assertNotEqual(receipt['sourceBeforeSha256'], receipt['sourceAfterSha256'])
            with self.assertRaisesRegex(ValueError, 'header-preimage'):
                guard.compact_exception_frames(root)

    def test_only_nesting_not_number_of_sequential_sites_reserves_storage(self):
        block = SIMPLE[SIMPLE.index(b'    TEAVM_TRY'):SIMPLE.index(b'    TEAVM_RELEASE_STACK;')]
        source = SIMPLE.replace(block, block * 2)
        adapted, rows = guard.exception_frame_source(source)
        self.assertEqual([(r['sites'], r['slots']) for r in rows], [(2, 1)])
        restored = re.sub(rb'^    TeaVM_LongjmpDesc lsf_teavm_jump_frame_[0-9]+;\n', b'', adapted, flags=re.M)
        restored = re.sub(rb'LSF_TEAVM_TRY_SLOT\(lsf_teavm_jump_frame_[0-9]+\)', b'TEAVM_TRY', restored)
        self.assertEqual(restored, source)
        with self.assertRaisesRegex(ValueError, 'already-adapted'):
            guard.exception_frame_source(adapted)

    def test_literals_and_comments_cannot_change_scope_or_be_rewritten(self):
        note = b'    /* } TEAVM_TRY */\n    const char *s = "} TEAVM_CATCH \\\""; // TEAVM_END_TRY\n'
        source = SIMPLE.replace(b'    work();', note + b'    work();')
        adapted, rows = guard.exception_frame_source(source)
        self.assertIn(note, adapted)
        self.assertEqual(rows[0]['sites'], 1)

    def test_rejects_malformed_unscoped_or_ambiguous_emitter_shapes(self):
        variants = [
            SIMPLE.replace(b'TEAVM_CATCH', b'TEAVM_END_TRY', 1),
            SIMPLE.replace(b'TEAVM_END_TRY\n', b'', 1),
            SIMPLE.replace(b'TEAVM_TRY\n', b'TEAVM_TRY work();\n', 1),
            SIMPLE.replace(b'    TEAVM_ALLOC_STACK(INT32_C(0));\n', b''),
            SIMPLE.replace(b'    TEAVM_ALLOC_STACK(INT32_C(0));\n', b'    TEAVM_ALLOC_STACK(INT32_C(0));\n' * 2),
            SIMPLE + b'TEAVM_TRY\n', SIMPLE + b'/* unterminated',
            SIMPLE + b'"unterminated', SIMPLE.replace(b'work();', b'work();\\\n'),
            SIMPLE.replace(b'work();', b'int lsf_teavm_jump_frame_0;'),
            SIMPLE.replace(b'void example(void) {', b'void example(void){'),
        ]
        for raw in variants:
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                guard.exception_frame_source(raw)

    def test_rejects_changed_header_and_late_bad_source_before_any_write(self):
        for mutation in ('header', 'late-source'):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                self.stage(root)
                if mutation == 'header':
                    (root / 'exceptions.h').write_bytes(HEADER.replace(b'->previous', b'->changed', 1))
                else:
                    (root / 'c/z.c').write_bytes(SIMPLE.replace(b'TEAVM_CATCH', b'TEAVM_END_TRY', 1))
                    with (root / 'all.c').open('a') as stream: stream.write('#include "c/z.c"\n')
                before = {p: p.read_bytes() for p in root.rglob('*') if p.is_file()}
                with self.assertRaises(ValueError): guard.compact_exception_frames(root)
                self.assertEqual(before, {p: p.read_bytes() for p in before})

    def test_source_change_during_planning_is_not_accepted(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.stage(root)
            original = guard.exception_frame_source
            def changed(raw):
                result = original(raw)
                if raw == PROGRAM: (root / 'core.h').write_text(CORE + '\n/* changed */\n')
                return result
            with patch.object(guard, 'exception_frame_source', side_effect=changed), \
                    self.assertRaisesRegex(ValueError, 'source-drift'):
                guard.compact_exception_frames(root)
            self.assertEqual((root / 'exceptions.h').read_bytes(), HEADER)
            self.assertEqual((root / 'c/control.c').read_bytes(), PROGRAM)

    def compile_control(self, root):
        compiler = shutil.which('cc') or shutil.which('clang')
        self.assertIsNotNone(compiler, 'the C exception lifetime controls require a C compiler')
        executable = root / 'control'
        compiled = subprocess.run([compiler, '-std=c11', '-O2', '-I', str(root),
                                   str(root / 'c/control.c'), '-o', str(executable)],
                                  capture_output=True, timeout=30, check=False)
        self.assertEqual(compiled.returncode, 0, compiled.stderr.decode())
        return subprocess.run([str(executable)], capture_output=True, timeout=5, check=False)

    def test_real_setjmp_preserves_rethrow_recursion_explicit_exit_and_fresh_frames(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.stage(root)
            baseline = self.compile_control(root)
            self.assertEqual(baseline.returncode, 0, baseline.stderr.decode())
            guard.compact_exception_frames(root)
            candidate = self.compile_control(root)
            self.assertEqual(candidate.returncode, 0, candidate.stderr.decode())
            self.assertEqual(candidate.stdout, baseline.stdout)
            self.assertIn(b'fresh-frame: passed', candidate.stdout)

    def test_reusing_a_live_outer_slot_is_rejected_by_the_native_control(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.stage(root)
            guard.compact_exception_frames(root)
            source = root / 'c/control.c'
            source.write_bytes(source.read_bytes().replace(b'LSF_TEAVM_TRY_SLOT(lsf_teavm_jump_frame_1)', b'LSF_TEAVM_TRY_SLOT(lsf_teavm_jump_frame_0)'))
            result = self.compile_control(root)
            self.assertNotEqual(result.returncode, 0)


if __name__ == '__main__': unittest.main()
