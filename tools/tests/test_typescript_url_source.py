"""Closed maintained native URL inputs; actual runtime tests remain separate."""
from pathlib import Path
import unittest
from tools.typescript_guest import url_engine, runtime_profile
from tools.typescript_guest.activation_engine import engine_input_paths

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT/'tools/tests/fixtures/typescript_url'


class TypeScriptUrlSourceTests(unittest.TestCase):
    def original(self):
        return {name: (FIXTURES/file).read_bytes() for name, file in (
            (url_engine.CPP, 'original-url.cpp'), (url_engine.HEADER, 'original-url.h'),
            (url_engine.RUST_HEADER, 'original-rust-url.h'), (url_engine.RUST, 'original-rust-url.rs'))}

    def owner(self):
        return (ROOT/'sdk/typescript-guest/activation/native_url_owner.h').read_bytes()

    def test_exact_native_parser_selection_grants_no_authority_or_api_qualification(self):
        _, observed = url_engine.derive(self.original(), self.owner())
        self.assertEqual(observed['qualification'], 'unknown')
        self.assertFalse(observed['signedLSFComponentQualified'])
        self.assertFalse(observed['ordinaryImportProfileChanged'])
        self.assertFalse(observed['BlobFileWorkerRandomSelected'])
        self.assertEqual(observed['originalNativeObjectCeiling'], 64)

    def test_each_changed_original_cpp_header_rust_or_ffi_input_is_rejected(self):
        for name in url_engine.PREIMAGES:
            with self.subTest(source=name):
                changed = self.original()
                changed[name] += b'\n'
                with self.assertRaisesRegex(ValueError, 'unreviewed-maintained-URL-source'):
                    url_engine.derive(changed, self.owner())

    def test_missing_extra_or_ownerless_selection_is_rejected(self):
        original = self.original()
        for changed in ({key: raw for key, raw in original.items() if key != url_engine.RUST},
                        dict(original, extra=b'other source')):
            with self.assertRaisesRegex(ValueError, 'exact-maintained-URL-source-required'):
                url_engine.derive(changed, self.owner())
        with self.assertRaisesRegex(ValueError, 'exact-maintained-URL-source-required'):
            url_engine.derive(original, b'')

    def test_fetch_source_closure_binds_native_parser_but_ordinary_imports_do_not(self):
        selected = set(engine_input_paths(runtime_profile.FETCH_PROFILE))
        self.assertLessEqual(len(selected), 64)
        self.assertIn('sdk/typescript-guest/activation/native_url_owner.h', selected)
        self.assertIn('tools/typescript_guest/url_engine.py', selected)
        self.assertNotIn('sdk/typescript-guest/activation/native_url_owner.h',
                         engine_input_paths(runtime_profile.IMPORT_PROFILE))

    def test_exact_aggregate_retains_encoding_hooks_and_url_dependency_versions(self):
        from tools.typescript_guest import url_rust_graph
        original = {name: (FIXTURES/name).read_bytes() for name in url_rust_graph.PREIMAGES}
        _, observed = url_rust_graph.derive(original)
        self.assertEqual(observed['selectedCrates'], ['rust-encoding', 'rust-hooks', 'rust-url'])
        self.assertEqual(observed['selectedPackageCount'], 46)
        self.assertTrue(observed['selectedVersionsAndChecksumsPreserved'])
        self.assertFalse(observed['separateDuplicateRustArchives'])
        self.assertFalse(observed['multipartSelected'])

    def test_changed_or_incomplete_aggregate_cannot_change_the_selected_parser_graph(self):
        from tools.typescript_guest import url_rust_graph
        original = {name: (FIXTURES/name).read_bytes() for name in url_rust_graph.PREIMAGES}
        for name in original:
            changed = dict(original)
            changed[name] += b'\n'
            with self.assertRaisesRegex(ValueError, 'unreviewed-maintained-URL-aggregate'):
                url_rust_graph.derive(changed)
        with self.assertRaisesRegex(ValueError, 'exact-maintained-URL-aggregate-required'):
            url_rust_graph.derive({})
