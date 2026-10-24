"""Exact original compiler derivation controls, without a compiler/runtime claim."""
import hashlib
import json
from pathlib import Path
import unittest

from tools.typescript_guest.import_bindgen import derive_async_bindgen, derive_async_splice
from tools.typescript_guest.import_engine import SOURCE_PREIMAGES

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / 'tools/tests/fixtures/typescript_owned_result_compiler.json'


class TypeScriptOwnedResultSourceTests(unittest.TestCase):
    def originals(self):
        fixture = json.loads(FIXTURE.read_bytes())
        self.assertEqual(fixture['commit'], '4b8d6eb465b5cded6b97c67aaf6fdaa8b62001e2')
        self.assertEqual(set(fixture['sources']), set(SOURCE_PREIMAGES))
        result = {}
        for name, entry in fixture['sources'].items():
            raw = entry['source'].encode()
            self.assertEqual(len(raw), entry['bytes'])
            self.assertEqual(hashlib.sha256(raw).hexdigest(), entry['sha256'])
            self.assertEqual(entry['sha256'], SOURCE_PREIMAGES[name])
            result[name] = raw
        return result

    def test_actual_resource_import_namespace_and_sync_export_generator_are_preserved(self):
        original = self.originals()['crates/spidermonkey-embedding-splicer/src/bindgen.rs']
        derived, receipt = derive_async_bindgen(original)
        # The complete original resource mapping, including exported-resource
        # new/rep/drop bindings, survives. Only the imported drop identity gains
        # the compiler-private descriptor binding immediately before its push.
        before = original[original.index(b'    let mut resource_bindings = Vec::new();'):
                          original.index(b'    let finalization_registries = finalization_registries.concat();')]
        after = derived[derived.index(b'    let mut resource_bindings = Vec::new();'):
                        derived.index(b'    for descriptor in bindgen.lsf_async_imports.values_mut()')]
        after = after.replace(b'    let mut lsf_resource_drops = BTreeMap::new();\n', b'')
        after = after.replace(b'        lsf_resource_drops.insert(id,(impt.clone(),format!("[resource-drop]{resource_name_kebab}")));\n', b'')
        self.assertEqual(after, before)
        self.assertIn(b'lsf-owned-result-transfer:{}', derived)
        self.assertIn(b'if f.err == ErrHandling::ThrowResultErr { "wit-result" } else { "value" }', derived)
        self.assertFalse(receipt['actualCompilerExecuted'])

    def test_actual_splicer_keeps_sync_body_and_contiguous_original_import_bindings(self):
        original = self.originals()['crates/spidermonkey-embedding-splicer/src/splice.rs']
        derived, receipt = derive_async_splice(original)
        start = b'            // create the native JS binding function\n'
        end = b'        // extend the main table to include indices for generated imported functions\n'
        self.assertEqual(original[original.index(start):original.index(end)],
                         derived[derived.index(start):derived.index(end)])
        self.assertIn(b'import_fnids.into_iter().chain(lsf_disposers)', derived)
        self.assertIn(b'let disposer=lsf_async_splice::resource_disposer(module,descriptor,imports)?;', derived)
        self.assertLess(derived.index(b'lsf_async_splice::validate_disposer_table_append(module)?;'),
                        derived.index(b'for (import_index,(impt_specifier,'))
        self.assertIn(b'checked_add(i32::try_from(imports.len())?)', derived)
        self.assertTrue(receipt['originalSynchronousSpliceSignatureRetained'])
        self.assertFalse(receipt['actualCompilerExecuted'])

    def test_changed_upstream_source_refuses_before_any_derivation(self):
        original = self.originals()
        for name, derive in [('bindgen', derive_async_bindgen), ('splice', derive_async_splice)]:
            raw = original['crates/spidermonkey-embedding-splicer/src/' + name + '.rs']
            with self.assertRaisesRegex(ValueError, 'unreviewed-original-async'):
                derive(raw + b'\n')


if __name__ == '__main__':
    unittest.main()
