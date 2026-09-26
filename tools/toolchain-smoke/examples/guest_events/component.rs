#![cfg(target_arch = "wasm32")]

wit_bindgen::generate!({
    path: ["../../wit/platform/events-v2", "examples/guest_events"],
    world: "tests:nats-events/service@1.0.0",
    with: { "latent:events/publisher@0.2.0": latent_guest::bindings::events },
});

struct Capsule;
impl exports::tests::nats_events::api::Guest for Capsule {
    fn run(which: u32, text: String, handle: u64) -> u64 {
        probe(which, text, handle)
    }
}
export!(Capsule);

use latent_guest::events::{self, Event, EventError};
fn probe(_which: u32, text: String, handle: u64) -> u64 {
    let event = Event {
        topic: text,
        key: None,
        payload: b"payload".to_vec(),
        media_type: "text/plain".into(),
        attributes: vec![],
        idempotency_key: format!("guest-sdk-{handle}"),
    };
    match events::publish(&event) {
        Ok(receipt) => {
            assert!(!receipt.event_id.is_empty());
            assert!(!receipt.stream_name.is_empty());
            receipt.sequence
        }
        Err(EventError::PermissionDenied) => 10,
        Err(EventError::Uncertain) => 11, // Never retry an uncertain acknowledgement.
        Err(other) => panic!("unexpected publication error: {other:?}"),
    }
}
