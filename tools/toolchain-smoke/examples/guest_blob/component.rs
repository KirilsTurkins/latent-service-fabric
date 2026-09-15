#![cfg(target_arch = "wasm32")]

wit_bindgen::generate!({
    path: ["../../wit/platform/blob-v2", "examples/guest_blob"],
    world: "tests:local-blobs/service@1.0.0",
    with: { "latent:blob/blob@0.2.0": latent_guest::bindings::blob },
});

struct Capsule;
impl exports::tests::local_blobs::api::Guest for Capsule {
    async fn run(which: u32, text: String, handle: u64) -> u64 {
        probe(which, text, handle).await
    }
}
export!(Capsule);

use latent_guest::{
    bindings::blob as raw,
    blob::{Reader, Writer},
};
async fn probe(which: u32, _text: String, handle: u64) -> u64 {
    if which == 2 || which == 4 {
        let handle = if which == 2 {
            let value = raw::create("text/plain".into(), Some(0)).await.unwrap();
            assert!(raw::close(value).await.unwrap());
            value
        } else {
            handle
        };
        return match raw::write(handle, 0, vec![]).await {
            Err(raw::BlobError::InvalidState) => 10,
            Err(raw::BlobError::PermissionDenied) => 11,
            other => panic!("closed or foreign handle: {other:?}"),
        };
    }
    if which == 5 {
        return raw::create("text/plain".into(), Some(0)).await.unwrap();
    }
    let mut writer = Writer::create("text/plain".into(), Some(4)).await.unwrap();
    if which == 1 {
        let _abandoned_writer = writer;
        return 1;
    }
    assert_eq!(writer.write(0, b"data".to_vec()).await.unwrap(), 4);
    let reference = writer.seal().await.unwrap();
    let mut reader = Reader::open(reference).await.unwrap();
    let chunk = reader.read(0, 4).await.unwrap();
    assert!(reader.close().await.unwrap());
    if which == 3 {
        drop(chunk);
        return 3;
    }
    let bytes = chunk.bytes().await.unwrap();
    assert_eq!(bytes, b"data");
    bytes.len() as u64
}
