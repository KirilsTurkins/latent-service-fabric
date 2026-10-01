//! Explicitly admitted wall clock for the pinned NativeAOT runtime.
#![cfg(target_arch = "wasm32")]

wit_bindgen::generate!({
    path: "../../sdk/dotnet-guest/runtime/wit",
    world: "wall",
    generate_all,
});

struct WallClock;

impl exports::wasi::clocks::wall_clock::Guest for WallClock {
    fn now() -> exports::wasi::clocks::wall_clock::Datetime {
        let millis = latent::clock::wall::now_unix_millis();
        exports::wasi::clocks::wall_clock::Datetime {
            seconds: millis / 1_000,
            // The declared host clock has millisecond precision. Taking the
            // remainder before multiplication avoids overflowing at u64::MAX.
            nanoseconds: u32::try_from((millis % 1_000) * 1_000_000)
                .expect("millisecond remainder fits the datetime nanoseconds"),
        }
    }
}

export!(WallClock);
