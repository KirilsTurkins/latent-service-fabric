//! Standard NativeAOT WASI HTTP backend with explicitly admitted LSF authority.
#![cfg(target_arch = "wasm32")]

wit_bindgen::generate!({
    path: "../../sdk/dotnet-guest/runtime/wit",
    world: "http",
    generate_all,
});

#[path = "../../../sdk/dotnet-guest/runtime/http/io.rs"]
mod http_io;
#[path = "../../../sdk/dotnet-guest/runtime/http/types.rs"]
mod http_types;
#[path = "../../../sdk/dotnet-guest/runtime/http/owner.rs"]
mod owner;
#[path = "../../../sdk/dotnet-guest/runtime/http/poll.rs"]
mod poll;
#[path = "../../../sdk/dotnet-guest/runtime/http/pump.rs"]
mod pump;
#[path = "../../../sdk/dotnet-guest/runtime/http/quota.rs"]
mod quota;
#[path = "../../../sdk/dotnet-guest/runtime/http/state.rs"]
mod state;
#[path = "../../../sdk/dotnet-guest/runtime/http/timer.rs"]
mod timer;

use http_io::{Input as ClosedInput, Output as ClosedOutput};
use poll::Pollable as ClosedPoll;
struct ClosedError {
    _slot: quota::Slot,
}
include!("../../../sdk/dotnet-guest/runtime/closed_support.rs");
export!(ClosedRuntime);
