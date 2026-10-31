"""Wasm32 class-pointer layout adaptation, not evidence of guest execution."""
import importlib.util
import hashlib
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('teavm_platform',
    Path(__file__).resolve().parents[1] / 'tools/teavm_platform.py')
platform = importlib.util.module_from_spec(spec)
spec.loader.exec_module(platform)


class LayoutTests(unittest.TestCase):
    def test_every_dynamic_class_slot_is_aligned_not_only_the_pool_base(self):
        original = '''static TEAVM_OBJECT_CLASS teavm_dynamicClassPool[TEAVM_DYNAMIC_CLASS_POOL_CAPACITY];
TEAVM_OBJECT_CLASS* ptr = &teavm_dynamicClassPool[teavm_dynamicClassPoolSize++];
return &teavm_dynamicClassPool[index].parent;
'''
        result = platform.aligned_array_classes(original)
        self.assertIn('alignas(8) TEAVM_OBJECT_CLASS value', result)
        self.assertIn('sizeof(LsfArrayClassSlot) % 8 == 0', result)
        self.assertIn('teavm_dynamicClassPool[teavm_dynamicClassPoolSize++].value', result)
        self.assertIn('teavm_dynamicClassPool[index].value.parent', result)
        with self.assertRaisesRegex(ValueError, 'unreviewed-array-class-layout'):
            platform.aligned_array_classes(result)
        with self.assertRaisesRegex(ValueError, 'unreviewed-array-class-layout'):
            platform.aligned_array_classes(original + original)

    def test_wasm32_heap_alignment_backports_exact_upstream_runtime_shapes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            runtime = root / 'c/o/t/r'
            example = root / 'c/example'
            runtime.mkdir(parents=True)
            example.mkdir(parents=True)
            allocator = runtime / 'Allocator.c'
            allocator.write_text('''void* meth_otr_Allocator_allocateArray(void* teavm_local_1, int32_t teavm_local_2) {
    teavm_local_3 = sizeof(void*);
    teavm_local_4 = TEAVM_ALIGN(teavm_local_4, sizeof(void*));
    return teavm_local_5;
}
''')
            gc = runtime / 'GC.c'
            gc.write_text('''int32_t meth_otr_GC_objectSize_0(void* teavm_local_1, void* teavm_local_2) {
    teavm_local_3 = sizeof(void*);
    return ((int32_t) (intptr_t) TEAVM_ALIGN(teavm_local_4, sizeof(void*)));
}
TeaVM_Class cls_otr_GC = {
        .size = (int32_t) (intptr_t) TEAVM_ALIGN(sizeof(cls_otr_GC), sizeof(void*)),
};
''')
            ordinary = example / 'Ordinary.c'
            ordinary.write_text('''TeaVM_Class cls_example = {
        .size = (int32_t) (intptr_t) TEAVM_ALIGN(sizeof(cls_example), sizeof(void*)),
};
void untouched(void) { value = TEAVM_ALIGN(value, sizeof(void*)); }
''')
            (root / 'heaptrace.c').write_text('''int32_t teavm_gc_objectSize(void* address) {
    size = TEAVM_ALIGN(size, sizeof(void*));
    return size;
}
''')
            originals = {path: path.read_bytes() for path in (allocator, gc, ordinary, root / 'heaptrace.c')}
            outputs, receipt = platform.heap_alignment_outputs(root)
            self.assertEqual(receipt['upstreamFix'], platform.HEAP_ALIGNMENT_FIX)
            self.assertEqual(receipt['classSizeAlignments'], 2)
            self.assertEqual(receipt['scannedClasses'], 3)
            self.assertEqual({row['path'] for row in receipt['files']},
                {'c/o/t/r/Allocator.c', 'c/o/t/r/GC.c', 'c/example/Ordinary.c', 'heaptrace.c'})
            self.assertTrue(all(path.read_bytes() == raw for path, raw in originals.items()))
            adapted = dict(outputs)
            self.assertIn('TEAVM_ALIGN(teavm_local_4, INT32_C(8))', adapted[allocator].decode())
            self.assertIn('return ((int32_t) (intptr_t) TEAVM_ALIGN(teavm_local_4, INT32_C(8)))',
                adapted[gc].decode())
            self.assertEqual(adapted[ordinary].decode().count('sizeof(void*)'), 1)
            self.assertIn('TEAVM_ALIGN(sizeof(cls_example), 8)', adapted[ordinary].decode())
            self.assertIn('TEAVM_ALIGN(size, 8)', adapted[root / 'heaptrace.c'].decode())
            self.assertEqual(receipt['files'][0]['upstreamSha256'],
                hashlib.sha256(originals[ordinary]).hexdigest())

    def test_heap_alignment_refuses_missing_or_already_changed_runtime_shapes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'c').mkdir()
            (root / 'heaptrace.c').write_text('size = TEAVM_ALIGN(size, sizeof(void*));\n')
            with self.assertRaisesRegex(ValueError, 'unreviewed-teavm-heap-alignment-closure'):
                platform.heap_alignment_outputs(root)

    def test_packed_monitor_is_marked_and_rewritten_after_relocation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            gc = root / 'c/o/t/r/GC.c'
            gc.parent.mkdir(parents=True)
            gc.write_text('''int32_t meth_otr_GC_markObjectData(void* teavm_local_1) {
    void* teavm_local_2;
    teavm_local_2 = meth_otr_RuntimeClass_getClass(teavm_local_1);
    if ((TEAVM_FIELD(teavm_local_2, TeaVM_Class, itemType) == NULL)) {
        return meth_otr_GC_markObject(teavm_local_2, teavm_local_1);
    }
    return meth_otr_GC_markArray(teavm_local_2, teavm_local_1);
}
int32_t meth_otr_GC_enqueueMark(void* teavm_local_1) {
    if ((teavm_local_1 == NULL)) {
        return INT32_C(0);
    }
    if ((!meth_otr_GC_isMarked(teavm_local_1))) {
        meth_otr_GC_doEnqueueMark(teavm_local_1);
        return INT32_C(1);
    }
    return ((TEAVM_FIELD(teavm_local_1, TeaVM_Object, header) & INT32_C(1073741824))
        ? INT32_C(0) : INT32_C(1));
}
int32_t meth_otr_GC_markFields(void* teavm_local_1, void* teavm_local_2) {
    void* teavm_local_3;
    int32_t teavm_local_4;
    int32_t teavm_local_5;
    int32_t teavm_local_6;
    int32_t teavm_local_7;
    teavm_local_3 = TEAVM_FIELD(teavm_local_1, TeaVM_Class, layout);
    teavm_local_4 = INT32_C(0);
    teavm_local_5 = ((int32_t) *(int16_t*) teavm_local_3);
    while (1) {
        teavm_local_6 = TEAVM_TO_SHORT((teavm_local_5 - INT32_C(1)));
        if ((teavm_local_5 <= INT32_C(0))) break;
        teavm_local_3 = TEAVM_ADDRESS_ADD(teavm_local_3, INT32_C(2));
        teavm_local_7 = ((int32_t) *(int16_t*) teavm_local_3);
        teavm_local_4 = (teavm_local_4 | meth_otr_GC_enqueueMark((*(void**) TEAVM_ADDRESS_ADD(teavm_local_2, teavm_local_7))));
        teavm_local_5 = teavm_local_6;
    }
    return teavm_local_4;
}
void meth_otr_GC_updatePointers(void* teavm_local_1, void* teavm_local_2) {
    if ((TEAVM_FIELD(teavm_local_1, TeaVM_Class, itemType) == NULL)) {
        meth_otr_GC_updatePointersInObject(teavm_local_1, teavm_local_2);
    } else {
        meth_otr_GC_updatePointersInArray(teavm_local_1, teavm_local_2);
    }
}
''', newline='\n')
            original = gc.read_bytes()
            outputs, receipt = platform.monitor_root_outputs(root)
            self.assertEqual(receipt['upstreamIssue'], platform.MONITOR_ROOT_ISSUE)
            self.assertEqual(receipt['profile'], 'teavm-0.15-c-packed-monitor-gc-root-v9')
            self.assertTrue(receipt['markPackedMonitor'])
            self.assertTrue(receipt['rewriteRelocatedMonitor'])
            self.assertTrue(receipt['boundedPackedMonitorValidityTraps'])
            self.assertEqual(receipt['packedMonitorValidityTrapKinds'], 6)
            self.assertTrue(receipt['boundedEnqueuedReferenceValidityTraps'])
            self.assertEqual(receipt['enqueuedReferenceValidityTrapKinds'], 6)
            self.assertTrue(receipt['preMarkedBelowHeapReferencesAccepted'])
            self.assertTrue(receipt['validityChecksOnlyForUnmarkedReferences'])
            self.assertTrue(receipt['dynamicArrayClassesAcceptedByValidityTraps'])
            self.assertEqual(receipt['dynamicArrayClassCountMaximum'], 4096)
            self.assertTrue(receipt['boundedFieldEdgeIdentityFrames'])
            self.assertTrue(receipt['boundedUnmarkedBelowHeapFieldEdgeIdentityFrames'])
            self.assertTrue(receipt['boundedMisalignedFieldEdgeIdentityFrames'])
            self.assertEqual(receipt['fieldEdgeParentClassIndexMaximum'], 4095)
            self.assertEqual(receipt['fieldEdgeOffsetMaximum'], 255)
            self.assertEqual(gc.read_bytes(), original)
            adapted = dict(outputs)[gc].decode()
            self.assertIn('meth_otr_GC_enqueueMark(teavm_monitor)', adapted)
            self.assertEqual(adapted.count('teavm_marked_monitor |'), 2)
            self.assertIn('TEAVM_PACK_MONITOR(meth_otr_GC_updatePointer(teavm_monitor))', adapted)
            for kind in ('below_heap', 'past_heap', 'truncated_header', 'misaligned',
                    'free_chunk', 'unknown_class'):
                self.assertEqual(adapted.count('teavm_monitor_root_trap_' + kind), 2)
            self.assertIn('teavm_gc_candidate_has_known_class(teavm_monitor)', adapted)
            self.assertIn('teavm_gc_candidate_has_known_class(teavm_local_1)', adapted)
            self.assertIn('teavm_classReferencesCount', adapted)
            self.assertIn('extern int teavm_arrayClassCount(void);', adapted)
            self.assertIn('extern TeaVM_Class* teavm_arrayClass(int32_t index);', adapted)
            self.assertIn('teavm_arrayClassCount()', adapted)
            self.assertIn('teavm_arrayClass(teavm_class_index) == teavm_candidate_class', adapted)
            self.assertIn('teavm_dynamic_class_count > INT32_C(4096)', adapted)
            self.assertEqual(adapted.count('teavm_monitor_root_trap_kind = INT32_C('), 6)
            for kind in ('below_heap', 'past_heap', 'truncated_header', 'misaligned',
                    'free_chunk', 'unknown_class'):
                self.assertEqual(adapted.count('teavm_enqueued_root_trap_' + kind), 2)
            self.assertEqual(adapted.count('teavm_enqueued_root_trap_kind = INT32_C('), 6)
            enqueue = platform._generated_function(adapted, 'meth_otr_GC_enqueueMark')[2]
            marked = '    if ((!meth_otr_GC_isMarked(teavm_local_1))) {\n'
            prefix, queued = enqueue.split(marked)
            self.assertEqual(prefix, 'int32_t meth_otr_GC_enqueueMark(void* teavm_local_1) {\n'
                '    if ((teavm_local_1 == NULL)) {\n'
                '        return INT32_C(0);\n'
                '    }\n')
            for kind in ('below_heap', 'past_heap', 'truncated_header', 'misaligned',
                    'free_chunk', 'unknown_class'):
                # Every original guard stays inside the original unmarked branch,
                # before real queue publication; static marked refs keep its fast path.
                self.assertLess(queued.index('teavm_enqueued_root_trap_' + kind + '();'),
                    queued.index('meth_otr_GC_doEnqueueMark(teavm_local_1);'))
            self.assertIn('        if ((((uintptr_t) teavm_local_1 - ', queued)
            self.assertIn('            teavm_enqueued_root_trap_misaligned();\n', queued)
            self.assertIn('teavm_gc_candidate_is_valid_unknown_class(teavm_field_edge_candidate)', adapted)
            self.assertIn('teavm_gc_known_class_index(teavm_local_1)', adapted)
            self.assertIn('teavm_field_edge_diagnose(teavm_field_edge_parent, teavm_local_7)', adapted)
            self.assertIn('teavm_field_edge_unmarked_below_heap_diagnose(', adapted)
            self.assertIn('teavm_field_edge_misaligned_diagnose(', adapted)
            self.assertIn('(uintptr_t) teavm_field_edge_candidate <', adapted)
            self.assertIn('(uintptr_t) teavm_field_edge_candidate >=', adapted)
            self.assertIn('(INT32_C(8) - INT32_C(1))) != 0', adapted)
            self.assertEqual(adapted.count('&& !meth_otr_GC_isMarked('), 2)
            self.assertEqual(adapted.count('__attribute__((noinline)) static void teavm_field_edge_field_low_'), 16)
            self.assertEqual(adapted.count('__attribute__((noinline)) static void teavm_field_edge_field_high_'), 16)
            self.assertEqual(adapted.count('__attribute__((noinline)) static void teavm_field_edge_parent_low_'), 16)
            self.assertEqual(adapted.count('__attribute__((noinline)) static void teavm_field_edge_parent_mid_'), 16)
            self.assertEqual(adapted.count('__attribute__((noinline)) static void teavm_field_edge_parent_high_'), 16)
            self.assertIn('teavm_field_edge_field_low_f();', adapted)
            self.assertIn('teavm_field_edge_field_high_f(teavm_field);', adapted)
            self.assertIn('teavm_field_edge_parent_low_f(teavm_parent, teavm_field);', adapted)

    def test_packed_monitor_repair_refuses_unknown_collector_shapes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            gc = root / 'c/o/t/r/GC.c'
            gc.parent.mkdir(parents=True)
            gc.write_text('void meth_otr_GC_markObjectData(void) { changed(); }\n')
            with self.assertRaisesRegex(ValueError, 'unreviewed-teavm-monitor-root'):
                platform.monitor_root_outputs(root)


if __name__ == '__main__':
    unittest.main()
