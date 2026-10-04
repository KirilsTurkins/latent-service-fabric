//! Forward only closed host-failure and currentness vocabulary from host traps.
//! This observation never changes the outer failure, retryability or authority.

use latent_core::{error::ADMISSION_CURRENTNESS_REASONS, ErrorDetail, Metadata, PlatformErrorCode};
use latent_executor::GuestTrap;

pub(super) fn host_failure_detail(trap: &GuestTrap) -> Option<ErrorDetail> {
    if trap.code != "guest-runtime-error" {
        return None;
    }
    // This private metadata is emitted from a typed HostCapabilityFailure. Map
    // its exact closed enum spelling to stable wire vocabulary; never forward
    // arbitrary strings from an engine/backend, provider or guest exception.
    let code = match trap.metadata.get("capabilityFailure")?.as_str() {
        "Unavailable" => PlatformErrorCode::Unavailable,
        "DeadlineExceeded" => PlatformErrorCode::DeadlineExceeded,
        "Cancelled" => PlatformErrorCode::Cancelled,
        "ResourceExhausted" => PlatformErrorCode::ResourceExhausted,
        "PermissionDenied" => PlatformErrorCode::PermissionDenied,
        "Unauthenticated" => PlatformErrorCode::Unauthenticated,
        "InvalidArgument" => PlatformErrorCode::InvalidArgument,
        "NotFound" => PlatformErrorCode::NotFound,
        "AlreadyExists" => PlatformErrorCode::AlreadyExists,
        "IncompatibleContract" => PlatformErrorCode::IncompatibleContract,
        "StateConflict" => PlatformErrorCode::StateConflict,
        "DependencyFailed" => PlatformErrorCode::DependencyFailed,
        "GuestTrap" => PlatformErrorCode::GuestTrap,
        "CorruptArtifact" => PlatformErrorCode::CorruptArtifact,
        "RouteUnavailable" => PlatformErrorCode::RouteUnavailable,
        "AdmissionRejected" => PlatformErrorCode::AdmissionRejected,
        "Internal" => PlatformErrorCode::Internal,
        _ => return None,
    };
    Some(ErrorDetail {
        kind: "activation.guest-host-failure".into(),
        fields: Metadata::from([("code".into(), code.wire_code().into())]),
    })
}

pub(super) fn currentness_detail(trap: &GuestTrap) -> Option<ErrorDetail> {
    if trap.code != "guest-runtime-error" {
        return None;
    }
    let observed = trap.metadata.get("admissionCurrentnessReason")?;
    let reason = ADMISSION_CURRENTNESS_REASONS
        .iter()
        .copied()
        .find(|candidate| *candidate == observed)?;
    let expected_code = match reason {
        "signature-clock-regression" | "signature-trust-conflict" | "signature-stale-proof" => {
            "StateConflict"
        }
        _ => "Unavailable",
    };
    if trap.metadata.get("capabilityFailure").map(String::as_str) != Some(expected_code) {
        return None;
    }
    // Copy the selected static token, never arbitrary backend metadata, error
    // context, guest backtraces, policy content or provider locations.
    Some(ErrorDetail {
        kind: "admission.currentness".into(),
        fields: Metadata::from([("reason".into(), reason.into())]),
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use latent_activation::ActivationOutcome;
    use latent_core::{ActivationTerminalState, BudgetConsumption};
    use latent_executor::GuestOutcome;

    fn mapped(trap_code: &str, metadata: Metadata) -> latent_core::PlatformError {
        let consumption = BudgetConsumption {
            cpu_fuel: 17,
            peak_memory_bytes: 23,
            wall_time_micros: 29,
            ..BudgetConsumption::default()
        };
        let outcome = super::super::map_execution_outcome(
            Ok(GuestOutcome::Trapped {
                trap: GuestTrap {
                    code: trap_code.into(),
                    message: "guest execution failed".into(),
                    guest_backtrace: vec!["private-backtrace".into()],
                    metadata,
                },
                consumption: consumption.clone(),
            }),
            "cell-test",
            "released",
        );
        let ActivationOutcome::Failed {
            terminal_state,
            error,
            consumption: actual,
        } = outcome
        else {
            panic!("a diagnostic must not change the terminal failure");
        };
        assert_eq!(terminal_state, ActivationTerminalState::GuestTrap);
        assert_eq!(error.code, PlatformErrorCode::GuestTrap);
        assert!(!error.retryable);
        assert_eq!(actual, consumption);
        assert_eq!(error.message, "guest execution failed");
        assert_eq!(error.details[0].kind, "activation.guest-trap");
        assert_eq!(error.details[0].fields["code"], trap_code);
        assert_eq!(error.details[0].fields["cell_id"], "cell-test");
        assert!(!format!("{error:?}").contains("private"));
        error
    }

    #[test]
    fn currentness_detail_keeps_guest_trap_terminal_semantics() {
        for reason in ADMISSION_CURRENTNESS_REASONS {
            let code = if reason.starts_with("signature-") {
                "StateConflict"
            } else {
                "Unavailable"
            };
            let metadata = Metadata::from([
                ("capabilityFailure".into(), code.into()),
                ("admissionCurrentnessReason".into(), (*reason).into()),
                ("guest-value".into(), "private-input".into()),
            ]);
            let error = mapped("guest-runtime-error", metadata);
            assert_eq!(error.details.len(), 3);
            assert_eq!(error.details[1].kind, "admission.currentness");
            assert_eq!(
                error.details[1].fields,
                Metadata::from([("reason".into(), (*reason).into())])
            );
        }
    }

    #[test]
    fn unknown_or_mismatched_trap_metadata_stays_unclassified() {
        for (trap_code, host_code, reason) in [
            ("guest-trap", "Unavailable", "admission-authority-busy"),
            (
                "guest-runtime-error",
                "Internal",
                "admission-authority-busy",
            ),
            (
                "guest-runtime-error",
                "StateConflict",
                "admission-authority-busy",
            ),
            (
                "guest-runtime-error",
                "Unavailable",
                "signature-stale-proof",
            ),
            (
                "guest-runtime-error",
                "Unavailable",
                "unknown-private-reason",
            ),
            (
                "guest-runtime-error",
                "Unavailable",
                "admission-authority-busy-private",
            ),
            (
                "guest-runtime-error",
                "private-code",
                "admission-authority-busy",
            ),
            ("guest-runtime-error", "", "admission-authority-busy"),
            ("guest-runtime-error", "Unavailable", ""),
        ] {
            let metadata = Metadata::from([
                ("capabilityFailure".into(), host_code.into()),
                ("admissionCurrentnessReason".into(), reason.into()),
            ]);
            let error = mapped(trap_code, metadata);
            assert!(!error
                .details
                .iter()
                .any(|detail| detail.kind == "admission.currentness"));
            assert!(error.details.iter().all(|detail| matches!(
                detail.kind.as_str(),
                "activation.guest-trap" | "activation.guest-host-failure"
            )));
        }
        assert_eq!(
            mapped("guest-runtime-error", Metadata::new()).details.len(),
            1
        );
    }

    #[test]
    fn host_failure_codes_keep_terminal_semantics_without_private_metadata() {
        for code in [
            PlatformErrorCode::Unavailable,
            PlatformErrorCode::DeadlineExceeded,
            PlatformErrorCode::Cancelled,
            PlatformErrorCode::ResourceExhausted,
            PlatformErrorCode::PermissionDenied,
            PlatformErrorCode::Unauthenticated,
            PlatformErrorCode::InvalidArgument,
            PlatformErrorCode::NotFound,
            PlatformErrorCode::AlreadyExists,
            PlatformErrorCode::IncompatibleContract,
            PlatformErrorCode::StateConflict,
            PlatformErrorCode::DependencyFailed,
            PlatformErrorCode::GuestTrap,
            PlatformErrorCode::CorruptArtifact,
            PlatformErrorCode::RouteUnavailable,
            PlatformErrorCode::AdmissionRejected,
            PlatformErrorCode::Internal,
        ] {
            let metadata = Metadata::from([
                ("capabilityFailure".into(), format!("{code:?}")),
                ("classification".into(), "private-engine-class".into()),
                ("trap".into(), "private-value".into()),
                ("provider".into(), "private-token".into()),
                ("admissionCurrentnessReason".into(), "private-reason".into()),
            ]);
            let error = mapped("guest-runtime-error", metadata);
            assert_eq!(error.details.len(), 2);
            assert_eq!(error.details[1].kind, "activation.guest-host-failure");
            assert_eq!(
                error.details[1].fields,
                Metadata::from([("code".into(), code.wire_code().into())])
            );
        }
    }

    #[test]
    fn host_failure_metadata_requires_exact_known_code_and_runtime_trap() {
        for trap_code in [
            "guest-trap",
            "guest-runtime-error-unknown",
            "unrecognized",
            "",
        ] {
            let metadata = Metadata::from([("capabilityFailure".into(), "Unavailable".into())]);
            assert_eq!(mapped(trap_code, metadata).details.len(), 1);
        }
        for value in [
            "unavailable",
            "Unavailable ",
            " Unavailable",
            "Unavailable\n",
            "Unavailable/private",
            "private",
            "",
        ] {
            let metadata = Metadata::from([("capabilityFailure".into(), value.into())]);
            assert_eq!(mapped("guest-runtime-error", metadata).details.len(), 1);
        }
        for metadata in [
            Metadata::from([("capabilityFailure".into(), "private".repeat(1024))]),
            Metadata::from([("capabilityFailure/private".into(), "Unavailable".into())]),
        ] {
            assert_eq!(mapped("guest-runtime-error", metadata).details.len(), 1);
        }
    }
}
