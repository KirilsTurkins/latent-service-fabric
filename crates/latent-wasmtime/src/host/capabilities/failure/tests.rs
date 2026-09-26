use super::*;
use latent_core::ErrorDetail;

const PRIVATE: &str = "private-token /private/path arbitrary provider input";

fn source(reason: &str) -> PlatformError {
    let signature = reason.starts_with("signature-");
    PlatformError {
        code: if signature {
            PlatformErrorCode::StateConflict
        } else {
            PlatformErrorCode::Unavailable
        },
        message: PRIVATE.into(),
        retryable: !signature,
        details: vec![ErrorDetail {
            kind: "admission.currentness".into(),
            fields: [("reason".into(), reason.into())].into(),
        }],
    }
}

#[test]
fn every_currentness_reason_requires_its_exact_constructor_code_and_retryability() {
    for &reason in ADMISSION_CURRENTNESS_REASONS {
        let error = source(reason);
        let failure = HostCapabilityFailure::from_error(&error);
        assert_eq!(failure.code(), error.code);
        assert_eq!(failure.currentness_reason(), Some(reason));
        let mut changed = error.clone();
        changed.retryable = !changed.retryable;
        assert_eq!(currentness_reason(&changed), None);
        for code in [
            PlatformErrorCode::Unavailable,
            PlatformErrorCode::StateConflict,
            PlatformErrorCode::PermissionDenied,
            PlatformErrorCode::GuestTrap,
            PlatformErrorCode::Internal,
        ] {
            if code != error.code {
                changed = error.clone();
                changed.code = code;
                assert_eq!(currentness_reason(&changed), None);
            }
        }
    }
}

#[test]
fn absent_unknown_and_malformed_details_never_preserve_a_reason() {
    let good = source("admission-authority-busy");
    let mut absent = good.clone();
    absent.details.clear();
    // A matching token in the message is not a structured currentness reason.
    absent.message = "admission-authority-busy".into();
    let mut duplicate = good.clone();
    duplicate.details.push(duplicate.details[0].clone());
    let mut foreign = good.clone();
    foreign.details[0].kind = "private.detail".into();
    let mut extra = good.clone();
    extra.details[0]
        .fields
        .insert("extra".into(), PRIVATE.into());
    let mut missing = good.clone();
    missing.details[0].fields.clear();
    let mut wrong_key = good.clone();
    wrong_key.details[0].fields =
        [("private-key".into(), "admission-authority-busy".into())].into();
    for error in [
        absent,
        duplicate,
        foreign,
        extra,
        missing,
        wrong_key,
        source("admission-new-future-reason"),
        source(PRIVATE),
        source("admission-authority-busy "),
    ] {
        let failure = HostCapabilityFailure::from_error(&error);
        assert_eq!(failure.code(), error.code);
        assert_eq!(failure.currentness_reason(), None);
        assert!(!format!("{failure:?}").contains("private"));
    }
}

#[test]
fn wrapped_error_keeps_existing_display_and_only_static_closed_diagnostics() {
    let error = source("admission-authority-busy");
    let original_reason = error.details[0].fields["reason"].as_ptr();
    let failure = HostCapabilityFailure::from_error(&error);
    assert_ne!(
        failure.currentness_reason().unwrap().as_ptr(),
        original_reason
    );
    assert_eq!(failure.to_string(), "capability admission: Unavailable");
    let wrapped = host_error(error).context(PRIVATE);
    let retained = wrapped.downcast_ref::<HostCapabilityFailure>().unwrap();
    assert_eq!(
        retained.currentness_reason(),
        Some("admission-authority-busy")
    );
    assert_eq!(retained.code(), PlatformErrorCode::Unavailable);
    assert!(!format!("{retained:?}").contains("private"));
}
