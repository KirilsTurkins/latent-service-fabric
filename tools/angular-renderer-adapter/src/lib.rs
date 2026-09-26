#![cfg(target_arch = "wasm32")]

#[allow(unsafe_code)] // Only wit-bindgen's generated canonical ABI and export.
mod abi;
#[cfg(feature = "backend-http")]
mod backend;
mod wire;

use abi::exports::latent::web::application::{Guest, Header, Method, Profile, Request, Response};
use base64::{engine::general_purpose::STANDARD, Engine as _};

const MAX_DOCUMENT_BYTES: usize = 128 * 1024;
const MAX_RESULT_FRAME_BYTES: usize = 1024 * 1024;

struct Adapter;
impl Guest for Adapter {
    async fn handle(request: Request) -> Response {
        let input = wire::request(&request);
        #[cfg(feature = "backend-http")]
        let input = wire::render_request(&request, backend::load(&input).await);
        let result = abi::latent::angular_renderer_internal::engine::render(&input);
        assert!(
            result.len() <= MAX_RESULT_FRAME_BYTES,
            "renderer-result-frame-limit"
        );
        let document: wire::Document =
            serde_json::from_str(&result).expect("renderer-result-contract");
        assert!(
            document.html.len() <= MAX_DOCUMENT_BYTES,
            "renderer-document-limit"
        );
        assert!(
            (200..=599).contains(&document.status),
            "renderer-status-contract"
        );
        assert!(document.headers.len() <= 64, "renderer-header-count");
        let mut bytes = 0usize;
        let headers = document
            .headers
            .into_iter()
            .map(|header| {
                bytes += header.name.len() + header.value.len();
                assert!(
                    !header.name.is_empty()
                        && header.name.len() <= 64
                        && header.value.len() <= 4096
                        && bytes <= 16 * 1024,
                    "renderer-header-limit"
                );
                Header {
                    name: header.name,
                    value: header.value,
                }
            })
            .collect();
        let representation = matches!(request.method, Method::Head) || document.status == 304;
        let representation_length = representation.then_some(document.html.len() as u64);
        let body_base64 = if representation || document.status == 204 {
            String::new()
        } else {
            STANDARD.encode(&document.html)
        };
        Response {
            profile: Profile::BufferedV1,
            status: document.status,
            headers,
            media_type: Some("text/html; charset=utf-8".into()),
            representation_length,
            body_base64,
        }
    }
}
