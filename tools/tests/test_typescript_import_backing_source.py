"""Pinned embedding derivation, without a compiled allocator/runtime claim."""
import hashlib
import json
from pathlib import Path
import unittest

from tools.typescript_guest.import_engine import derive_import_backing_embedding

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / 'tools/tests/fixtures/typescript_import_backing_embedding.json'


class ImportBackingSourceTests(unittest.TestCase):
    def original(self):
        value = json.loads(FIXTURE.read_bytes())
        self.assertEqual(value['commit'], '4b8d6eb465b5cded6b97c67aaf6fdaa8b62001e2')
        self.assertEqual(value['path'], 'embedding/embedding.cpp')
        raw = value['source'].encode()
        self.assertEqual(len(raw), 18538)
        self.assertEqual(hashlib.sha256(raw).hexdigest(),
                         '0c083624ba85778cafe9aadbf81a3b9db63d6b632bb1760088098dd3a0b82cbb')
        return raw

    def test_original_allocator_zero_and_private_free_projection_is_exact(self):
        original = self.original()
        derived = derive_import_backing_embedding(original)
        zero = (b'  // Canonical fresh zero-byte values own no backing allocation.\n'
                b'  if (!ptr && orig_size == 0 && new_size == 0) return nullptr;\n')
        wrapper = (b'\n// Read-only diagnostic observation, never an ownership/refund ledger.\n'
                   b'struct LsfImportBackingFreeObservation { uint32_t returns; bool overflow; };\n'
                   b'static_assert(sizeof(LsfImportBackingFreeObservation) == 8);\n'
                   b'static LsfImportBackingFreeObservation lsf_import_backing_free_observation{};\n'
                   b'uint32_t lsf_import_backing_free_count() { return lsf_import_backing_free_observation.returns; }\n'
                   b'bool lsf_import_backing_free_overflow() { return lsf_import_backing_free_observation.overflow; }\n'
                   b'__attribute__((export_name("lsf_import_free_backing"))) void\n'
                   b'lsf_import_free_backing(void *ptr) {\n'
                   b'  cabi_free(ptr);\n'
                   b'  auto &observation = lsf_import_backing_free_observation;\n'
                   b'  if (observation.returns == 0xffffffffU) observation.overflow = true;\n'
                   b'  else ++observation.returns;\n'
                   b'}\n')
        self.assertEqual(derived.count(zero), 1)
        self.assertEqual(derived.count(wrapper), 1)
        self.assertEqual(derived.replace(zero, b'').replace(wrapper, b''), original)
        self.assertLess(derived.index(zero), derived.index(b'  void *ret = JS_realloc'))
        self.assertIn(b'void cabi_free(void *ptr) {\n  LOG("(cabi_free) %d", (uint32_t)ptr);\n  JS_free(Runtime.cx, ptr);\n}', derived)
        # Exact inverse proves the two original free_list additions, post_call,
        # adapter and ordinary nonzero realloc body were not silently replaced.
        self.assertEqual(original.count(b'Runtime.free_list.push_back'), 2)
        self.assertEqual(derived.count(b'Runtime.free_list.push_back'), 2)

    def test_repeated_or_ambiguous_embedding_extension_is_refused(self):
        original = self.original()
        with self.assertRaisesRegex(ValueError, 'already-extended'):
            derive_import_backing_embedding(derive_import_backing_embedding(original))
        anchor = b'  void *ret = JS_realloc(Runtime.cx, ptr, orig_size, new_size);\n'
        with self.assertRaises(ValueError):
            derive_import_backing_embedding(original + anchor)


if __name__ == '__main__':
    unittest.main()
