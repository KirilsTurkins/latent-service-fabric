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

    def test_staged_recipe_resolves_all_adapter_modules_without_checkout_fallback(self):
        import shutil
        import subprocess
        node = shutil.which('node')
        if node is None:
            self.skipTest('requires Node')
        from tools.typescript_guest.build import RECIPE
        root = Path(__file__).resolve().parents[2]
        with tempfile.TemporaryDirectory() as owned:
            staged = Path(owned)
            for name in RECIPE:
                if name.startswith('tools/typescript_guest/') and name.endswith('.mjs'):
                    target = staged/name
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes((root/name).read_bytes())
            result = subprocess.run(
                [node, str(staged/'tools/typescript_guest/componentize.mjs'),
                 str(staged/'missing-compiler.mjs')], cwd=staged, capture_output=True, timeout=30,
                check=False,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn(b'ENOENT', result.stderr)
            self.assertNotIn(b'ERR_MODULE_NOT_FOUND', result.stderr)


if __name__ == '__main__':
    unittest.main()
