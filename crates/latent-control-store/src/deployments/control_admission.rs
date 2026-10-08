//! Closed failure location for an existing authenticated preparation error.

use latent_core::{ErrorDetail, Metadata, PlatformError, PlatformErrorCode};

#[derive(Clone, Copy)]
pub(super) enum Stage {
    PrepareLease,
    PackageLease,
    PackageRead,
    PackageLifecycle,
    PackageTenant,
    InheritedBindings,
}

impl Stage {
    const fn name(self) -> &'static str {
        match self {
            Self::PrepareLease => "prepare-lease",
            Self::PackageLease => "package-lease",
            Self::PackageRead => "package-read",
            Self::PackageLifecycle => "package-lifecycle",
            Self::PackageTenant => "package-tenant",
            Self::InheritedBindings => "inherited-bindings",
        }
    }
}

pub(super) fn annotate(control: bool, stage: Stage, mut failure: PlatformError) -> PlatformError {
    // Report only the closed typed reason, never caller input or an engine's
    // error text. The first (innermost) location wins, so nesting adds one row.
    if control
        && failure.code == PlatformErrorCode::Unavailable
        && failure.details.iter().any(|detail| {
            detail.kind == "admission.currentness"
                && detail
                    .fields
                    .get("reason")
                    .is_some_and(|reason| reason == "admission-clock-lease-uncovered")
        })
        && !failure
            .details
            .iter()
            .any(|detail| detail.kind == "admission.control-stage")
    {
        failure.details.push(ErrorDetail {
            kind: "admission.control-stage".into(),
            fields: Metadata::from([("stage".into(), stage.name().into())]),
        });
    }
    failure
}

#[cfg(test)]
mod tests {
    use super::{annotate, Stage};
    use latent_core::{ErrorDetail, Metadata, PlatformError, PlatformErrorCode};

    #[test]
    fn closed_stage_preserves_failure_identity_and_never_copies_private_payload() {
        let original = PlatformError {
            code: PlatformErrorCode::Unavailable,
            message: "private engine payload is retained only in its original field".into(),
            retryable: true,
            details: vec![ErrorDetail {
                kind: "admission.currentness".into(),
                fields: Metadata::from([(
                    "reason".into(),
                    "admission-clock-lease-uncovered".into(),
                )]),
            }],
        };
        let message_owner = original.message.as_ptr();
        let existing = original.details.clone();
        let reported = annotate(true, Stage::PackageRead, original);
        assert_eq!(reported.code, PlatformErrorCode::Unavailable);
        assert!(reported.retryable);
        assert_eq!(reported.message.as_ptr(), message_owner);
        assert_eq!(&reported.details[..existing.len()], existing.as_slice());
        assert_eq!(
            reported.details[1].fields,
            Metadata::from([("stage".into(), "package-read".into())])
        );
        let outer = annotate(true, Stage::InheritedBindings, reported);
        assert_eq!(outer.details.len(), 2);
        assert_eq!(outer.details[1].fields["stage"], "package-read");

        for (control, code, reason) in [
            (
                false,
                PlatformErrorCode::Unavailable,
                "admission-clock-lease-uncovered",
            ),
            (
                true,
                PlatformErrorCode::PermissionDenied,
                "admission-clock-lease-uncovered",
            ),
            (
                true,
                PlatformErrorCode::Unavailable,
                "admission-authority-busy",
            ),
        ] {
            let unclassified = PlatformError {
                code,
                message: "private unclassified payload".into(),
                retryable: false,
                details: vec![ErrorDetail {
                    kind: "admission.currentness".into(),
                    fields: Metadata::from([("reason".into(), reason.into())]),
                }],
            };
            let expected = unclassified.clone();
            assert_eq!(
                annotate(control, Stage::PrepareLease, unclassified),
                expected
            );
        }
    }
}
