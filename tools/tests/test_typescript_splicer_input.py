"""Immutable compiler input admission, independent of runtime qualification."""
from copy import deepcopy
import hashlib
import unittest
from tools.typescript_guest import splicer_input as inputs

class TypeScriptSplicerInputTests(unittest.TestCase):
    def values(self):
        files={inputs.MODULE:b'export const splicer={};',
               'spidermonkey-embedding-splicer.core.wasm':b'\0asm\1\0\0\0'}
        sdk={'tools/typescript_guest/import_bindgen.py':b'current exact recipe'}
        digest='sha256:'+'a'*64
        value={'schemaVersion':inputs.SCHEMA,'componentizeTree':inputs.COMPONENTIZE_TREE,
               'files':inputs.identity(files),'sdkInputs':[{'path':name,'digest':'sha256:'+hashlib.sha256(raw).hexdigest(),'size':len(raw)}for name,raw in sorted(sdk.items())],
               'sourceDerivationDigest':digest,'buildReceiptDigest':digest,'transpileReceiptDigest':digest,
               'qualification':'unknown','apiSupport':'not-evaluated','inputTrust':'operator-asserted'}
        return value,files,sdk
    def test_current_exact_source_files_remain_unqualified(self):
        value,files,sdk=self.values()
        actual=inputs.validate(value,files,sdk)
        self.assertEqual((actual['qualification'],actual['apiSupport']),('unknown','not-evaluated'))
    def test_changed_compiler_byte_rejected(self):
        value,files,sdk=self.values();files[inputs.MODULE]+=b'changed'
        with self.assertRaisesRegex(ValueError,'compiler-identity'):inputs.validate(value,files,sdk)
    def test_stale_sdk_codegen_recipe_rejected(self):
        value,files,sdk=self.values();sdk[next(iter(sdk))]+=b'changed'
        with self.assertRaisesRegex(ValueError,'SDK-source-mismatch'):inputs.validate(value,files,sdk)
    def test_declared_support_cannot_promote_compiler_input(self):
        value,files,sdk=self.values();value['qualification']='passed'
        with self.assertRaisesRegex(ValueError,'cannot-certify-api'):inputs.validate(value,files,sdk)
    def test_unknown_schema_field_rejected(self):
        value,files,sdk=self.values();value['approved']=True
        with self.assertRaisesRegex(ValueError,'input-schema'):inputs.validate(value,files,sdk)
    def test_escaping_file_path_rejected(self):
        value,files,sdk=self.values();files['../escape.js']=b'evil'
        with self.assertRaisesRegex(ValueError,'file-shape'):inputs.validate(value,files,sdk)
    def test_missing_generated_module_rejected(self):
        value,files,sdk=self.values();del files[inputs.MODULE]
        with self.assertRaisesRegex(ValueError,'JS-and-Wasm-required'):inputs.validate(value,files,sdk)
    def test_fake_Wasm_extension_rejected(self):
        value,files,sdk=self.values();files['spidermonkey-embedding-splicer.core.wasm']=b'notwasm'
        with self.assertRaisesRegex(ValueError,'Wasm-required'):inputs.validate(value,files,sdk)
    def test_recipe_digest_is_required_even_when_bytes_match(self):
        value,files,sdk=self.values();value['buildReceiptDigest']='missing'
        with self.assertRaisesRegex(ValueError,'recipe-material-required'):inputs.validate(value,files,sdk)

if __name__=='__main__':unittest.main()
