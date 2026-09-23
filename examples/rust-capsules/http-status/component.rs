//! One bounded HTTP request; the host, not this capsule, chooses its authority.
#![cfg(target_arch = "wasm32")]

wit_bindgen::generate!({
    path: "wit",
    world: "examples:http-status/service@1.0.0",
    with: { "latent:http/client@0.2.0": latent_guest::bindings::http },
});

struct Capsule;
impl exports::examples::http_status::api::Guest for Capsule {
    async fn check(url: String) -> Result<u16, latent_guest::http::HttpError> {
        use latent_guest::http::{self, Method, Request};
        let response = http::send(Request {
            method: Method::Get,
            url,
            headers: vec![],
            body: None,
            body_media_type: None,
            idempotency_key: None,
            timeout_millis: Some(4000),
        })
        .await?;
        Ok(response.status)
    }
}
export!(Capsule);
