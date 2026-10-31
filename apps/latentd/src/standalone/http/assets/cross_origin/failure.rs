//! CORS authority denial is distinct from transient resource/clock failures.
use latent_core::{PlatformError, PlatformErrorCode};

pub(super) fn selection_status(error: &PlatformError) -> u16 {
    // Retained signature/provenance expiry is a typed StateConflict, not a
    // PermissionDenied. It cannot authorize another read or a preflight. Do not
    // classify arbitrary conflicts or message text as expiry: clock regression,
    // contention and capacity must keep their existing unavailable semantics.
    let stale_proof = error.code == PlatformErrorCode::StateConflict
        && error.details.iter().any(|detail| {
            detail.kind == "admission.currentness"
                && detail
                    .fields
                    .get("reason")
                    .is_some_and(|reason| reason == "signature-stale-proof")
        });
    if stale_proof || error.code == PlatformErrorCode::RouteUnavailable {
        return 403;
    }
    match super::super::status(error) {
        400 | 401 | 403 | 404 => 403,
        status => status,
    }
}
