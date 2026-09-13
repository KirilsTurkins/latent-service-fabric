use sha2::{Digest, Sha256};
use std::hash::{Hash, Hasher};

// Hash is Wasmtime's documented native compatibility API. Capture its complete
// framed Hash stream, not DefaultHasher's truncated 64-bit result. This identity
// is scoped to the pinned Wasmtime/compiler/runtime format, not a general wire
// serialization of arbitrary Rust Hash implementations.
pub(super) fn engine(engine: &wasmtime::Engine) -> [u8; 32] {
    let mut digest = EngineHash(Sha256::new());
    digest.0.update(b"lsf-wasmtime-native-compatibility-v1\0");
    engine.precompile_compatibility_hash().hash(&mut digest);
    digest.0.finalize().into()
}
struct EngineHash(Sha256);
impl Hasher for EngineHash {
    fn write(&mut self, bytes: &[u8]) {
        super::frame(&mut self.0, bytes);
    }
    fn finish(&self) -> u64 {
        let digest = self.0.clone().finalize();
        u64::from_le_bytes(digest[..8].try_into().expect("SHA-256 width"))
    }
}
