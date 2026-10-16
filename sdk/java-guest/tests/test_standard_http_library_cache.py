"""Qualification cache boundary controls; mocked acquisition is not execution."""
import json
from pathlib import Path
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from tools import java_standard_http_library as gate


class CapturedClientCompilerCache(unittest.TestCase):
    @staticmethod
    def cache(directory):
        selected = directory/'gradle-home/caches/modules-2'
        (selected/'files-2.1').mkdir(parents=True)
        (selected/'metadata-2.107').mkdir()
        (selected/'files-2.1/fixture.jar').write_bytes(b'cache-boundary-only')
        return selected

    def test_explicit_cache_never_starts_registry_acquisition(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            selected = self.cache(root/'existing')
            output = root/'output'; output.mkdir()
            with patch.object(gate, 'Compiler') as compiler, patch.object(gate, 'create') as creator:
                actual = gate.compiler_cache(SimpleNamespace(deadline=time.monotonic()+10), root/'wasi', output, selected)
            self.assertEqual(actual, selected.resolve())
            compiler.assert_not_called(); creator.assert_not_called()
            record = json.loads((output/'compiler-cache-selection.json').read_bytes())
            self.assertEqual(record['mode'], 'explicit-read-only-cache')
            self.assertFalse(record['applicationRegistryResolution'])

    def test_default_acquisition_finishes_and_rechecks_before_cache_selection(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            compiler = Mock(directory=root/'compiler-acquisition')
            compiler.compile.side_effect = lambda *_args: self.cache(compiler.directory)
            with patch.object(gate, 'Compiler', return_value=compiler) as owner, \
                    patch.object(gate, 'create', return_value=root/'compiler-source'):
                actual = gate.compiler_cache(SimpleNamespace(deadline=time.monotonic()+10), root/'wasi', root, None)
            self.assertEqual(actual, compiler.directory/'gradle-home/caches/modules-2')
            self.assertGreater(owner.call_args.kwargs['timeout'], 0)
            self.assertLessEqual(owner.call_args.kwargs['timeout'], 10)
            compiler.check_unchanged.assert_called_once_with()
            record = json.loads((root/'compiler-cache-selection.json').read_bytes())
            self.assertEqual(record['mode'], 'maintained-source-compiler-acquisition')
            self.assertFalse(record['applicationRegistryResolution'])

    def test_failed_acquisition_cannot_emit_a_selected_cache_receipt(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            compiler = Mock(directory=root/'compiler-acquisition')
            compiler.compile.side_effect = ValueError('registry-acquisition-failed')
            with patch.object(gate, 'Compiler', return_value=compiler), \
                    patch.object(gate, 'create', return_value=root/'compiler-source'):
                with self.assertRaisesRegex(ValueError, 'registry-acquisition-failed'):
                    gate.compiler_cache(SimpleNamespace(deadline=time.monotonic()+10), root/'wasi', root, None)
            self.assertFalse((root/'compiler-cache-selection.json').exists())
            compiler.check_unchanged.assert_not_called()

    def test_original_deadline_expiry_precedes_output_or_registry_access(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.object(gate, 'Compiler') as compiler, patch.object(gate, 'create') as creator:
                with self.assertRaisesRegex(ValueError, 'original-deadline-expired'):
                    gate.compiler_cache(SimpleNamespace(deadline=time.monotonic()-1), root/'wasi', root, None)
            compiler.assert_not_called(); creator.assert_not_called()
            self.assertEqual(list(root.iterdir()), [])

    def test_incomplete_explicit_cache_does_not_fall_back_to_registry(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            selected = root/'modules-2'; selected.mkdir()
            with patch.object(gate, 'Compiler') as compiler, patch.object(gate, 'create') as creator:
                with self.assertRaisesRegex(ValueError, 'incomplete pinned read-only'):
                    gate.compiler_cache(SimpleNamespace(deadline=time.monotonic()+10), root/'wasi', root, selected)
            compiler.assert_not_called(); creator.assert_not_called()
            self.assertFalse((root/'compiler-cache-selection.json').exists())
