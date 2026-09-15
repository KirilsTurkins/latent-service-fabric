#![cfg(target_arch = "wasm32")]

wit_bindgen::generate!({
    path: ["../../wit/platform/http-v3", "examples/guest_streaming"],
    world: "tests:streaming-http/service@1.0.0",
    with: { "latent:http/streaming@0.3.0": latent_guest::bindings::streaming },
});

struct Capsule;
impl exports::tests::streaming_http::api::Guest for Capsule {
    async fn run(which: u32, text: String, handle: u64) -> u64 {
        probe(which, text, handle).await
    }
}
export!(Capsule);

use latent_guest::streaming::{HttpError, Method, Request, Upload};
async fn probe(which: u32, text: String, _handle: u64) -> u64 {
    let upload = Upload::open(Request {
        method: Method::Post,
        url: text,
        headers: vec![],
        body_length: Some(4),
        body_media_type: Some("text/plain".into()),
        idempotency_key: None,
        timeout_millis: Some(1000),
    })
    .await;
    let mut upload = match upload {
        Ok(value) => value,
        Err(HttpError::PermissionDenied) => return 10,
        Err(other) => panic!("unexpected open error: {other:?}"),
    };
    if which == 1 {
        drop(upload);
        return 1;
    }
    upload.write(b"data".to_vec()).await.expect("write chunk");
    let mut response = upload.finish().await.expect("finish upload");
    if which == 2 {
        drop(response);
        return 2;
    }
    if which == 3 {
        let chunk = response.body.read(4).await.unwrap().unwrap();
        drop(response);
        return chunk.bytes().await.unwrap().len() as u64;
    }
    let mut count = 0;
    while let Some(chunk) = response.body.read(4).await.expect("complete response") {
        count += chunk.bytes().await.expect("one materialization").len() as u64;
    }
    let _trailers = response.body.trailers().await.expect("verified EOF");
    assert!(matches!(
        response.body.trailers().await,
        Err(HttpError::InvalidState)
    ));
    count
}
