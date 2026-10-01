"""Exact generated C exception reference ownership, not node qualification."""
import hashlib
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('spill_platform',
    Path(__file__).resolve().parents[1] / 'tools/teavm_platform.py')
platform = importlib.util.module_from_spec(spec)
spec.loader.exec_module(platform)


class ExceptionSpills(unittest.TestCase):
    def test_pointer_local_survives_exception_and_scalar_declarations_are_preserved(self):
        original = ('void test(void) {\n    volatile void* teavm_spill_2;\n'
                    '    volatile int32_t teavm_spill_3;\n    volatile int64_t teavm_spill_4;\n'
                    '    volatile float teavm_spill_5;\n    volatile double teavm_spill_6;\n'
                    '    teavm_spill_2 = teavm_local_2;\n    teavm_local_2 = teavm_spill_2;\n}\n')
        result, count = platform.reference_spills(original)
        self.assertEqual(count, 1)
        self.assertEqual(result, original.replace('volatile void*', 'void* volatile'))

    def test_only_generated_spill_declarations_change(self):
        source = ('volatile void* unrelated;\n    volatile void* other_local;\n'
                  '    const char* literal = "volatile void* teavm_spill_2;";\n'
                  '    void* teavm_local_2;\n    volatile void* teavm_spill_2;\n')
        result, count = platform.reference_spills(source)
        self.assertEqual(count, 1)
        self.assertEqual(result, source.replace('    volatile void* teavm_spill_2;\n',
                                               '    void* volatile teavm_spill_2;\n'))

    def test_unknown_pointer_scalar_and_declaration_grammars_fail_closed(self):
        for declaration in ('    volatile TeaVM_Array* teavm_spill_1;',
                            '    volatile void * teavm_spill_1;', '    void* teavm_spill_1;',
                            '    volatile uint32_t teavm_spill_1;',
                            '\tvolatile void* teavm_spill_1;', '    volatile void* teavm_spill_1; ',
                            '    volatile void* teavm_spill_1;\r'):
            with self.subTest(declaration=declaration):
                with self.assertRaisesRegex(ValueError, 'unreviewed-teavm-exception-spill'):
                    platform.reference_spills(declaration + '\n')

    def test_repeated_pointer_port_is_rejected(self):
        adapted, _ = platform.reference_spills('    volatile void* teavm_spill_1;\n')
        with self.assertRaisesRegex(ValueError, 'unreviewed-teavm-exception-spill'):
            platform.reference_spills(adapted)

    def test_receipt_binds_actual_original_and_derived_class_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'c/example/Original.c'
            source.parent.mkdir(parents=True)
            original = b'void original(void) {\n    volatile void* teavm_spill_2;\n}\n'
            source.write_bytes(original)
            sibling = root / 'c/example/Unchanged.c'
            sibling.write_bytes(b'void unchanged(void) {}\n')
            outputs, receipt = platform.reference_spill_outputs(root)
            self.assertEqual(receipt['pointerSpills'], 1)
            self.assertEqual(receipt['scannedClasses'], 2)
            self.assertEqual(source.read_bytes(), original)
            self.assertEqual(outputs[0][0], source)
            self.assertEqual(receipt['files'], [{'path': 'c/example/Original.c',
                'upstreamSha256': hashlib.sha256(original).hexdigest(),
                'adaptedSha256': hashlib.sha256(outputs[0][1]).hexdigest(), 'pointerSpills': 1}])
            self.assertEqual(sibling.read_bytes(), b'void unchanged(void) {}\n')

    def test_every_class_is_validated_before_any_class_is_mutated(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'c').mkdir()
            first, later = root / 'c/A.c', root / 'c/Z.c'
            original = b'    volatile void* teavm_spill_2;\n'
            first.write_bytes(original)
            later.write_text('    volatile TeaVM_Array* teavm_spill_2;\n')
            with self.assertRaisesRegex(ValueError, 'unreviewed-teavm-exception-spill'):
                platform.reference_spill_outputs(root)
            self.assertEqual(first.read_bytes(), original)

    def test_class_size_and_nonfile_inputs_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'c').mkdir()
            (root / 'c/directory.c').mkdir()
            with self.assertRaisesRegex(ValueError, 'unreviewed-teavm-generated-class'):
                platform.reference_spill_outputs(root)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'c/TooLarge.c'
            source.parent.mkdir()
            with source.open('wb') as stream:
                stream.truncate(16 * 1024 * 1024 + 1)
            with self.assertRaisesRegex(ValueError, 'unreviewed-teavm-generated-class'):
                platform.reference_spill_outputs(root)

    def test_missing_or_linked_class_root_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaisesRegex(ValueError, 'unreviewed-teavm-generated-classes'):
                platform.reference_spill_outputs(root)
            with patch.object(Path, 'is_symlink', return_value=True):
                with self.assertRaisesRegex(ValueError, 'unreviewed-teavm-generated-classes'):
                    platform.reference_spill_outputs(root)


if __name__ == '__main__': unittest.main()
