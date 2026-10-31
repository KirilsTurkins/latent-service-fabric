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
int32_t meth_otr_GC_markArray(void* teavm_local_1, void* teavm_local_2) {
    void* teavm_local_3;
    int32_t teavm_local_4;
    int32_t teavm_local_5;
    if (meth_otr_RuntimeClass_isPrimitive(TEAVM_FIELD(teavm_local_1, TeaVM_Class, itemType))) {
        return INT32_C(0);
    }
    teavm_local_3 = TEAVM_ALIGN(TEAVM_ADDRESS_ADD(teavm_local_2, INT32_C(1) * sizeof(TeaVM_Array)), sizeof(void*));
    teavm_local_4 = INT32_C(0);
    teavm_local_5 = INT32_C(0);
    while (1) {
        if (!(teavm_local_5 < TEAVM_FIELD(teavm_local_2, TeaVM_Array, size))) break;
        teavm_local_4 = (teavm_local_4 | meth_otr_GC_enqueueMark((*(void**) teavm_local_3)));
        teavm_local_3 = TEAVM_ADDRESS_ADD(teavm_local_3, sizeof(void*));
        teavm_local_5 = (teavm_local_5 + INT32_C(1));
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
            (gc.parent / 'Fiber.h').write_text('typedef struct cls_otr_Fiber {\n    struct TeaVM_Object parent;\n    TeaVM_Array* fld_intValues;\n    int32_t fld_intTop;\n    TeaVM_Array* fld_longValues;\n    int32_t fld_longTop;\n    TeaVM_Array* fld_floatValues;\n    int32_t fld_floatTop;\n    TeaVM_Array* fld_doubleValues;\n    int32_t fld_doubleTop;\n    TeaVM_Array* fld_objectValues;\n    int32_t fld_objectTop;\n    int32_t fld_state;\n    void* fld_runner;\n    void* fld_result;\n    void* fld_exception;\n    int8_t fld_isPendingResume;\n    int8_t fld_daemon;\n} cls_otr_Fiber;\nextern void* sfld_otr_Fiber_current;\nextern void* sfld_otr_Fiber_lastPendingCall;\n', newline='\n')
            (gc.parent / 'Fiber@dPendingCall.h').write_text('typedef struct cls_otr_Fiber_PendingCall {\n    struct TeaVM_Object parent;\n    void* fld_value;\n    void* fld_next;\n    void* fld_previous;\n    void* fld_callback;\n} cls_otr_Fiber_PendingCall;\n', newline='\n')
            (gc.parent / 'Fiber@dAsyncCallbackImpl.h').write_text('typedef struct cls_otr_Fiber_AsyncCallbackImpl {\n    struct TeaVM_Object parent;\n    void* fld_pendingCall;\n    void* fld_javaThread;\n    void* fld_fiber;\n} cls_otr_Fiber_AsyncCallbackImpl;\n', newline='\n')
            original = gc.read_bytes()
            outputs, receipt = platform.monitor_root_outputs(root)
            self.assertEqual(receipt['upstreamIssue'], platform.MONITOR_ROOT_ISSUE)
            self.assertEqual(receipt['profile'], 'teavm-0.15-c-packed-monitor-gc-root-v12')
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
            self.assertTrue(receipt['boundedUnmarkedBelowHeapArrayItemIdentityFrames'])
            self.assertTrue(receipt['arrayItemClassStaticTableOnly'])
            self.assertEqual(receipt['arrayItemIndexMaximum'], 255)
            self.assertTrue(receipt['unavailableArrayItemIdentityUsesOriginalGuard'])
            self.assertTrue(receipt['boundedObjectArrayOwnerLengthIdentityFrames'])
            self.assertEqual(receipt['arrayOwnerFlagsMaximum'], 15)
            self.assertEqual(receipt['arrayOwnerLengthMaximum'], 255)
            self.assertEqual(receipt['arrayOwnerSources'], ['currentFiber', 'directLastPendingFiber'])
            self.assertEqual(receipt['arrayOwnerUnavailableFlags'], [4, 8])
            self.assertTrue(receipt['arrayOwnerHeaderDceOrderedSubsets'])
            self.assertEqual(receipt['arrayOwnerAvailablePaths'], ['currentFiber', 'directLastPendingFiber'])
            self.assertTrue(receipt['arrayOwnerMissingPathUsesUnavailableFlag'])
            self.assertTrue(receipt['arrayOwnerTrapOnly'])
            self.assertTrue(receipt['arrayOwnerOtherShapesUseItemIdentity'])
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
            self.assertEqual(adapted.count('&& !meth_otr_GC_isMarked('), 3)
            self.assertEqual(adapted.count('__attribute__((noinline)) static void teavm_field_edge_field_low_'), 16)
            self.assertEqual(adapted.count('__attribute__((noinline)) static void teavm_field_edge_field_high_'), 16)
            self.assertEqual(adapted.count('__attribute__((noinline)) static void teavm_field_edge_parent_low_'), 16)
            self.assertEqual(adapted.count('__attribute__((noinline)) static void teavm_field_edge_parent_mid_'), 16)
            self.assertEqual(adapted.count('__attribute__((noinline)) static void teavm_field_edge_parent_high_'), 16)
            self.assertIn('teavm_field_edge_field_low_f();', adapted)
            self.assertIn('teavm_field_edge_field_high_f(teavm_field);', adapted)
            self.assertIn('teavm_field_edge_parent_low_f(teavm_parent, teavm_field);', adapted)
            array = platform._generated_function(adapted, 'meth_otr_GC_markArray')[2]
            edge = ('        teavm_local_4 = (teavm_local_4 | '
                'meth_otr_GC_enqueueMark((*(void**) teavm_local_3)));\n')
            self.assertEqual(array.count(edge), 1)
            self.assertIn('teavm_gc_known_class_index(\n'
                '                TEAVM_FIELD(teavm_local_1, TeaVM_Class, itemType))', array)
            self.assertIn('teavm_array_edge_item_class <= INT32_C(4095)', array)
            self.assertIn('teavm_local_5 >= INT32_C(0)', array)
            self.assertIn('teavm_local_5 <= INT32_C(255)', array)
            self.assertIn('&& !meth_otr_GC_isMarked(teavm_array_edge_candidate)', array)
            self.assertLess(array.index('teavm_array_edge_unmarked_below_heap_diagnose('),
                array.index(edge))
            self.assertIn('teavm_array_owner_flags_length_diagnose(', array)
            self.assertLess(array.index('teavm_array_owner_flags_length_diagnose('),
                array.index('teavm_array_edge_unmarked_below_heap_diagnose('))
            self.assertIn('== (TeaVM_Class*) &jl_Object_Cls', array)
            self.assertIn('TeaVM_Array, size) <= INT32_C(255)', array)
            owner = platform._generated_function(adapted, 'teavm_array_owner_flags')[2]
            self.assertNotIn('while', owner)
            self.assertNotIn('for (', owner)
            self.assertIn('sfld_otr_Fiber_current', owner)
            self.assertIn('sfld_otr_Fiber_lastPendingCall', owner)
            self.assertIn('sizeof(cls_otr_Fiber_PendingCall)', owner)
            self.assertIn('sizeof(cls_otr_Fiber_AsyncCallbackImpl)', owner)
            self.assertEqual(owner.count('teavm_array_owner_has_type('), 4)
            # A changed named field cannot silently become a different owner.
            header = gc.parent / 'Fiber@dAsyncCallbackImpl.h'
            reviewed = header.read_bytes()
            header.write_bytes(reviewed.replace(b'fld_fiber', b'fld_other', 1))
            with self.assertRaisesRegex(ValueError, '^unreviewed-teavm-array-owner-header$'):
                platform.monitor_root_outputs(root)
            header.write_bytes(reviewed)
            # The real compiler-cache greeting is linked separately. Its
            # retained fields are reviewed ordered subsets of the GC fixture.
            headers = {name: (gc.parent / name).read_bytes() for name in (
                'Fiber.h', 'Fiber@dPendingCall.h', 'Fiber@dAsyncCallbackImpl.h')}
            removed = {'Fiber.h': b'    TeaVM_Array* fld_doubleValues;\n',
                       'Fiber@dPendingCall.h': b'    void* fld_value;\n',
                       'Fiber@dAsyncCallbackImpl.h': b'    void* fld_javaThread;\n'}
            for name, line in removed.items():
                (gc.parent / name).write_bytes(headers[name].replace(line, b'', 1))
            _, lean = platform.monitor_root_outputs(root)
            self.assertEqual(lean['arrayOwnerAvailablePaths'], ['currentFiber', 'directLastPendingFiber'])
            # Missing read fields/classes are explicit unavailable bits, never
            # an undeclared C include/member access or accepted GC qualification.
            fiber = gc.parent / 'Fiber.h'
            fiber.write_bytes(headers['Fiber.h'].replace(b'    TeaVM_Array* fld_objectValues;\n', b'', 1))
            outputs, lean = platform.monitor_root_outputs(root)
            self.assertEqual(lean['arrayOwnerAvailablePaths'], [])
            lean_source = dict(outputs)[gc].decode()
            self.assertNotIn('#include "Fiber', lean_source)
            self.assertNotIn('sizeof(cls_otr_Fiber', lean_source)
            flags = platform._generated_function(lean_source, 'teavm_array_owner_flags')[2]
            self.assertIn('teavm_flags |= INT32_C(4);', flags)
            self.assertIn('teavm_flags |= INT32_C(8);', flags)
            fiber.write_bytes(headers['Fiber.h'])
            pending = gc.parent / 'Fiber@dPendingCall.h'
            pending.unlink()
            outputs, lean = platform.monitor_root_outputs(root)
            self.assertEqual(lean['arrayOwnerAvailablePaths'], ['currentFiber'])
            lean_source = dict(outputs)[gc].decode()
            self.assertIn('#include "Fiber.h"', lean_source)
            self.assertNotIn('#include "Fiber@d', lean_source)
            self.assertNotIn('cls_otr_Fiber_PendingCall', lean_source)
            # Missing parent and unknown required-field type remain refusals.
            pending.write_bytes(headers['Fiber@dPendingCall.h'])
            for changed in (
                    headers['Fiber.h'].replace(b'    struct TeaVM_Object parent;\n', b'', 1),
                    headers['Fiber.h'].replace(b'TeaVM_Array* fld_objectValues', b'int32_t fld_objectValues', 1)):
                fiber.write_bytes(changed)
                with self.assertRaisesRegex(ValueError, '^unreviewed-teavm-array-owner-header$'):
                    platform.monitor_root_outputs(root)
            for name, raw in headers.items():
                (gc.parent / name).write_bytes(raw)
            # An unreviewed item source must be refused before a diagnostic
            # can attach a misleading class/index identity to the original call.
            gc.write_bytes(original.replace(edge.encode(),
                edge.replace('teavm_local_3', 'teavm_local_4').encode(), 1))
            with self.assertRaisesRegex(ValueError, '^unreviewed-teavm-array-item-mark$'):
                platform.monitor_root_outputs(root)
            gc.write_bytes(original)

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
