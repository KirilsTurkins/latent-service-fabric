#![cfg(target_arch = "wasm32")]

wit_bindgen::generate!({
    path: ["../../wit/platform/http-v2", "examples/guest_http"],
    world: "tests:http/service@1.0.0",
    with: { "latent:http/client@0.2.0": latent_guest::bindings::http },
});

struct Capsule;
impl exports::tests::http::api::Guest for Capsule {
    async fn run(which: u32, text: String, handle: u64) -> u64 {
        probe(which, text, handle).await
    }
}
export!(Capsule);

use latent_guest::http::{self, HttpError, Method, Request};
async fn probe(which: u32, text: String, _handle: u64) -> u64 {
    let method = match which {
        0 => Method::Get,
        1 => Method::Head,
        _ => Method::Post,
    };
    match http::send(Request {
        method,
        url: text,
        headers: vec![],
        body: Some(b"payload".to_vec()),
        body_media_type: Some("text/plain".into()),
        idempotency_key: None,
        timeout_millis: Some(1000),
    })
    .await
    {
        Ok(response) => u64::from(response.status) + 1000 * response.body.len() as u64,
        Err(HttpError::PermissionDenied) => 10,
        Err(HttpError::Uncertain) => 11,
        Err(other) => panic!("unexpected HTTP error: {other:?}"),
    }
}
