"""Bounded fixture and retained-input controls; JVM execution is a separate step."""
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from tools import qualify_java_checkpoint_context as probe
from tools.phase2_operator_process import WorkflowError


class CheckpointCompiler(unittest.TestCase):
    def test_real_frontend_fixture_matches_production_preparation_and_has_no_codegen(self):
        source = probe.COMPILER_CONTROL.read_text()
        self.assertIn('new PreOptimizingClassHolderSource(new ClasspathClassHolderSource(', source)
        self.assertIn('vm.installPlugins();', source)
        self.assertIn('vm.setOptimizationLevel(TeaVMOptimizationLevel.FULL);', source)
        self.assertIn('super.analyzeBeforeOptimizations(source);', source)
        self.assertLess(source.index('super.analyzeBeforeOptimizations(source);'),
            source.index('throw new AnalysisComplete();'))
        self.assertIn('checkpoint-control-must-not-generate-code', source)
        self.assertIn('checkpoint-control-mutation-was-applied', source)
        self.assertIn('getSevereProblems().isEmpty()', source)
        self.assertNotIn('printStackTrace', source)
        self.assertIn('"' + probe.COMPILER_EXPECTED + '"', source)
        self.assertEqual(probe.COMPILER_EXPECTED.split(';')[1:], [
            'finite', 'initializer', 'unmanaged', 'managed', 'recursion',
            'runtime-initializer', 'class-object-helper', 'string-copy-body'])

    def test_retained_inputs_are_deterministic_and_exclude_unselected_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            selected = root/'control.java'; selected.write_bytes(b'fixed control')
            generated = root/'generated.java'; generated.write_bytes(b'fixed generated finder')
            jar = root/'core.jar'; jar.write_bytes(b'fixed locked jar')
            (root/'unselected.txt').write_bytes(b'not a compiler input')
            records = []
            for name in ('first', 'second'):
                output = root/name
                (output/'commands/logs').mkdir(parents=True)
                with patch.object(probe, 'ROOT', root):
                    records.append(probe.retain_compiler_inputs(output, str(jar), [selected], generated))
                with zipfile.ZipFile(output/'commands/logs/compiler-inputs.zip') as archive:
                    self.assertEqual(set(archive.namelist()), {
                        'control.java', 'generated/AsyncMethodFinder.java', 'jars/core.jar'})
                    self.assertEqual(archive.read('control.java'), b'fixed control')
                    self.assertEqual(archive.read('generated/AsyncMethodFinder.java'), b'fixed generated finder')
                    self.assertEqual(archive.read('jars/core.jar'), b'fixed locked jar')
            self.assertEqual(records[0], records[1])
            self.assertEqual((root/'first/commands/logs/compiler-inputs.zip').read_bytes(),
                (root/'second/commands/logs/compiler-inputs.zip').read_bytes())
            self.assertEqual(selected.read_bytes(), b'fixed control')
            self.assertEqual(jar.read_bytes(), b'fixed locked jar')

    def test_retained_inputs_refuse_duplicate_jar_names_before_writing(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            output = root/'out'
            (output/'commands/logs').mkdir(parents=True)
            with patch.object(probe, 'ROOT', root), self.assertRaisesRegex(WorkflowError, 'duplicate'):
                probe.retain_compiler_inputs(output,
                    os.pathsep.join(map(str, (root/'a/core.jar', root/'b/core.jar'))), [], root/'generated.java')
            self.assertFalse((output/'commands/logs/compiler-inputs.zip').exists())

    def test_retained_inputs_refuse_excess_entries_before_reading(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with patch.object(probe, 'ROOT', root), patch.object(probe, 'read_file') as read:
                with self.assertRaisesRegex(WorkflowError, 'entry-bound'):
                    probe.retain_compiler_inputs(root, str(root/'core.jar'),
                        [root/f'control-{index}.java' for index in range(64)], root/'generated.java')
                read.assert_not_called()


if __name__ == '__main__':
    unittest.main()
