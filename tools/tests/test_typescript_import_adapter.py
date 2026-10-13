"""Private source-bound adapter preparation does not advertise API support."""
from pathlib import Path
import tempfile
import unittest
from tools.typescript_guest.import_profile import compiler_observation,componentizer_adapter,splicer_files

class TypeScriptImportAdapterTests(unittest.TestCase):
    def test_unknown_engine_and_compiler_observations_stay_unknown(self):
        value=compiler_observation({'qualification':'unknown'},{'qualification':'unknown'})
        self.assertEqual((value['qualification'],value['apiSupport'],value['authority']),
                         ('unknown','not-evaluated','none'))
    def test_declared_engine_support_cannot_create_runtime_qualification(self):
        with self.assertRaisesRegex(ValueError,'cannot-infer-qualification'):
            compiler_observation({'qualification':'passed'},{'qualification':'unknown'})
    def test_declared_compiler_support_cannot_create_runtime_qualification(self):
        with self.assertRaisesRegex(ValueError,'cannot-infer-qualification'):
            compiler_observation({'qualification':'unknown'},{'qualification':'passed'})
    def test_unreviewed_public_componentizer_source_rejected_before_derivation(self):
        with self.assertRaisesRegex(ValueError,'unreviewed-componentize-js-source'):
            componentizer_adapter(b'fake compiler source')
    def test_missing_source_splicer_directory_rejected(self):
        with tempfile.TemporaryDirectory()as name:
            with self.assertRaisesRegex(ValueError,'directory-required'):
                splicer_files(Path(name)/'missing')
    def test_actual_files_read_exactly_and_extra_bytes_change_input(self):
        with tempfile.TemporaryDirectory()as name:
            root=Path(name);module=root/'spidermonkey-embedding-splicer.js'
            module.write_bytes(b'original');(root/'core.wasm').write_bytes(b'\0asm\1\0\0\0')
            self.assertEqual(splicer_files(root)[module.name],b'original')
            module.write_bytes(b'changed')
            self.assertEqual(splicer_files(root)[module.name],b'changed')

if __name__=='__main__':unittest.main()
