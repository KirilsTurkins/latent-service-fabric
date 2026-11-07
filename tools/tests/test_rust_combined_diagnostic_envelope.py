"""Boundary controls for the diagnostic-only fixed Rust component wrapper."""
import hashlib
from pathlib import Path
import unittest

from tools import rust_combined_diagnostic_envelope as envelope
from tools import rust_original_delta as delta

ROOT = Path(__file__).resolve().parents[2]
CATALOGUE = ROOT / 'crates/latent-component-threading/src/rust_catalogue'


class RustCombinedDiagnosticEnvelope(unittest.TestCase):
    def test_retained_sample_produces_exact_bounded_untrusted_component(self):
        original = (CATALOGUE / 'combined-original-core.wasm').read_bytes()
        base = (CATALOGUE / 'combined-final-component.wasm').read_bytes()
        proof = delta.encode(original, base)
        self.assertEqual(proof, (CATALOGUE / 'combined-original-delta.bin').read_bytes())
        wrapped = envelope.frame(base, proof)
        self.assertEqual(wrapped[:len(base)], base)
        self.assertEqual(len(wrapped), 1_629_518)
        self.assertEqual(hashlib.sha256(wrapped).hexdigest(),
            '5634429a97b4a3f0cf8afca2877dbbddbc98f5e4fd7bf59ae6f7f50e780c2e17')
        self.assertLessEqual(len(wrapped), delta.MAX_BASE)

    def test_truncated_duplicate_noncanonical_and_oversized_inputs_refuse(self):
        original = (CATALOGUE / 'combined-original-core.wasm').read_bytes()
        base = (CATALOGUE / 'combined-final-component.wasm').read_bytes()
        proof = delta.encode(original, base)
        wrapped = envelope.frame(base, proof)
        for candidate, material in ((b'bad', proof), (base, b'bad'), (wrapped, proof),
                                    (base[:-1], proof), (base, proof[:8]),
                                    (base + b'\x00\x80\x00', proof),
                                    (b'\0' * (delta.MAX_BASE + 1), proof)):
            with self.subTest(component=len(candidate), proof=len(material)):
                with self.assertRaises(ValueError):
                    envelope.frame(candidate, material)
        for raw in (b'\x80', b'\x80\x00', b'\xff\xff\xff\xff\x10'):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                envelope.read_u32(raw, 0)


if __name__ == '__main__':
    unittest.main()
