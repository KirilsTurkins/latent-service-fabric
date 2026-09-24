use super::*;
use crate::host::capabilities::HostCapabilityFailure;
use latent_core::{error::ADMISSION_CURRENTNESS_REASONS, ErrorDetail};

struct Cancelled;
impl ExecutionCancellationProbe for Cancelled {
    fn is_cancelled(&self) -> bool {
        true
    }
    fn reason(&self) -> Option<String> {
        Some("controlled cancellation".into())
    }
}

fn currentness(reason: &str) -> PlatformError {
    let signature = reason.starts_with("signature-");
    PlatformError {
        code: if signature {
            PlatformErrorCode::StateConflict
        } else {
            PlatformErrorCode::Unavailable
        },
        message: "private original provider input".into(),
        retryable: !signature,
        details: vec![ErrorDetail {
            kind: "admission.currentness".into(),
            fields: [("reason".into(), reason.into())].into(),
        }],
    }
}

fn consumption() -> BudgetConsumption {
    BudgetConsumption {
        cpu_fuel: 123,
        peak_memory_bytes: 4096,
        wall_time_micros: 789,
        ..Default::default()
    }
}

#[test]
fn validated_currentness_keeps_the_existing_runtime_trap_and_consumption() {
    for &reason in ADMISSION_CURRENTNESS_REASONS {
        let source = currentness(reason);
        let code = format!("{:?}", source.code);
        let failure = wasmtime::Error::new(HostCapabilityFailure::from_error(&source))
            .context("private Wasmtime context");
        let outcome = classify_runtime_error(
            &failure,
            &StopControl::new(None, None),
            false,
            consumption(),
        )
        .unwrap();
        let GuestOutcome::Trapped {
            trap,
            consumption: retained,
        } = outcome
        else {
            panic!("diagnostics must not change the trapped outcome");
        };
        assert_eq!(retained, consumption());
        assert_eq!(trap.code, "guest-runtime-error");
        assert_eq!(trap.message, "guest execution failed");
        assert!(trap.guest_backtrace.is_empty());
        assert_eq!(
            trap.metadata,
            Metadata::from([
                ("classification".into(), "runtime-error".into()),
                ("capabilityFailure".into(), code),
                ("admissionCurrentnessReason".into(), reason.into()),
            ])
        );
        assert!(!format!("{trap:?}").contains("private"));
    }
}

#[test]
fn currentness_diagnostics_never_override_memory_deadline_or_untyped_errors() {
    let failure = wasmtime::Error::new(HostCapabilityFailure::from_error(&currentness(
        "admission-authority-busy",
    )));
    for (stop, memory, expected) in [
        (
            StopControl::new(None, Some(Arc::new(Cancelled))),
            false,
            GuestInterruptionKind::Cancelled,
        ),
        (
            StopControl::new(None, None),
            true,
            GuestInterruptionKind::MemoryExhausted,
        ),
        (
            StopControl::new(Some(Instant::now()), None),
            false,
            GuestInterruptionKind::DeadlineExceeded,
        ),
    ] {
        let outcome = classify_runtime_error(&failure, &stop, memory, consumption()).unwrap();
        let GuestOutcome::Interrupted {
            kind,
            consumption: retained,
            ..
        } = outcome
        else {
            panic!("stop/memory precedence must remain an interruption");
        };
        assert_eq!(kind, expected);
        assert_eq!(retained, consumption());
    }
    let untyped = wasmtime::Error::msg("admission-authority-busy private provider input");
    let mut malformed = currentness("admission-authority-busy");
    malformed.details[0]
        .fields
        .insert("private".into(), "extra field".into());
    let malformed = wasmtime::Error::new(HostCapabilityFailure::from_error(&malformed));
    for error in [&untyped, &malformed] {
        let outcome =
            classify_runtime_error(error, &StopControl::new(None, None), false, consumption())
                .unwrap();
        let GuestOutcome::Trapped {
            trap,
            consumption: retained,
        } = outcome
        else {
            panic!("untyped or malformed errors retain their existing trapped outcome");
        };
        assert_eq!(retained, consumption());
        assert_eq!(trap.code, "guest-runtime-error");
        assert!(!trap.metadata.contains_key("admissionCurrentnessReason"));
        assert!(!format!("{trap:?}").contains("private"));
    }
}
