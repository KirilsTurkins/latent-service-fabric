//! Extend the registered native lifecycle case with typed expiry/refusal inputs.
//! The signed browser campaign separately exercises actual cryptographic expiry.
use super::support::*;
use crate::standalone::http::assets::integration::Harness;
use latent_artifacts::PublicationRef;
use latent_core::{ErrorDetail, PlatformError, PlatformErrorCode};

pub(super) async fn reject_stale_proof(h: &Harness, reference: &PublicationRef, conditional: &str) {
    use PlatformErrorCode::{CorruptArtifact, ResourceExhausted, StateConflict, Unavailable};

    let preflight = format!(
        "{}Access-Control-Request-Method: GET\r\nAccess-Control-Request-Headers: if-none-match\r\n",
        metadata(ORIGIN)
    );
    for (code, reason, status) in [
        (StateConflict, Some("signature-stale-proof"), 403),
        (StateConflict, Some("signature-clock-regression"), 503),
        (Unavailable, Some("admission-clock-lease-uncovered"), 503),
        (StateConflict, None, 503),
        (ResourceExhausted, None, 503),
        (CorruptArtifact, None, 502),
    ] {
        let error = PlatformError {
            code,
            // Message text alone must not be mistaken for typed currentness.
            message: "signature-stale-proof".into(),
            retryable: false,
            details: reason
                .map(|reason| ErrorDetail {
                    kind: "admission.currentness".into(),
                    fields: [("reason".into(), reason.into())].into(),
                })
                .into_iter()
                .collect(),
        };
        *h.admission_failure.lock().unwrap() = Some(error);
        for path in ["/app.js".to_owned(), immutable(reference, "/app.js")] {
            for (method, fields) in [
                ("GET", conditional),
                ("HEAD", conditional),
                ("OPTIONS", preflight.as_str()),
            ] {
                let (actual, headers, body) = call(h, method, &path, fields).await;
                assert_eq!(actual, status, "{method} {path}: {code:?} {reason:?}");
                assert!(body.is_empty());
                denied(&headers);
            }
        }
        *h.admission_failure.lock().unwrap() = None;
        // A transient refusal must not poison the cached body or consume a
        // read owner; only fresh current authority may allow its later reuse.
        assert_eq!(call(h, "GET", "/app.js", &metadata(ORIGIN)).await.0, 200);
    }
    no_execution(h);
}
