"""Actual source candidate selection cannot imply qualification or authority."""
from copy import deepcopy
from pathlib import Path
import unittest
from tools.typescript_guest import runtime_profile as runtime
from tools.typescript_guest.activation_engine import engine_input_paths

class TypeScriptImportSelectionTests(unittest.TestCase):
    def envelope(self):
        core=b'\0asm\1\0\0\0\1';sdk={'source.h':b'current'};wit=b'actual WIT'
        value={'schemaVersion':runtime.IMPORT_ENGINE_SCHEMA,'profile':runtime.IMPORT_PROFILE,
         'coreDigest':runtime.digest(core),'coreBytes':len(core),'sdkInputs':[{'path':'source.h','digest':runtime.digest(b'current'),'size':7}],
         'runtimeWitDigest':runtime.digest(wit),'upstream':runtime.SOURCE_PINS,
         'sourceDerivationDigest':runtime.digest(b'source'),'buildReceiptDigest':runtime.digest(b'build'),
         'compilerSplicerInputDigest':runtime.digest(b'compiler'),'qualification':'unknown','apiSupport':'not-evaluated','inputTrust':'operator-asserted'}
        return value,core,sdk,wit
    def test_explicit_profile_stays_unknown_and_grants_no_authority(self):
        self.assertEqual(runtime.selected_profile({'runtimeProfile':runtime.IMPORT_PROFILE}),runtime.IMPORT_PROFILE)
        observation=runtime.selection(runtime.IMPORT_PROFILE)
        self.assertEqual((observation['qualification'],observation['apiSupport'],observation['authority']),('unknown','not-evaluated','none'))
    def test_original_synchronous_default_unchanged(self):
        self.assertEqual(runtime.selected_profile({}),runtime.SYNC_PROFILE)
    def test_actual_import_candidate_requires_distinct_schema_and_compiler_binding(self):
        value,core,sdk,wit=self.envelope()
        runtime.validate_engine(value,core,sdk,wit,profile=runtime.IMPORT_PROFILE)
        value['schemaVersion']=runtime.ENGINE_SCHEMA
        with self.assertRaisesRegex(ValueError,'input-version'):
            runtime.validate_engine(value,core,sdk,wit,profile=runtime.IMPORT_PROFILE)
    def test_missing_compiler_recipe_binding_rejected(self):
        value,core,sdk,wit=self.envelope();del value['compilerSplicerInputDigest']
        with self.assertRaisesRegex(ValueError,'input-schema'):
            runtime.validate_engine(value,core,sdk,wit,profile=runtime.IMPORT_PROFILE)
    def test_old_profile_cannot_receive_import_candidate_envelope(self):
        value,core,sdk,wit=self.envelope()
        with self.assertRaisesRegex(ValueError,'input-schema'):
            runtime.validate_engine(value,core,sdk,wit,profile=runtime.CLOCK_PROFILE)
    def test_invalid_compiler_digest_rejected(self):
        value,core,sdk,wit=self.envelope();value['compilerSplicerInputDigest']='missing'
        with self.assertRaisesRegex(ValueError,'compiler-source-required'):
            runtime.validate_engine(value,core,sdk,wit,profile=runtime.IMPORT_PROFILE)
    def test_declared_engine_support_does_not_promote_input(self):
        value,core,sdk,wit=self.envelope();value['qualification']='passed'
        with self.assertRaisesRegex(ValueError,'cannot-certify-api'):
            runtime.validate_engine(value,core,sdk,wit,profile=runtime.IMPORT_PROFILE)
    def test_source_closure_contains_actual_native_compiler_and_async_cancel_inputs(self):
        paths=set(engine_input_paths(runtime.IMPORT_PROFILE))
        self.assertTrue({'sdk/typescript-guest/activation/native_cancel.h',
          'sdk/typescript-guest/activation/native_import_bridge.cpp','sdk/typescript-guest/activation/async_import_splice.rs',
          'tools/typescript_guest/import_profile.py','tools/typescript_guest/import_bindgen.py'}<=paths)
        self.assertLessEqual(len(paths),64)

if __name__=='__main__':unittest.main()
