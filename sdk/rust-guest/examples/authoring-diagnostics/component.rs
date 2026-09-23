//! Qualification capsule: intentionally bounded by the node's fuel and memory limits.
#[cfg(target_arch = "wasm32")]
mod component {
    use std::sync::atomic::{AtomicU32, Ordering};
    wit_bindgen::generate!({path: "wit", world: "service"});
    static COUNTER: AtomicU32 = AtomicU32::new(0);
    struct Capsule;
    impl exports::examples::authoring_diagnostics::api::Guest for Capsule {
        fn echo(value: exports::examples::authoring_diagnostics::api::Message) -> Result<exports::examples::authoring_diagnostics::api::Message, String> {
            if value.text.is_empty() { Err("text is required".into()) } else { Ok(value) }
        }
        fn fresh() -> u32 { COUNTER.fetch_add(1, Ordering::Relaxed) + 1 }
        fn trap() -> u32 { COUNTER.store(42, Ordering::Relaxed); panic!("intentional qualification trap") }
        fn spin() -> u32 {
            COUNTER.store(42, Ordering::Relaxed);
            loop { std::hint::black_box(COUNTER.load(Ordering::Relaxed)); }
        }
    }
    export!(Capsule);
}
