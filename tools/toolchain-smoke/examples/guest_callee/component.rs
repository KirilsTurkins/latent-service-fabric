#![cfg(target_arch = "wasm32")]
wit_bindgen::generate!({ path: "examples/guest_callee", world: "tests:local/service@1.0.0" });
struct Capsule;
impl exports::tests::local::api::Guest for Capsule {
    fn answer() -> u32 {
        42
    }
    fn fail() -> Result<u32, String> {
        Err("declared application failure".into())
    }
    fn spin() -> u32 {
        loop {
            core::hint::spin_loop();
        }
    }
}
export!(Capsule);
