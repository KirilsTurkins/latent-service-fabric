//! Closed source-level call boundaries, never an inference inside the engine call.
use latent_core::PlatformError;
use latent_executor::GuestOutcome;

#[derive(Clone, Copy)]
pub(super) enum CallPhase {
    Instantiate,
    ExportLookup,
    CallAndPostReturn,
}

impl CallPhase {
    fn wire_name(self) -> &'static str {
        match self {
            Self::Instantiate => "instantiate",
            Self::ExportLookup => "export-lookup",
            // The safe dynamic call includes argument lowering, guest execution,
            // result lifting and canonical post-return. Do not subdivide it here.
            Self::CallAndPostReturn => "call-and-postreturn",
        }
    }

    pub(super) fn annotate(self, outcome: &mut Result<GuestOutcome, PlatformError>) {
        let Ok(GuestOutcome::Trapped { trap, .. }) = outcome else {
            return;
        };
        if trap.code == "guest-runtime-error"
            && trap.metadata.get("classification").map(String::as_str) == Some("runtime-error")
        {
            trap.metadata
                .insert("runtimePhase".into(), self.wire_name().into());
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use latent_core::{BudgetConsumption, Metadata};
    use latent_executor::GuestTrap;

    fn outcome(code: &str, classification: &str) -> Result<GuestOutcome, PlatformError> {
        Ok(GuestOutcome::Trapped {
            trap: GuestTrap {
                code: code.into(),
                message: "original private diagnostic".into(),
                guest_backtrace: Vec::new(),
                metadata: Metadata::from([("classification".into(), classification.into())]),
                diagnostic: None,
            },
            consumption: BudgetConsumption {
                cpu_fuel: 71,
                peak_memory_bytes: 1024,
                ..Default::default()
            },
        })
    }

    #[test]
    fn only_generic_runtime_failure_gets_the_actual_closed_call_boundary() {
        for (phase, expected) in [
            (CallPhase::Instantiate, "instantiate"),
            (CallPhase::ExportLookup, "export-lookup"),
            (CallPhase::CallAndPostReturn, "call-and-postreturn"),
        ] {
            let mut value = outcome("guest-runtime-error", "runtime-error");
            phase.annotate(&mut value);
            let Ok(GuestOutcome::Trapped { trap, consumption }) = value else {
                unreachable!()
            };
            assert_eq!(trap.code, "guest-runtime-error");
            assert_eq!(trap.message, "original private diagnostic");
            assert!(trap.guest_backtrace.is_empty());
            assert!(trap.diagnostic.is_none());
            assert_eq!(
                trap.metadata,
                Metadata::from([
                    ("classification".into(), "runtime-error".into()),
                    ("runtimePhase".into(), expected.into()),
                ])
            );
            assert_eq!(consumption.cpu_fuel, 71);
            assert_eq!(consumption.peak_memory_bytes, 1024);
        }
    }

    #[test]
    fn call_boundary_does_not_relabel_traps_accounting_or_lifecycle_failures() {
        for (code, classification) in [
            ("guest-trap", "runtime-error"),
            ("runtime-lifecycle-unproven", "runtime-error"),
            ("budget-accounting-failed", "runtime-error"),
            ("guest-runtime-error", "private-classification"),
            ("guest-runtime-error", ""),
        ] {
            let mut value = outcome(code, classification);
            CallPhase::CallAndPostReturn.annotate(&mut value);
            let Ok(GuestOutcome::Trapped { trap, consumption }) = value else {
                unreachable!()
            };
            assert_eq!(trap.code, code);
            assert_eq!(trap.message, "original private diagnostic");
            assert_eq!(
                trap.metadata,
                Metadata::from([("classification".into(), classification.into())])
            );
            assert_eq!(consumption.cpu_fuel, 71);
        }
    }
}
