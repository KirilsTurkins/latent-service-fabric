#![cfg(target_arch = "wasm32")]
use bindings::exports::latent::web::application::{Guest, Header, Profile, Request, Response};
use latent_component_bindings::web_guest as bindings;

struct Capsule;
impl Guest for Capsule {
    async fn handle(request: Request) -> Response {
        let principal = bindings::latent::context::context::principal();
        let mut headers = request.headers;
        headers.push(Header {
            name: "x-subject".into(),
            value: principal.subject.into_bytes(),
        });
        let body_base64 = if request.path == "/maximum" {
            // Exactly 256 KiB of 0xff in canonical base64; no provider needed.
            let mut encoded = "////".repeat(87_381);
            encoded.push_str("/w==");
            encoded
        } else {
            request.body_base64
        };
        Response {
            profile: Profile::BufferedV1,
            status: 200,
            headers,
            media_type: Some("application/octet-stream".into()),
            representation_length: None,
            body_base64,
        }
    }
}
bindings::export!(Capsule with_types_in bindings);
