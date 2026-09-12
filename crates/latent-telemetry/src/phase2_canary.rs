//! Control-registered canary cohorts with affine, nonblocking activation capture.
mod capture;
mod model;
mod outcome;
mod snapshot;
mod window;

pub use capture::{CanaryCapture, CanaryCaptureAttempt, CanarySample, SelectedOutcomeRevision};
pub use model::{
    CanaryCoverage, CanaryRevisionBinding, CanaryWindowIdentity, CanaryWindowSpec,
    Phase2CanaryOutcomeWindowConfig, Phase2CanaryWindowSnapshot, CANARY_LATENCY_UPPER_MICROS,
};
pub use outcome::{Phase2CanaryOutcomeClass, Phase2CanaryOutcomeCounters};
pub use snapshot::{CanaryRevisionSnapshot, CanaryWindowSnapshot};
pub use window::{BoundedPhase2CanaryOutcomeWindow, CanaryWindow};

fn error(
    code: latent_core::PlatformErrorCode,
    message: &'static str,
) -> latent_core::PlatformError {
    latent_core::PlatformError {
        code,
        message: message.to_owned(),
        retryable: false,
        details: Vec::new(),
    }
}

#[cfg(test)]
mod tests;
