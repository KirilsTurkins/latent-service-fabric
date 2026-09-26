#![cfg(target_arch = "wasm32")]

wit_bindgen::generate!({
    path: ["../../wit/platform/blob-v2", "examples/guest_blob"],
    world: "tests:local-blobs/service@1.0.0",
    with: { "latent:blob/blob@0.2.0": latent_guest::bindings::blob },
});

struct Capsule;
impl exports::tests::local_blobs::api::Guest for Capsule {
    async fn run(which: u32, text: String, handle: u64) -> u64 {
        probe(which, text, handle).await.unwrap_or_else(diagnostic)
    }
}
export!(Capsule);

use latent_guest::{
    bindings::blob as raw,
    blob::{Reader, Writer},
};

// Test-only, closed diagnostics: no provider messages, handles, or payloads are
// returned. Success expectations remain unchanged in both acceptance runners.
// Thousands identify the failed operation; the final two digits identify the
// WIT error. This makes a real-node failure actionable without guest panic logs.
fn diagnostic((operation, error): (u64, raw::BlobError)) -> u64 {
    let code = match error {
        raw::BlobError::NotFound => 1,
        raw::BlobError::PermissionDenied => 2,
        raw::BlobError::InvalidRange => 3,
        raw::BlobError::InvalidState => 4,
        raw::BlobError::ChecksumMismatch => 5,
        raw::BlobError::BudgetExhausted => 6,
        raw::BlobError::Unavailable => 7,
        raw::BlobError::Uncertain => 8,
        raw::BlobError::DeadlineExceeded => 9,
        raw::BlobError::Cancelled => 10,
    };
    operation * 1000 + code
}

async fn probe(which: u32, _text: String, handle: u64) -> Result<u64, (u64, raw::BlobError)> {
    if which == 2 || which == 4 {
        let handle = if which == 2 {
            let value = raw::create("text/plain".into(), Some(0))
                .await
                .map_err(|error| (1, error))?;
            assert!(raw::close(value).await.map_err(|error| (2, error))?);
            value
        } else {
            handle
        };
        return match raw::write(handle, 0, vec![]).await {
            Err(raw::BlobError::InvalidState) => Ok(10),
            Err(raw::BlobError::PermissionDenied) => Ok(11),
            Err(error) => Err((3, error)),
            Ok(_) => panic!("closed or foreign handle accepted"),
        };
    }
    if which == 5 {
        // This case returns an opaque handle, not a fixed success value. Keep
        // failure trapping so a diagnostic cannot masquerade as a stale handle.
        return Ok(raw::create("text/plain".into(), Some(0)).await.unwrap());
    }
    let mut writer = Writer::create("text/plain".into(), Some(4))
        .await
        .map_err(|error| (1, error))?;
    if which == 1 {
        let _abandoned_writer = writer;
        return Ok(1);
    }
    assert_eq!(
        writer
            .write(0, b"data".to_vec())
            .await
            .map_err(|error| (3, error))?,
        4
    );
    let reference = writer.seal().await.map_err(|error| (4, error))?;
    let mut reader = Reader::open(reference).await.map_err(|error| (5, error))?;
    let chunk = reader.read(0, 4).await.map_err(|error| (6, error))?;
    assert!(reader.close().await.map_err(|error| (2, error))?);
    if which == 3 {
        drop(chunk);
        return Ok(3);
    }
    let bytes = chunk.bytes().await.map_err(|error| (7, error))?;
    assert_eq!(bytes, b"data");
    Ok(bytes.len() as u64)
}
