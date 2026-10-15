//! Ordinary CLR Task/timer readiness without an HTTP capability import.
#![cfg(target_arch = "wasm32")]

wit_bindgen::generate!({
    path: "../../sdk/dotnet-guest/runtime/wit",
    world: "runtime",
    generate_all,
    async: [
        "export:wasi:io/poll@0.2.6#poll",
        "export:wasi:io/poll@0.2.6#[method]pollable.block",
    ],
});

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
export!(ClosedRuntime);
