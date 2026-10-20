//! Selected standard WASI 0.2.12 client backend, over original typed authority.
#![cfg(target_arch = "wasm32")]

wit_bindgen::generate!({
    path: "../../sdk/wasi-http-runtime/wit",
    world: "client",
    generate_all,
    async: [
        "export:wasi:io/poll@0.2.12#poll",
        "export:wasi:io/poll@0.2.12#[method]pollable.block",
        "export:wasi:io/streams@0.2.12#[method]input-stream.blocking-read",
        "export:wasi:io/streams@0.2.12#[method]input-stream.blocking-skip",
        "export:wasi:io/streams@0.2.12#[method]output-stream.blocking-write-and-flush",
        "export:wasi:io/streams@0.2.12#[method]output-stream.blocking-flush",
        "export:wasi:io/streams@0.2.12#[method]output-stream.blocking-write-zeroes-and-flush",
        "export:wasi:io/streams@0.2.12#[method]output-stream.blocking-splice",
        "export:latent:rust-http-retirement/owner@0.1.0#drain",
    ],
});

#[path = "../../../sdk/wasi-http-runtime/error.rs"]
mod error;
#[path = "../../../sdk/wasi-http-runtime/fields.rs"]
mod fields;
#[path = "../../../sdk/wasi-http-runtime/io.rs"]
mod http_io;
#[path = "../../../sdk/wasi-http-runtime/types.rs"]
mod http_types;
#[path = "../../../sdk/wasi-http-runtime/limits.rs"]
mod limits;
#[path = "../../../sdk/wasi-http-runtime/poll.rs"]
mod poll;
#[path = "../../../sdk/wasi-http-runtime/request_options.rs"]
mod request_options;
#[path = "../../../sdk/wasi-http-runtime/state.rs"]
mod state;

// These exact shared owners, cap and readiness machinery are not a second
// provider, runtime budget, cache or executor. The existing .NET source/output
// stays unchanged; each selected component has only this one instance.
#[path = "../../../sdk/dotnet-guest/runtime/http/owner.rs"]
mod owner;
#[path = "../../../sdk/dotnet-guest/runtime/http/pump.rs"]
mod pump;
#[path = "../../../sdk/dotnet-guest/runtime/http/quota.rs"]
mod quota;
#[path = "../../../sdk/dotnet-guest/runtime/http/timer.rs"]
mod timer;

use error::HttpError;
use exports::wasi::{clocks::monotonic_clock, io};
struct StandardRuntime;

impl io::error::Guest for StandardRuntime {
    type Error = HttpError;
}
impl io::poll::Guest for StandardRuntime {
    type Pollable = poll::Pollable;
    async fn poll(inputs: Vec<io::poll::PollableBorrow<'_>>) -> Vec<u32> {
        poll::Pollable::poll(inputs)
    }
}
impl monotonic_clock::Guest for StandardRuntime {
    fn now() -> u64 {
        latent::clock::monotonic::now_nanos()
    }
    fn resolution() -> u64 {
        // The host's existing monotonic API does not expose an authenticated
        // resolution. This WIT signature has no error channel: do not invent a
        // precision, zero success, clock source or authority.
        panic!("unsupported-wasi-monotonic-clock-resolution")
    }
    fn subscribe_instant(when: u64) -> io::poll::Pollable {
        poll::Pollable::timer(when, true)
    }
    fn subscribe_duration(when: u64) -> io::poll::Pollable {
        poll::Pollable::timer(when, false)
    }
}
impl exports::latent::rust_http_retirement::owner::Guest for StandardRuntime {
    async fn drain() {
        pump::Pump::current().drain_retired();
    }
}
export!(StandardRuntime);
