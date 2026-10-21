"""Closed original/extracted source proof; no native or guest execution."""
import copy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools import activation_stack_native_source as source
from tools.rust_capsule_project import ROOT


class ActivationStackNativeSource(unittest.TestCase):
    def test_original_tree_requires_no_projection_and_preserves_compiled_identity(self):
        with patch.object(source, 'git_source_identity', return_value=copy.deepcopy(source.COMPILED)), \
                patch.object(source, 'source_identity', return_value=copy.deepcopy(source.COMPILED)), \
                patch.object(source, 'read_file', side_effect=AssertionError('unexpected projection')):
            result = source.assert_current(ROOT)
        self.assertTrue(result['compiledSourceByteExact'])
        self.assertEqual(result['compiledSourceRevision'], source.SOURCE)
        self.assertEqual(result['compiledNativeSource'], result['consumerNativeSource'])
        self.assertEqual(result['reviewedSourceChanges'], [])

    def test_actual_pinned_extraction_reverses_to_original_and_reports_separate_source(self):
        raw = (ROOT / 'tools/tests/fixtures/activation-stack-runtime-extracted.rs').read_bytes()
        self.assertEqual(source._identity(raw), source.EXTRACTED_FILE)
        self.assertEqual(source._identity(source._reverse_extraction(raw)), source.ORIGINAL_FILE)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = root / source.PATH
            path.parent.mkdir(parents=True)
            path.write_bytes(raw)
            with patch.object(source, 'git_source_identity', return_value=copy.deepcopy(source.COMPILED)), \
                    patch.object(source, 'source_identity', return_value=copy.deepcopy(source.EXTRACTED)):
                result = source.assert_current(root)
            self.assertFalse(result['compiledSourceByteExact'])
            self.assertEqual(result['compiledNativeSource'], source.COMPILED)
            self.assertEqual(result['consumerNativeSource'], source.EXTRACTED)
            self.assertEqual(len(result['reviewedSourceChanges']), 1)
            change = result['reviewedSourceChanges'][0]
            self.assertEqual(change['path'], source.PATH)
            self.assertTrue(change['reverseInlineByteExact'])
            self.assertEqual(change['allOtherNativeFilesByteExact'], 3324)
        for changed in (raw + b'\n', raw.replace(b'&mut runtime)?;', b'&mut runtime);'),
                        raw.replace(b'owned_native_stacks = true', b'owned_native_stacks = false'),
                        raw.replace(b'\n', b'\r\n'), raw + source._CALL, b'x' * 16385):
            with self.subTest(bytes=len(changed)), self.assertRaisesRegex(RuntimeError, 'exact-extracted-file'):
                source._reverse_extraction(changed)

    def test_foreign_complete_source_and_field_type_aliases_are_refused(self):
        variants = [dict(source.EXTRACTED, **{key: value}) for key, value in (
            ('sha256', 'sha256:' + '0' * 64), ('files', 3326), ('bytes', 26391744),
            ('files', 3325.0), ('hermetic', 0), ('scope', 'foreign'))]
        variants.extend(({}, dict(source.COMPILED, extra='unreviewed')))
        for changed in variants:
            with self.subTest(changed=changed), \
                    patch.object(source, 'git_source_identity', return_value=copy.deepcopy(source.COMPILED)), \
                    patch.object(source, 'source_identity', return_value=changed), \
                    self.assertRaisesRegex(RuntimeError, 'exact-current-source'):
                source.assert_current(ROOT)
        with patch.object(source, 'git_source_identity', return_value=dict(source.COMPILED, files=3326)), \
                patch.object(source, 'source_identity', side_effect=AssertionError('source used before compiled proof')), \
                self.assertRaisesRegex(RuntimeError, 'exact-compiled-source'):
            source.assert_current(ROOT)


if __name__ == '__main__':
    unittest.main()
