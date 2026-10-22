"""Only the reviewed unselected test insertion can accompany v7 products."""
import copy
import subprocess
import unittest
from unittest.mock import patch

from tools import c_thread_linear_memory_native_source as source
from tools.phase2_operator_process import WorkflowError
from tools.rust_capsule_project import ROOT


def original():
    return subprocess.check_output(['git', 'show', source.SOURCE + ':' + source.PATH], cwd=ROOT)


def corrected():
    return subprocess.check_output(['git', 'show', source.FIXTURE_FIX + ':' + source.PATH], cwd=ROOT)


class CThreadLinearMemoryNativeSource(unittest.TestCase):
    def test_actual_git_test_insertion_reverses_to_the_compiled_file_only(self):
        self.assertEqual(source._identity(original()), source.ORIGINAL_FILE)
        self.assertEqual(source._identity(corrected()), source.CORRECTED_FILE)
        self.assertEqual(source._reverse_fixture(corrected()), original())
        for raw in (original(), corrected() + b'\n',
                corrected().replace(b'drop(output);', b'drop(control);', 1),
                corrected().replace(b'outstanding_reservations(), 1', b'outstanding_reservations(), 0', 1)):
            with self.subTest(identity=source._identity(raw)), self.assertRaises(WorkflowError):
                source._reverse_fixture(raw)

    def test_compiled_and_corrected_trees_keep_separate_compilation_identities(self):
        for current in (source.COMPILED, source.CORRECTED):
            with patch.object(source, 'git_source_identity', return_value=source.COMPILED), \
                    patch.object(source, 'source_identity', return_value=current), \
                    patch.object(source, 'read_file', return_value=corrected()) as read:
                result = source.assert_current(ROOT)
            self.assertEqual(result['compiledSourceRevision'], source.SOURCE)
            self.assertEqual(result['compiledNativeSource'], source.COMPILED)
            self.assertEqual(result['consumerNativeSource'], current)
            self.assertIs(result['compiledSourceByteExact'], current == source.COMPILED)
            changes = result['reviewedSourceChanges']
            if current == source.COMPILED:
                read.assert_not_called()
                self.assertEqual(changes, [])
            else:
                read.assert_called_once_with(ROOT / source.PATH, 64 * 1024)
                self.assertEqual(len(changes), 1)
                self.assertEqual(changes[0]['allOtherNativeFilesByteExact'], 3621)
                self.assertEqual(changes[0]['path'], source.PATH)
                self.assertIs(changes[0]['reverseSubstitutionByteExact'], True)

    def test_foreign_complete_tree_field_types_and_file_tampering_refuse(self):
        for identity in (source.COMPILED, source.CORRECTED):
            for name in identity:
                bad = copy.deepcopy(identity)
                bad[name] = True if type(identity[name]) is int else 'foreign'
                with self.subTest(tree=identity['sha256'], field=name), \
                        patch.object(source, 'git_source_identity', return_value=source.COMPILED), \
                        patch.object(source, 'source_identity', return_value=bad), self.assertRaises(WorkflowError):
                    source.assert_current(ROOT)
        with patch.object(source, 'git_source_identity', return_value=source.CORRECTED), \
                patch.object(source, 'source_identity', return_value=source.CORRECTED), self.assertRaises(WorkflowError):
            source.assert_current(ROOT)
        with patch.object(source, 'git_source_identity', return_value=source.COMPILED), \
                patch.object(source, 'source_identity', return_value=source.CORRECTED), \
                patch.object(source, 'read_file', return_value=corrected() + b'\n'), self.assertRaises(WorkflowError):
            source.assert_current(ROOT)


if __name__ == '__main__':
    unittest.main()
