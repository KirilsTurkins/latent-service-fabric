#![cfg(target_arch = "wasm32")]

wit_bindgen::generate!({
    path: ["../../wit/platform/random", "examples/guest_random"],
    world: "tests:random/service@1.0.0",
    with: { "latent:random/random@0.1.0": latent_guest::bindings::random },
});

struct Capsule;
impl exports::tests::random::api::Guest for Capsule {
    fn run(which: u32, text: String, handle: u64) -> u64 {
        probe(which, text, handle)
    }
}
export!(Capsule);

use latent_guest::random;
fn probe(which: u32, _text: String, _handle: u64) -> u64 {
    match which {
        0 => random::bytes(32).expect("bounded entropy").len() as u64,
        1 => {
            let _value = random::u64_value().expect("bounded integer");
            8
        }
        2 => match random::bytes(u32::MAX) {
            Err(random::RandomError::InvalidLength) => 10,
            other => panic!("unexpected result: {other:?}"),
        },
        3 => random::u64_value().expect("exact entropy fixture value"),
        4 => u64::from_le_bytes(
            random::bytes(8)
                .expect("exact entropy fixture bytes")
                .try_into()
                .expect("eight bytes"),
        ),
        5 => match random::bytes(8) {
            Err(random::RandomError::Unavailable) => 11,
            other => panic!("unexpected denied result: {other:?}"),
        },
        _ => panic!("unknown probe"),
    }
}
