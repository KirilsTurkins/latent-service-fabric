"""Actual core retention cannot replace original Rust assembly failure semantics."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from tools import rust_capsule_build as suite


class RustRawCoreRetention(unittest.TestCase):
    def test_assembly_failure_retains_exact_core_and_source_without_success(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); module = root / 'module.wasm'; output = root / 'output'; output.mkdir()
            raw = b'\x00asm\x01\x00\x00\x00'; module.write_bytes(raw)
            original = ValueError('original assembly failure')
            commands = Mock(); commands.run.side_effect = original
            with self.assertRaises(ValueError) as observed:
                suite.componentize(commands, root / 'wasm-tools', module, output, 'sha256:' + 'a' * 64)
            self.assertIs(observed.exception, original)
            self.assertEqual((output / 'raw-core.wasm').read_bytes(), raw)
            receipt = json.loads((output / 'raw-core-observation.json').read_bytes())
            self.assertEqual(receipt['coreDigest'], suite.digest(raw))
            self.assertEqual(receipt['coreBytes'], len(raw))
            self.assertEqual(receipt['sourceDigest'], 'sha256:' + 'a' * 64)
            self.assertEqual(receipt['authority'], 'none')
            self.assertFalse((output / 'BUILD-COMPLETE.json').exists())
            commands.run.assert_called_once_with('component', root / 'wasm-tools', 'component', 'new',
                module, '-o', output / 'component.wasm')

    def test_missing_noncore_and_overlimit_original_never_mask_assembly_fault(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); output = root / 'output'; output.mkdir()
            for failure in (OSError('gone'), ValueError('over limit')):
                original = RuntimeError('original')
                commands = Mock(); commands.run.side_effect = original
                with patch.object(suite, 'read_file', side_effect=failure), self.assertRaises(RuntimeError) as observed:
                    suite.componentize(commands, root / 'tool', root / 'module', output, 'sha256:' + 'a' * 64)
                self.assertIs(observed.exception, original)
            module = root / 'component'; module.write_bytes(b'\x00asm\x0d\x00\x01\x00')
            with self.assertRaises(RuntimeError) as observed:
                suite.componentize(commands, root / 'tool', module, output, 'sha256:' + 'a' * 64)
            self.assertIs(observed.exception, original)
            self.assertFalse((output / 'raw-core-observation.json').exists())
            module.write_bytes(b'\x00asm\x01\x00\x00\x00')
            with patch.object(suite, 'write_json', side_effect=RuntimeError('diagnostic writer failure')):
                with self.assertRaises(RuntimeError) as observed:
                    suite.componentize(commands, root / 'tool', module, output, 'sha256:' + 'a' * 64)
            self.assertIs(observed.exception, original)

    def test_success_and_cancellation_keep_the_original_outcome(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            commands = Mock()
            with patch.object(suite, 'read_file') as read:
                suite.componentize(commands, root / 'tool', root / 'module', root, 'sha256:' + 'a' * 64)
            read.assert_not_called()
            original = KeyboardInterrupt()
            commands.run.side_effect = original
            with patch.object(suite, 'read_file', side_effect=OSError('gone')), self.assertRaises(KeyboardInterrupt) as observed:
                suite.componentize(commands, root / 'tool', root / 'module', root, 'sha256:' + 'a' * 64)
            self.assertIs(observed.exception, original)
