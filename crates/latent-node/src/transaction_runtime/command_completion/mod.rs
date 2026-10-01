//! Command completion over the original host, claim and protected store owners.
//!
//! Durable disposition is separate from delivery. Public constructors cannot
//! assert a commit, rejection or abort using a caller-supplied receipt.

use latent_activation::ActivationOutcome;
mod admission;
mod delivery;
mod driver;
mod errors;
mod lookup;
mod native;
mod output;
mod retry;
pub use admission::{
    CommandAdmission, CommandAdmissionFactory, CommandAdmissionSelection, CommandCoordinator,
};
pub use delivery::ResultDeliveryFence;
pub use output::{CanonicalCommandResult, CommandOutput, CommandResultCodec};
pub use retry::CommandRetry;

use latent_commit::atomic::{CommandRecord, DurableResult, Outcome};
use latent_core::{HostMemoryReservation, PlatformError};
use std::sync::Arc;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum CommandObservation {
    Terminal,
    InProgress,
    RecoveryRequired,
}

/// A closed observation created by the command owner after actual publication
/// or an authorized durable lookup. It is never an execution/commit permit.
#[derive(Clone)]
pub struct TransactionDisposition {
    record: CommandRecord,
    observation: CommandObservation,
    read_authorized: bool,
    _memory: Option<Arc<HostMemoryReservation>>,
}
impl TransactionDisposition {
    #[must_use]
    pub fn original_command(&self) -> &CommandRecord {
        &self.record
    }

    #[must_use]
    pub fn durable_command(&self) -> Option<&CommandRecord> {
        (self.observation == CommandObservation::Terminal).then_some(&self.record)
    }

    #[must_use]
    pub fn requires_recovery(&self) -> bool {
        self.observation == CommandObservation::RecoveryRequired
    }
    #[must_use]
    pub const fn observation(&self) -> CommandObservation {
        self.observation
    }
    /// Reports authorization at observation time. Consumers must additionally
    /// use the completion's current delivery fence when releasing data.
    #[must_use]
    pub const fn read_authorized(&self) -> bool {
        self.read_authorized
    }
}
impl std::fmt::Debug for TransactionDisposition {
    fn fmt(&self, out: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        out.debug_struct("TransactionDisposition")
            .field("record", &self.record)
            .field("observation", &self.observation)
            .field("read_authorized", &self.read_authorized)
            .finish_non_exhaustive()
    }
}
impl PartialEq for TransactionDisposition {
    fn eq(&self, other: &Self) -> bool {
        self.record == other.record
            && self.observation == other.observation
            && self.read_authorized == other.read_authorized
    }
}
impl Eq for TransactionDisposition {}

#[derive(Debug)]
pub struct TransactionCompletion {
    outcome: ActivationOutcome,
    disposition: Option<TransactionDisposition>,
    delivery_failure: Option<PlatformError>,
    delivery_fence: Option<Arc<ResultDeliveryFence>>,
}
impl TransactionCompletion {
    /// Ordinary/query completion creates no durable command observation.
    #[must_use]
    pub fn ordinary(outcome: ActivationOutcome) -> Self {
        Self {
            outcome,
            disposition: None,
            delivery_failure: None,
            delivery_fence: None,
        }
    }

    /// Query completion with an actual retained read authority. Creating an
    /// ordinary completion alone never authorizes response data.
    #[must_use]
    pub fn ordinary_authorized(outcome: ActivationOutcome, fence: ResultDeliveryFence) -> Self {
        let mut completion = Self::ordinary(outcome);
        completion.delivery_fence = Some(Arc::new(fence));
        completion
    }

    #[must_use]
    pub fn delivery_fence(&self) -> Option<&ResultDeliveryFence> {
        self.delivery_fence.as_deref()
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
        self.delivery_failure = failure.or(self.delivery_failure);
        self
    }

    pub(crate) fn into_parts(
        self,
    ) -> (
        ActivationOutcome,
        Option<TransactionDisposition>,
        Option<PlatformError>,
        Option<Arc<ResultDeliveryFence>>,
    ) {
        (
            self.outcome,
            self.disposition,
            self.delivery_failure,
            self.delivery_fence,
        )
    }

    fn observed(
        outcome: ActivationOutcome,
        record: CommandRecord,
        observation: CommandObservation,
        read_authorized: bool,
        memory: Option<Arc<HostMemoryReservation>>,
    ) -> Self {
        Self {
            outcome,
            disposition: Some(TransactionDisposition {
                record,
                observation,
                read_authorized,
                _memory: memory,
            }),
            delivery_failure: None,
            delivery_fence: None,
        }
    }

    fn confirmed(
        outcome: ActivationOutcome,
        record: CommandRecord,
        result: &DurableResult,
        read_authorized: bool,
        memory: Option<Arc<HostMemoryReservation>>,
    ) -> Result<Self, PlatformError> {
        result.verify(&record).map_err(errors::atomic)?;
        if record.outcome() == Outcome::Pending || record.committed_version().is_none() {
            return Err(errors::atomic(latent_commit::atomic::AtomicError::Corrupt));
        }
        Ok(Self::observed(
            outcome,
            record,
            CommandObservation::Terminal,
            read_authorized,
            memory,
        ))
    }
}
