//! Reusable, small conformance adapters over caller-owned runtime services.
//!
//! These adapters exercise the supplied implementation. They neither create a
//! second activation ledger nor certify the full Phase 1 performance gate.

mod backend;
mod node;
mod probe;
mod suite;
#[cfg(test)]
mod tests;

pub use backend::BorrowedBackendHarness;
pub use node::{NodeHarness, ScopedNodeHarness};
pub use probe::{IdleScalingMeasurement, ObservedInvariantProbe};
pub use suite::{ExpectedOutcome, InvocationCase, InvocationConformanceSuite};

use latent_core::{PlatformError, PlatformErrorCode};

fn error(code: PlatformErrorCode, message: &'static str) -> PlatformError {
    PlatformError {
        code,
        message: message.to_owned(),
        retryable: false,
        details: Vec::new(),
    }
}

fn work_limit() -> PlatformError {
    error(
        PlatformErrorCode::ResourceExhausted,
        "conformance-work-limit",
    )
}
