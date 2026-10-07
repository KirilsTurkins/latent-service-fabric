"""Real maintained helper archive imports; no checkout fallback or node work."""
from pathlib import Path
import os
import subprocess
import sys
import tempfile
import unittest
import zipfile

from tools import build_dev_frontend as builder


class HelperRuntimeImports(unittest.TestCase):
    def archive(self):
        owned = tempfile.TemporaryDirectory(); self.addCleanup(owned.cleanup)
        root = Path(owned.name); helper = root / 'helper.pyz'
        builder.helper(helper)
        return root, helper

    def probe(self, root, helper, *, dispatch=False):
        script = '''import importlib,pathlib,sys
archive=pathlib.Path(sys.argv[1]).resolve();sys.path.insert(0,str(archive))
module=importlib.import_module('tools.dev_workflow.node_scenarios')
from tools.dev_workflow.common import DevError
if sys.argv[2]=='dispatch':
 try:
  module.run(pathlib.Path.cwd(),{'environment':'invalid','selection':[]})
 except DevError as error:
  assert error.code=='linux-test-cannot-fallback-to-portable',error.code
 else:raise AssertionError('original scenario admission fence missing')
for name in ('tools.guest_compatibility_outcomes','tools.guest_compatibility','tools.guest_compatibility_context','tools.guest_runtime_receipts'):
 importlib.import_module(name)
for name,loaded in tuple(sys.modules.items()):
 if name.startswith('tools.') and getattr(loaded,'__file__',None):
  assert str(pathlib.Path(loaded.__file__)).startswith(str(archive)),name
print('real-helper-runtime-imports-owned')
'''
        return subprocess.run([sys.executable, '-I', '-B', '-c', script, str(helper), 'dispatch' if dispatch else 'imports'],
            cwd=root, capture_output=True, timeout=30, check=False)

    def test_actual_built_helper_imports_runtime_closure_without_checkout_or_node_fallback(self):
        root, helper = self.archive(); result = self.probe(root, helper)
        self.assertEqual(result.returncode, 0, result.stderr.decode('utf-8', 'replace')[:4096])
        self.assertEqual(result.stdout.splitlines(), [b'real-helper-runtime-imports-owned'])
        self.assertEqual(result.stderr, b'')

    @unittest.skipUnless(os.name == 'posix', 'Linux helper dispatch requires the real pwd module')
    def test_linux_helper_dispatch_reaches_original_scenario_fence_without_node_work(self):
        root, helper = self.archive(); result = self.probe(root, helper, dispatch=True)
        self.assertEqual(result.returncode, 0, result.stderr.decode('utf-8', 'replace')[:4096])
        self.assertEqual(result.stdout.splitlines(), [b'real-helper-runtime-imports-owned'])
        self.assertEqual(result.stderr, b'')

    def test_missing_captured_outcome_module_cannot_be_imported_from_checkout(self):
        root, helper = self.archive(); incomplete = root / 'incomplete.pyz'
        with zipfile.ZipFile(helper) as source, zipfile.ZipFile(incomplete, 'x') as target:
            for row in source.infolist():
                if row.filename != 'tools/guest_compatibility_outcomes.py':
                    target.writestr(row, source.read(row.filename))
        result = self.probe(root, incomplete)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(b'guest_compatibility_outcomes', result.stderr)


if __name__ == '__main__': unittest.main()
