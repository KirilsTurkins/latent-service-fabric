//! Forward only the existing closed currentness vocabulary from host traps.
//! This observation never changes the outer failure, retryability or authority.

use latent_core::{error::ADMISSION_CURRENTNESS_REASONS, ErrorDetail, Metadata};
use latent_executor::GuestTrap;

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
    use latent_core::{ActivationTerminalState, BudgetConsumption, PlatformErrorCode};
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
            assert_eq!(error.details.len(), 2);
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
            assert_eq!(mapped(trap_code, metadata).details.len(), 1);
        }
        assert_eq!(
            mapped("guest-runtime-error", Metadata::new()).details.len(),
            1
        );
    }
}
