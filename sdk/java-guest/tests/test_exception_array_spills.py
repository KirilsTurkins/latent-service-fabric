"""Reviewed pinned array references, preserving the historical v1 guards."""
import hashlib
import importlib.util
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('array_spill_platform',
    Path(__file__).resolve().parents[1] / 'tools/teavm_platform.py')
platform = importlib.util.module_from_spec(spec)
spec.loader.exec_module(platform)


class ArrayExceptionSpills(unittest.TestCase):
    def test_exact_reviewed_reference_declarations_preserve_scalar_saves(self):
        original = ('void probe(void) {\n    volatile TeaVM_Array* teavm_spill_1;\n'
                    '    volatile void* teavm_spill_2;\n    volatile int32_t teavm_spill_3;\n'
                    '    TeaVM_Array* teavm_local_1;\n    teavm_spill_1 = teavm_local_1;\n'
                    '    teavm_local_1 = teavm_spill_1;\n}\n')
        adapted, count = platform.reference_spills(original, array_references=True)
        self.assertEqual(count, 2)
        self.assertEqual(adapted, original.replace('volatile TeaVM_Array*', 'TeaVM_Array* volatile')
                         .replace('volatile void*', 'void* volatile'))

    def test_historical_profile_still_rejects_array_declarations(self):
        with self.assertRaisesRegex(ValueError, 'unreviewed-teavm-exception-spill'):
            platform.reference_spills('    volatile TeaVM_Array* teavm_spill_1;\n')

    def test_array_profile_keeps_unknown_and_previously_adapted_declarations_closed(self):
        for declaration in ('    volatile OtherArray* teavm_spill_1;',
                            '    volatile TeaVM_Array * teavm_spill_1;',
                            '    TeaVM_Array* volatile teavm_spill_1;',
                            '    volatile uint32_t teavm_spill_1;',
                            '\tvolatile TeaVM_Array* teavm_spill_1;',
                            '    volatile TeaVM_Array* teavm_spill_1; ',
                            '    volatile TeaVM_Array* teavm_spill_1;\r'):
            with self.subTest(declaration=declaration):
                with self.assertRaisesRegex(ValueError, 'unreviewed-teavm-exception-spill'):
                    platform.reference_spills(declaration + '\n', array_references=True)

    def test_array_profile_records_original_and_derived_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'c/ByteArray.c'
            source.parent.mkdir()
            original = b'    volatile TeaVM_Array* teavm_spill_1;\n'
            source.write_bytes(original)
            outputs, receipt = platform.reference_spill_outputs(root, array_references=True)
            adapted = b'    TeaVM_Array* volatile teavm_spill_1;\n'
            self.assertEqual(outputs, [(source, adapted)])
            self.assertEqual(source.read_bytes(), original)
            self.assertEqual(receipt, {'profile': 'teavm-0.15-wasm-sjlj-reference-spills-v2',
                'scannedClasses': 1, 'pointerSpills': 1,
                'files': [{'path': 'c/ByteArray.c',
                    'upstreamSha256': hashlib.sha256(original).hexdigest(),
                    'adaptedSha256': hashlib.sha256(adapted).hexdigest(), 'pointerSpills': 1}]})

    def test_array_profile_validates_later_classes_before_any_file_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'c').mkdir()
            original = b'    volatile TeaVM_Array* teavm_spill_1;\n'
            first, later = root / 'c/A.c', root / 'c/Z.c'
            first.write_bytes(original)
            later.write_bytes(b'    volatile OtherArray* teavm_spill_1;\n')
            with self.assertRaisesRegex(ValueError, 'unreviewed-teavm-exception-spill'):
                platform.reference_spill_outputs(root, array_references=True)
            self.assertEqual(first.read_bytes(), original)
            self.assertEqual(later.read_bytes(), b'    volatile OtherArray* teavm_spill_1;\n')


if __name__ == '__main__':
    unittest.main()
