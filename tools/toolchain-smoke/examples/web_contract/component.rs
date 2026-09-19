#![cfg(target_arch = "wasm32")]
use bindings::exports::latent::web::application::{Guest, Header, Profile, Request, Response};
use latent_component_bindings::web_guest as bindings;
mod browser;

struct Capsule;
impl Guest for Capsule {
    async fn handle(request: Request) -> Response {
        if request.path == "/api/greeting" {
            let accepted = matches!(
                request.method,
                bindings::exports::latent::web::application::Method::Post
            ) && request.media_type.as_deref() == Some("application/json")
                && request.body_base64 == "eyJuYW1lIjoiQnJvd3NlciJ9";
            return Response {
                profile: Profile::BufferedV1,
                status: if accepted { 200 } else { 400 },
                headers: vec![
                    Header {
                        name: "cache-control".into(),
                        value: b"no-store".to_vec(),
                    },
                    Header {
                        name: "x-app-principal".into(),
                        value: bindings::latent::context::context::principal()
                            .subject
                            .into_bytes(),
                    },
                ],
                media_type: Some("application/json".into()),
                representation_length: None,
                body_base64: if accepted {
                    "eyJncmVldGluZyI6IkhlbGxvIEJyb3dzZXIifQ=="
                } else {
                    "eyJlcnJvciI6ImJhZC1yZXF1ZXN0In0="
                }
                .into(),
            };
        }
        if request.path == "/spin" {
            loop {
                std::hint::black_box(0u8);
            }
        }
        if request.path == "/trap" {
            unreachable!("deliberate web contract fixture trap");
        }
        if let Some(response) = browser::response(&request.path) {
            return response;
        }
        if request.path == "/cache" {
            let cookie = request
                .headers
                .iter()
                .find(|header| header.name == "cookie");
            let body = match cookie.map(|header| header.value.as_slice()) {
                Some(b"session=alice") => "YWxpY2U=",
                Some(b"session=bob") => "Ym9i",
                Some(_) => "cHJpdmF0ZQ==",
                None => "cHVibGlj",
            };
            return Response {
                profile: Profile::BufferedV1,
                status: 200,
                headers: vec![Header {
                    name: "cache-control".into(),
                    value: b"public, max-age=60".to_vec(),
                }],
                media_type: Some("text/plain".into()),
                representation_length: None,
                body_base64: body.into(),
            };
        }
        let principal = bindings::latent::context::context::principal();
        let mut headers = request.headers;
        headers.push(Header {
            name: "x-activation".into(),
            value: bindings::latent::context::context::activation_id().into_bytes(),
        });
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
            status: if request.path == "/invalid-response" {
                99
            } else {
                200
            },
            headers,
            media_type: Some("application/octet-stream".into()),
            representation_length: None,
            body_base64,
        }
    }
}
bindings::export!(Capsule with_types_in bindings);
