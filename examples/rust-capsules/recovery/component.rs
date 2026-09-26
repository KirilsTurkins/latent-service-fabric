//! Deliberate faults for the bounded lifecycle acceptance test, not application logic.
#![cfg(target_arch = "wasm32")]
use std::sync::atomic::{AtomicU32, Ordering};

wit_bindgen::generate!({ path: "wit", world: "examples:recovery/service@1.0.0" });
static CALLS: AtomicU32 = AtomicU32::new(0);
struct Capsule;
impl exports::examples::recovery::api::Guest for Capsule {
    fn run(which: u32) -> u32 {
        match which {
            1 => panic!("deliberate recovery-test trap"),
            2 => {
                let mut bytes = vec![1_u8; 64 * 1024 * 1024];
                std::hint::black_box(&mut bytes);
            }
            3 => loop {
                std::hint::spin_loop();
            },
            _ => {}
        }
        CALLS.fetch_add(1, Ordering::Relaxed) + 1
    }
}
export!(Capsule);
