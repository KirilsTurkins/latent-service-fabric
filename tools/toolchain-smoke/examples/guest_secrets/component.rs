#![cfg(target_arch = "wasm32")]

wit_bindgen::generate!({
    path: ["../../wit/platform/secrets", "examples/guest_secrets"],
    world: "tests:local-secrets/service@1.0.0",
    with: { "latent:secrets/reader@0.1.0": latent_guest::bindings::secrets },
});

struct Capsule;
impl exports::tests::local_secrets::api::Guest for Capsule {
    fn run(which: u32, text: String, handle: u64) -> u64 {
        probe(which, text, handle)
    }
}
export!(Capsule);

use latent_guest::secrets::{Secret, SecretError};
fn probe(_which: u32, text: String, _handle: u64) -> u64 {
    match Secret::read(&text) {
        Ok(secret) => {
            let count = secret.bytes().len();
            drop(secret);
            count as u64
        }
        Err(SecretError::PermissionDenied) => 10,
        Err(SecretError::NotFound) => 11,
        Err(SecretError::Expired) => 12,
        Err(SecretError::Unavailable) => 13,
    }
}
