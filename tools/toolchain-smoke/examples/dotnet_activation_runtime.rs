//! Ordinary CLR Task/timer readiness without an HTTP capability import.
#![cfg(target_arch = "wasm32")]

wit_bindgen::generate!({
    path: "../../sdk/dotnet-guest/runtime/wit",
    world: "runtime",
    generate_all,
    async: [
        "export:wasi:io/poll@0.2.6#poll",
        "export:wasi:io/poll@0.2.6#[method]pollable.block",
        "export:latent:dotnet-retirement/owner@0.1.0#drain",
        "-export:wasi:io/streams@0.2.6#[method]input-stream.blocking-read",
        "-export:wasi:io/streams@0.2.6#[method]output-stream.blocking-flush",
    ],
});

#[path = "../../../sdk/dotnet-guest/runtime/console/closed.rs"]
mod console;
#[path = "../../../sdk/dotnet-guest/runtime/http/denied.rs"]
mod denied;
#[path = "../../../sdk/dotnet-guest/runtime/http/owner.rs"]
mod owner;
#[path = "../../../sdk/dotnet-guest/runtime/http/poll.rs"]
mod poll;
#[path = "../../../sdk/dotnet-guest/runtime/http/pump.rs"]
mod pump;
#[path = "../../../sdk/dotnet-guest/runtime/http/quota.rs"]
mod quota;
#[path = "../../../sdk/dotnet-guest/runtime/http/timer.rs"]
mod timer;

use poll::Pollable as ClosedPoll;
include!("../../../sdk/dotnet-guest/runtime/closed_io.rs");
include!("../../../sdk/dotnet-guest/runtime/closed_support.rs");
impl io::poll::Guest for ClosedRuntime {
    type Pollable = ClosedPoll;
    async fn poll(inputs: Vec<io::poll::PollableBorrow<'_>>) -> Vec<u32> {
        ClosedPoll::poll(inputs)
    }
}
impl exports::latent::dotnet_retirement::owner::Guest for ClosedRuntime {
    async fn drain() {
        pump::Pump::current().drain_retired();
    }
}
export!(ClosedRuntime);
