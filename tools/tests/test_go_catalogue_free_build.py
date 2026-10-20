"""Real maintained Go recipe staging without optional catalogue/reference data."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from tools import go_catalogue_free_build as stage
from tools.phase2_operator_process import WorkflowError

ROOT = Path(__file__).resolve().parents[2]


class GoCatalogueFreeBuildTests(unittest.TestCase):
    def test_real_static_recipe_closure_excludes_catalogue_and_preserves_exact_source(self):
        before = stage.source_files(ROOT)
        self.assertTrue((ROOT / 'docs/compatibility-catalogue/v1/catalogue.json').is_file())
        self.assertTrue(set(stage.RECIPE) <= set(before))
        self.assertNotIn('tools/compatibility_catalogue.py', before)
        self.assertFalse(any(name.startswith('docs/') for name in before))
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / 'compiler'
            receipt = stage.stage(ROOT, root)
            self.assertEqual(stage.verify(root), receipt)
            self.assertEqual(before, stage.source_files(ROOT))
            self.assertEqual({name: (root / name).read_bytes() for name in before}, before)
            self.assertFalse((root / 'docs').exists())
            self.assertFalse((root / 'sdk/go-guest').exists())  # Captured SDK is in the application vendor.
            self.assertIs(receipt['actualComponentQualified'], False)
            self.assertEqual({n for n in before if not n.endswith('.py')}, stage.DATA)

    def test_removed_recipe_or_changed_source_cannot_pass_verified_stage(self):
        for change in ('remove', 'modify', 'manifest'):
            with self.subTest(change=change), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary) / 'compiler'
                stage.stage(ROOT, root)
                source = root / 'tools/go_guest/http.py'
                if change == 'remove': source.unlink()
                elif change == 'modify': source.write_bytes(source.read_bytes() + b'\n# unreviewed\n')
                else:
                    manifest = root / stage.MANIFEST
                    value = json.loads(manifest.read_bytes()); value['fileCount'] += 1
                    manifest.write_bytes(json.dumps(value).encode())
                with self.assertRaises(WorkflowError): stage.verify(root)

    def test_catalogue_or_unselected_extra_data_is_rejected_even_with_valid_original_inventory(self):
        for name in ('docs/compatibility-catalogue/v1/catalogue.json', 'tools/optional-pins.json',
                     'sdk/go-guest/unreviewed.json'):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary) / 'compiler'
                stage.stage(ROOT, root)
                path = root / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(b'{}')
                with self.assertRaises(WorkflowError): stage.verify(root)

    def test_source_path_and_second_physical_link_fail_before_compiler_execution(self):
        for name in ('../escape.py', 'docs/compatibility-catalogue/v1/catalogue.json',
                     'tools/../escape.py', '/tools/go_capsule.py'):
            with self.subTest(name=name), self.assertRaises(WorkflowError): stage.source_file(ROOT, name)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / 'compiler'
            stage.stage(ROOT, root)
            path = root / 'tools/go_guest/http.py'
            os.link(path, Path(temporary) / 'outside-hardlink')
            with self.assertRaises(WorkflowError): stage.verify(root)

    def test_staged_cli_imports_only_its_own_closure_without_checkout_pythonpath(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / 'compiler'; stage.stage(ROOT, root)
            result = subprocess.run([sys.executable, str(root / stage.SELF), '--help'],
                cwd=temporary, env=dict(os.environ, PYTHONPATH=''), capture_output=True, timeout=20)
            self.assertEqual(result.returncode, 0, result.stderr.decode())
            self.assertIn(b'--expect-source-digest', result.stdout)
            self.assertNotIn(b'--tools', result.stdout)


if __name__ == '__main__':
    unittest.main()
