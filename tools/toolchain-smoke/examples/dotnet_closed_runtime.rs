//! Capability-constrained WASI support for the pinned NativeAOT library profile.
//! GC timing requires the explicitly admitted LSF monotonic clock. This guest
//! adapter neither obtains ambient authority nor owns an OS resource.
#![cfg(target_arch = "wasm32")]

wit_bindgen::generate!({
    path: "../../sdk/dotnet-guest/runtime/wit",
    world: "closed",
    with: {
        "latent:clock/monotonic@0.1.0": generate,
    },
});

#[path = "../../../sdk/dotnet-guest/runtime/http/denied.rs"]
mod denied;
#[path = "../../../sdk/dotnet-guest/runtime/http/quota.rs"]
mod quota;

struct ClosedPoll {
    _slot: quota::Slot,
}
impl ClosedPoll {
    fn closed() -> exports::wasi::io::poll::Pollable {
        exports::wasi::io::poll::Pollable::new(Self {
            _slot: quota::Slot::new(),
        })
    }
    fn poll(inputs: Vec<exports::wasi::io::poll::PollableBorrow<'_>>) -> Vec<u32> {
        assert!(
            !inputs.is_empty() && inputs.len() <= 64,
            "WASI poll input limit"
        );
        // Subscriptions in this profile refer only to already closed streams.
        (0..inputs.len()).map(|index| index as u32).collect()
    }
    fn timer(_nanos: u64, _absolute: bool) -> exports::wasi::io::poll::Pollable {
        panic!("WASI timers require the separately admitted activation runtime")
    }
}
impl io::poll::GuestPollable for ClosedPoll {
    fn block(&self) {}
}
include!("../../../sdk/dotnet-guest/runtime/closed_io.rs");
include!("../../../sdk/dotnet-guest/runtime/closed_support.rs");
export!(ClosedRuntime);
