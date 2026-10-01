//! Command completion over the original host, claim and protected store owners.
//!
//! Durable disposition is separate from delivery. Public constructors cannot
//! assert a commit, rejection or abort using a caller-supplied receipt.

use latent_activation::ActivationOutcome;
use latent_commit::atomic::CommandRecord;
use latent_core::PlatformError;

/// A closed observation created by the command owner after actual publication
/// or an authorized durable lookup. It is never an execution/commit permit.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct TransactionDisposition {
    record: CommandRecord,
    durable: bool,
}
impl TransactionDisposition {
    #[must_use]
    pub fn original_command(&self) -> &CommandRecord {
        &self.record
    }

    #[must_use]
    pub fn durable_command(&self) -> Option<&CommandRecord> {
        self.durable.then_some(&self.record)
    }

    #[must_use]
    pub const fn requires_recovery(&self) -> bool {
        !self.durable
    }
}

#[derive(Debug)]
pub struct TransactionCompletion {
    outcome: ActivationOutcome,
    disposition: Option<TransactionDisposition>,
    delivery_failure: Option<PlatformError>,
}
impl TransactionCompletion {
    /// Ordinary/query completion creates no durable command observation.
    #[must_use]
    pub fn ordinary(outcome: ActivationOutcome) -> Self {
        Self {
            outcome,
            disposition: None,
            delivery_failure: None,
        }
    }

    #[must_use]
    pub fn outcome(&self) -> &ActivationOutcome {
        &self.outcome
    }

    #[must_use]
    pub fn into_outcome(self) -> ActivationOutcome {
        self.outcome
    }

    #[must_use]
    pub fn durable_command(&self) -> Option<&CommandRecord> {
        self.disposition
            .as_ref()
            .and_then(TransactionDisposition::durable_command)
    }

    #[must_use]
    pub fn disposition(&self) -> Option<&TransactionDisposition> {
        self.disposition.as_ref()
    }

    #[must_use]
    pub fn delivery_failure(&self) -> Option<&PlatformError> {
        self.delivery_failure.as_ref()
    }

    pub(crate) fn with_delivery(
        mut self,
        outcome: ActivationOutcome,
        failure: Option<PlatformError>,
    ) -> Self {
        self.outcome = outcome;
        self.delivery_failure = failure;
        self
    }

    pub(crate) fn into_parts(
        self,
    ) -> (
        ActivationOutcome,
        Option<TransactionDisposition>,
        Option<PlatformError>,
    ) {
        (self.outcome, self.disposition, self.delivery_failure)
    }
}
