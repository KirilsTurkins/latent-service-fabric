use super::error;
use latent_core::{PlatformError, PlatformErrorCode};

#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub enum Phase2CanaryOutcomeClass {
    Success,
    DomainError,
    PlatformError,
    DeadlineExceeded,
    Cancelled,
}

impl Phase2CanaryOutcomeClass {
    #[must_use]
    pub const fn metric_label(self) -> &'static str {
        match self {
            Self::Success => "success",
            Self::DomainError => "domain_error",
            Self::PlatformError => "platform_error",
            Self::DeadlineExceeded => "deadline_exceeded",
            Self::Cancelled => "cancelled",
        }
    }
}

#[derive(Debug, Clone, Copy, Default, PartialEq, Eq)]
pub struct Phase2CanaryOutcomeCounters {
    pub success: u64,
    pub domain_error: u64,
    pub platform_error: u64,
    pub deadline_exceeded: u64,
    pub cancelled: u64,
}

impl Phase2CanaryOutcomeCounters {
    /// Arbitrary public diagnostic values saturate; bounded retained counters cannot overflow.
    #[must_use]
    pub const fn total(self) -> u64 {
        self.success
            .saturating_add(self.domain_error)
            .saturating_add(self.platform_error)
            .saturating_add(self.deadline_exceeded)
            .saturating_add(self.cancelled)
    }

    pub(super) fn record(
        &mut self,
        outcome: Phase2CanaryOutcomeClass,
    ) -> Result<(), PlatformError> {
        let counter = match outcome {
            Phase2CanaryOutcomeClass::Success => &mut self.success,
            Phase2CanaryOutcomeClass::DomainError => &mut self.domain_error,
            Phase2CanaryOutcomeClass::PlatformError => &mut self.platform_error,
            Phase2CanaryOutcomeClass::DeadlineExceeded => &mut self.deadline_exceeded,
            Phase2CanaryOutcomeClass::Cancelled => &mut self.cancelled,
        };
        *counter = counter.checked_add(1).ok_or_else(|| {
            error(
                PlatformErrorCode::ResourceExhausted,
                "phase2-canary-counter-exhausted",
            )
        })?;
        Ok(())
    }
}
