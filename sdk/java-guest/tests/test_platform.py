"""Wasm32 class-pointer layout adaptation, not evidence of guest execution."""
import importlib.util
from pathlib import Path
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


if __name__ == '__main__':
    unittest.main()
