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
            self.assertTrue(receipt['markPackedMonitor'])
            self.assertTrue(receipt['rewriteRelocatedMonitor'])
            self.assertEqual(gc.read_bytes(), original)
            adapted = dict(outputs)[gc].decode()
            self.assertIn('meth_otr_GC_enqueueMark(teavm_monitor)', adapted)
            self.assertEqual(adapted.count('teavm_marked_monitor |'), 2)
            self.assertIn('TEAVM_PACK_MONITOR(meth_otr_GC_updatePointer(teavm_monitor))', adapted)

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
