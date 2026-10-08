"""Pinned native codec selection repairs typed bindings, not a JS polyfill."""
from pathlib import Path
import unittest
from tools.typescript_guest.text_codec_engine import PREIMAGES,SOURCES,extend_native_text_codec_source

FIXTURES=Path(__file__).parent/'fixtures/typescript_text_codec'
SELECTION=b'NS_DEF(builtins::web::abort)\nNS_DEF(componentize::embedding)\n'


class TypeScriptNativeTextCodecSourceTests(unittest.TestCase):
    def source(self):
        return {name:(FIXTURES/('codec'+str(index)+'.source')).read_bytes()
                for index,name in enumerate(PREIMAGES)}

    def test_all_original_codec_definitions_and_other_sources_preserved(self):
        source=self.source();source['lsf/native_engine.cpp']=b'unchanged original native runtime'
        before=dict(source);derived,receipt=extend_native_text_codec_source(source,SELECTION)
        self.assertEqual(source,before)
        for name,raw in before.items():self.assertEqual(derived[name],raw)
        self.assertEqual(receipt['compilerSourceFilesToAdd'],list(SOURCES))
        self.assertTrue(receipt['originalNativeCodecDefinitionsUnchanged'])

    def test_codec_installed_before_component_binding_initialization(self):
        derived,_=extend_native_text_codec_source(self.source(),SELECTION)
        self.assertEqual(derived['builtins.incl'],
            b'NS_DEF(builtins::web::abort)\nNS_DEF(builtins::web::text_codec)\nNS_DEF(componentize::embedding)\n')

    def test_each_original_source_byte_is_an_exact_precondition(self):
        for name in PREIMAGES:
            with self.subTest(name=name):
                source=self.source();source[name]+=b'changed'
                with self.assertRaisesRegex(ValueError,'unreviewed-native-text-codec-source'):
                    extend_native_text_codec_source(source,SELECTION)

    def test_missing_codec_definition_rejected(self):
        source=self.source();del source[SOURCES[0]]
        with self.assertRaisesRegex(ValueError,'source-required'):
            extend_native_text_codec_source(source,SELECTION)

    def test_duplicate_installation_is_rejected(self):
        with self.assertRaisesRegex(ValueError,'already-selected-or-invalid'):
            extend_native_text_codec_source(self.source(),b'NS_DEF(builtins::web::text_codec)\n'+SELECTION)

    def test_missing_or_repeated_embedding_anchor_rejected(self):
        for value in (b'',SELECTION+SELECTION):
            with self.subTest(value=value),self.assertRaisesRegex(ValueError,'pinned engine hook shape differs'):
                extend_native_text_codec_source(self.source(),value)

    def test_source_selection_cannot_claim_api_or_signed_qualification(self):
        _,receipt=extend_native_text_codec_source(self.source(),SELECTION)
        self.assertEqual(receipt['qualification'],'unknown')
        self.assertFalse(receipt['standardTextCodecOrSignedLSFQualificationClaimed'])
        self.assertFalse(receipt['applicationLibraryPatchOrAmbientImportAdded'])


if __name__=='__main__':unittest.main()
