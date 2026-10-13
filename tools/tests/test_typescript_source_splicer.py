"""The selected source-built splicer remains the only import compiler input."""
from pathlib import Path
import json
import os
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]


class TypeScriptSourceSplicerTests(unittest.TestCase):
    def run_module(self, source):
        node = shutil.which('node')
        self.assertIsNotNone(node, 'the maintained source control requires Node')
        with tempfile.TemporaryDirectory(prefix='lsf-splicer-contract-') as name:
            root = Path(name)
            (root/'selected.mjs').write_text(source, encoding='utf-8')
            (root/'source_splicer.mjs').write_bytes(
                (ROOT/'tools/typescript_guest/source_splicer.mjs').read_bytes())
            script = """import {selectedSourceSplicer} from './source_splicer.mjs';
import * as selected from './selected.mjs';
try {
  const splicer = selectedSourceSplicer(selected);
  console.log(JSON.stringify({accepted:true,value:splicer.spliceBindings(),stub:splicer.stubWasi()}));
} catch (error) {
  console.log(JSON.stringify({accepted:false,error:error.message}));
}
"""
            (root/'control.mjs').write_text(script, encoding='utf-8')
            result = subprocess.run([node, root/'control.mjs'], cwd=root,
                                    capture_output=True, timeout=10, env={
                                        'PATH': os.environ.get('PATH', ''),
                                        'SystemRoot': os.environ.get('SystemRoot', '')})
            self.assertEqual(result.returncode, 0, result.stderr.decode(errors='replace'))
            return json.loads(result.stdout)

    def test_missing_export_rejected(self):
        self.assertEqual(self.run_module('export const unrelated = 1;'), {
            'accepted': False, 'error': 'source-built-splicer-callable-export-required'})

    def test_null_export_rejected(self):
        self.assertEqual(self.run_module('export const splicer = null;'), {
            'accepted': False, 'error': 'source-built-splicer-callable-export-required'})

    def test_false_export_rejected(self):
        self.assertEqual(self.run_module('export const splicer = false;'), {
            'accepted': False, 'error': 'source-built-splicer-callable-export-required'})

    def test_non_function_truthy_export_rejected(self):
        self.assertEqual(self.run_module('export const splicer = {};'), {
            'accepted': False, 'error': 'source-built-splicer-callable-export-required'})

    def test_exact_selected_callable_is_invoked(self):
        self.assertEqual(self.run_module(
            'export const splicer = {spliceBindings() { return "selected"; }, '
            'stubWasi() { return "selected-stub"; }};'), {
            'accepted': True, 'value': 'selected', 'stub': 'selected-stub'})

    def test_missing_stub_method_rejected(self):
        self.assertEqual(self.run_module(
            'export const splicer = {spliceBindings() { return "selected"; }};'), {
            'accepted': False, 'error': 'source-built-splicer-callable-export-required'})

    def test_non_callable_splice_method_rejected(self):
        self.assertEqual(self.run_module(
            'export const splicer = {spliceBindings: {}, stubWasi() {}};'), {
            'accepted': False, 'error': 'source-built-splicer-callable-export-required'})

    def test_non_callable_stub_method_rejected(self):
        self.assertEqual(self.run_module(
            'export const splicer = {spliceBindings() {}, stubWasi: {}};'), {
            'accepted': False, 'error': 'source-built-splicer-callable-export-required'})


if __name__ == '__main__':
    unittest.main()
