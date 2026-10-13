"""Build provenance identifies selected bytes without certifying API support."""
from pathlib import Path
import unittest

from tools.rust_capsule_project import digest, inventory
from tools.typescript_guest.compiler import Compiler


class TypeScriptRuntimeMaterialTests(unittest.TestCase):
    def compiler(self, engine=None, splicer=None):
        compiler=Compiler.__new__(Compiler)
        compiler.engine_before=engine
        compiler.source_splicer_original=splicer
        return compiler

    def test_original_synchronous_selection_has_no_invented_runtime_materials(self):
        self.assertEqual(self.compiler().runtime_materials(), [])

    def test_selected_engine_names_exact_core_and_input_envelope(self):
        core,envelope=b'actual core',b'actual input'
        self.assertEqual(self.compiler((core,envelope)).runtime_materials(), [
            {'name':'typescript-native-engine','digest':digest(core),'size':len(core)},
            {'name':'typescript-native-engine-input','digest':digest(envelope),'size':len(envelope)},
        ])

    def test_selected_splicer_names_envelope_and_actual_file_inventory(self):
        files={'selected.js':b'original code','selected.wasm':b'original bytes'}
        raw=b'unknown operator input'
        compiler=self.compiler(splicer=(Path('source'),Path('receipt'),files,raw))
        rows=compiler.runtime_materials()
        encoded=inventory(files)
        self.assertEqual(rows,[
            {'name':'typescript-source-splicer-input','digest':digest(raw),'size':len(raw)},
            {'name':'typescript-source-splicer-files','digest':digest(encoded),'size':len(encoded)},
        ])
        self.assertTrue(all(set(row)=={'name','digest','size'}for row in rows))

    def test_any_selected_compiler_file_changes_its_material_identity(self):
        files={'selected.js':b'original code','selected.wasm':b'original bytes'}
        compiler=self.compiler(splicer=(Path('source'),Path('receipt'),files,b'input'))
        before=compiler.runtime_materials()
        files['selected.wasm']=b'changed bytes'
        self.assertNotEqual(compiler.runtime_materials(),before)


if __name__=='__main__':
    unittest.main()
