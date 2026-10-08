"""Trusted host aliases bind physical bytes without relaxing source inputs."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools.typescript_guest.compiler import discovered_host_tool


class TypeScriptHostToolTests(unittest.TestCase):
    def test_missing_tool_keeps_existing_concrete_diagnostic_path(self):
        with patch('tools.typescript_guest.compiler.shutil.which', return_value=None):
            self.assertEqual(discovered_host_tool('node', '/none'), Path('missing-node'))

    def test_discovered_regular_tool_binds_its_resolved_bytes(self):
        with tempfile.TemporaryDirectory() as name:
            binary = Path(name)/'node'
            binary.write_bytes(b'owned tool')
            with patch('tools.typescript_guest.compiler.shutil.which', return_value=str(binary)):
                selected = discovered_host_tool('node', name)
            self.assertEqual(selected, binary.resolve(strict=True))
            self.assertEqual(selected.read_bytes(), b'owned tool')

    def test_only_discovered_host_path_is_resolved_strictly(self):
        with tempfile.TemporaryDirectory() as name:
            binary = Path(name)/'physical'
            binary.write_bytes(b'physical tool')
            candidate = Path(name)/'trusted-host-alias'
            with patch('tools.typescript_guest.compiler.shutil.which', return_value=str(candidate)), \
                 patch('tools.typescript_guest.compiler.Path.resolve', return_value=binary) as resolve:
                self.assertEqual(discovered_host_tool('wasm-tools', name), binary)
            resolve.assert_called_once_with(strict=True)


if __name__ == '__main__':
    unittest.main()
