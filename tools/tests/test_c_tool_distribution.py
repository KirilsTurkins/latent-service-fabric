"""Execute the actual installed C creator with isolated imports outside checkout."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from tools import c_capsule_project, dev_tool_distribution
from tools.rust_capsule_project import snapshot


class InstalledCProjects(unittest.TestCase):
    def setUp(self):
        owned = tempfile.TemporaryDirectory()
        self.addCleanup(owned.cleanup)
        self.root = Path(owned.name)
        self.payload = self.root / 'installed'
        self.payload.mkdir()
        dev_tool_distribution.recipe(self.payload, 'c')
        self.outside = self.root / 'outside-checkout'
        self.outside.mkdir()

    def create(self, template):
        destination = self.outside / template
        result = subprocess.run([sys.executable, '-I', '-B',
            str(self.payload / 'recipe/tools/c_capsule.py'), 'new', str(destination), '--template', template],
            cwd=self.outside, env={**os.environ, 'PYTHONPATH': str(self.root / 'absent')},
            capture_output=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr.decode())
        return snapshot(destination)

    def test_every_installed_creator_captures_the_exact_sdk_and_validates_without_checkout(self):
        expected = c_capsule_project.sdk_inputs(dev_tool_distribution.ROOT)
        for template in c_capsule_project.AUTHORING_TEMPLATES:
            with self.subTest(template=template):
                files = self.create(template)
                _project, lock, _pins = c_capsule_project.validate(files)
                self.assertEqual(lock['template']['name'], template)
                self.assertEqual({name.removeprefix('vendor/lsf/'): data for name, data in files.items()
                                  if name.startswith('vendor/lsf/')}, expected)

    def test_installed_runtime_tampering_cannot_inherit_the_created_sdk_lock(self):
        files = self.create('greeting')
        runtime = 'vendor/lsf/sdk/c-guest/src/trap.c'
        self.assertIn(runtime, files)
        with self.assertRaisesRegex(ValueError, 'vendored SDK changed'):
            c_capsule_project.validate({**files, runtime: files[runtime] + b'\n/* altered bytes */\n'})


if __name__ == '__main__':
    unittest.main()
