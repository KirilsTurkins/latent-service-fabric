//! Separately admitted entropy for the pinned CLR's noncryptographic seeds.
#![cfg(target_arch = "wasm32")]

wit_bindgen::generate!({
    path: "../../sdk/dotnet-guest/runtime/entropy/wit",
    world: "noncrypto",
    generate_all,
});

struct NoncryptoEntropy;

fn bytes(length: u64) -> Vec<u8> {
    assert!(length <= 65_536, "noncryptographic entropy length limit");
    if length == 0 {
        return Vec::new();
    }
    let value = latent::random::random::bytes(length as u32)
        .expect("explicit noncryptographic entropy request failed");
    assert_eq!(value.len() as u64, length, "noncryptographic entropy size mismatch");
    value
}

fn value() -> u64 {
    latent::random::random::u64_value()
        .expect("explicit noncryptographic entropy request failed")
}

impl exports::wasi::random0_2_0::insecure::Guest for NoncryptoEntropy {
    fn get_insecure_random_bytes(length: u64) -> Vec<u8> {
        bytes(length)
    }
    fn get_insecure_random_u64() -> u64 {
        value()
    }
}

impl exports::wasi::random0_2_6::insecure::Guest for NoncryptoEntropy {
    fn get_insecure_random_bytes(length: u64) -> Vec<u8> {
        bytes(length)
    }
    fn get_insecure_random_u64() -> u64 {
        value()
    }
}

export!(NoncryptoEntropy);
