use latent_core::{PlatformError, PlatformErrorCode};

/// Only the broker's exact bookkeeping contention or the closed admission
/// authority-fence diagnostic may be inspected again under the original
/// deadline. Capacity, unavailable authority, retirement and accepted provider
/// effects must never be retried using this predicate.
#[must_use]
pub fn is_authority_bookkeeping_busy(error: &PlatformError) -> bool {
    if error.code == PlatformErrorCode::ResourceExhausted
        && error.message == "capability-busy"
        && !error.retryable
        && error.details.is_empty()
    {
        return true;
    }
    let [detail] = error.details.as_slice() else {
        return false;
    };
    error.code == PlatformErrorCode::Unavailable
        && error.retryable
        && detail.kind == "admission.currentness"
        && detail.fields.len() == 1
        && detail.fields.get("reason").map(String::as_str) == Some("admission-authority-busy")
}

#[cfg(test)]
mod tests {
    use super::*;
    use latent_core::{ErrorDetail, Metadata};

    #[test]
    fn only_exact_authority_bookkeeping_contention_is_waitable() {
        assert!(is_authority_bookkeeping_busy(&super::super::busy()));
        assert!(!is_authority_bookkeeping_busy(&super::super::capacity()));
        assert!(!is_authority_bookkeeping_busy(&super::super::denied()));
        let error = PlatformError {
            code: PlatformErrorCode::Unavailable,
            message: "redacted authority unavailable".into(),
            retryable: true,
            details: vec![ErrorDetail {
                kind: "admission.currentness".into(),
                fields: Metadata::from([("reason".into(), "admission-authority-busy".into())]),
            }],
        };
        assert!(is_authority_bookkeeping_busy(&error));
        let mut malformed = error.clone();
        malformed.details.clear();
        malformed.message = "admission-authority-busy".into();
        assert!(!is_authority_bookkeeping_busy(&malformed));
        for reason in [
            "admission-authority-unavailable",
            "signature-stale-proof",
            "admission-authority-busy ",
        ] {
            let mut malformed = error.clone();
            malformed.details[0]
                .fields
                .insert("reason".into(), reason.into());
            assert!(!is_authority_bookkeeping_busy(&malformed));
        }
        for code in [
            PlatformErrorCode::PermissionDenied,
            PlatformErrorCode::ResourceExhausted,
        ] {
            let mut malformed = error.clone();
            malformed.code = code;
            assert!(!is_authority_bookkeeping_busy(&malformed));
        }
        let mut malformed = error.clone();
        malformed.retryable = false;
        assert!(!is_authority_bookkeeping_busy(&malformed));
        let mut malformed = error.clone();
        malformed.details[0]
            .fields
            .insert("endpoint".into(), "private".into());
        assert!(!is_authority_bookkeeping_busy(&malformed));
        let mut malformed = error.clone();
        malformed.details.push(malformed.details[0].clone());
        assert!(!is_authority_bookkeeping_busy(&malformed));
        let mut malformed = super::super::busy();
        malformed.retryable = true;
        assert!(!is_authority_bookkeeping_busy(&malformed));
    }
}
