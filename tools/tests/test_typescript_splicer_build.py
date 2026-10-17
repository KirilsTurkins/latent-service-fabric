"""Source-splicer compiler ownership controls; real Cargo/JCO runs in CI."""
import json
from pathlib import Path
import shutil
import tempfile
import unittest

from tools.rust_capsule_project import ROOT
from tools.typescript_guest import splicer_build as owner


class SplicerBuildInputs(unittest.TestCase):
    def compiler(self, root):
        tools = root/'tools'; tools.mkdir()
        for name in ('package.json','package-lock.json'):
            shutil.copyfile(ROOT/'sdk/typescript-guest/tools'/name,tools/name)
        (tools/'node_modules/transitive').mkdir(parents=True)
        (tools/'node_modules/transitive/original.js').write_bytes(b'original')
        return tools

    def test_every_transitive_byte_is_rechecked_including_equal_size_tampering(self):
        with tempfile.TemporaryDirectory() as name:
            tools = self.compiler(Path(name))
            before = owner.compiler_inventory(tools)
            path = tools/'node_modules/transitive/original.js'
            path.write_bytes(b'changed!')
            self.assertNotEqual(owner.compiler_inventory(tools),before)
            self.assertEqual(before['bytes'],8)
            self.assertEqual(before['files'][0]['path'],'node_modules/transitive/original.js')

    def test_original_manifest_and_lock_must_match_before_build(self):
        for selected in ('package.json','package-lock.json'):
            with self.subTest(selected=selected), tempfile.TemporaryDirectory() as name:
                tools = self.compiler(Path(name))
                (tools/selected).write_bytes(b'{}')
                with self.assertRaisesRegex(ValueError,'original-compiler-lock-differs'):
                    owner.compiler_inventory(tools)

    def test_removed_and_added_transitive_inputs_change_complete_inventory(self):
        with tempfile.TemporaryDirectory() as name:
            tools = self.compiler(Path(name))
            before = owner.compiler_inventory(tools)
            (tools/'node_modules/transitive/added.js').write_bytes(b'new')
            self.assertNotEqual(owner.compiler_inventory(tools),before)
            (tools/'node_modules/transitive/original.js').unlink()
            self.assertNotEqual(owner.compiler_inventory(tools),before)

    def test_transpilation_receipt_binds_success_and_every_actual_product(self):
        with tempfile.TemporaryDirectory() as name:
            output = Path(name)
            (output/'transpile.command.json').write_text(json.dumps({'command':['node','jco','transpile']}))
            (output/'transpile.result.json').write_text(json.dumps({'returncode':0}))
            files = {'spidermonkey-embedding-splicer.js':b'original JS',
                     'spidermonkey-embedding-splicer.core.wasm':b'\0asm\x01\0\0\0'}
            before = owner.transpilation_receipt(output,files)
            self.assertEqual(before['result']['returncode'],0)
            files['spidermonkey-embedding-splicer.js'] = b'changed JS'
            self.assertNotEqual(before,owner.transpilation_receipt(output,files))
            (output/'transpile.result.json').write_text(json.dumps({'returncode':1}))
            with self.assertRaisesRegex(ValueError,'successful-transpilation-required'):
                owner.transpilation_receipt(output,files)


if __name__ == '__main__': unittest.main()
