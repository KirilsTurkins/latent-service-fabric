use std::fmt;
use std::time::Instant;

use latent_core::{
    ActivationId, EffectiveActivationBudget, EffectiveDeadline, PlatformError, PlatformErrorCode,
    ResourceBudget, TenantId,
};
use latent_routing::revision_policy::{ExecutionBackendKind, StateModel, ThreadingModel};
use latent_routing::ResolvedRevision;

use crate::quota::ReservationSpec;
use crate::{rejection, LocalQuotaProvider};

/// Immutable scheduler/executor obligations derived from trusted policy.
///
/// Schedule only in these classes, enforce every granted budget dimension and
/// the original monotonic deadline, and retain the affine permit through backend
/// cleanup. Do not interpret caller metadata as a replacement for these values.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct AdmissionObligations {
    pub cell_class: String,
    pub queue_class: String,
    pub trust_class: String,
    pub priority: u8,
    pub backend: ExecutionBackendKind,
    pub threading: ThreadingModel,
    pub state_model: StateModel,
    pub required_features: Vec<String>,
    pub host_call_depth_maximum: u32,
    pub component_call_depth_maximum: u32,
}

/// One queued reservation. It cannot be cloned or constructed by a caller.
/// Dropping it handles enqueue failure, cancellation, expiry, and abandoned futures.
///
/// ```compile_fail
/// fn duplicate(permit: latent_admission::AdmissionPermit) {
///     let _second = permit.clone();
/// }
/// ```
#[must_use = "retain the admission permit through scheduling and execution cleanup"]
pub struct AdmissionPermit {
    activation_id: ActivationId,
    revision: ResolvedRevision,
    grant: EffectiveActivationBudget,
    obligations: AdmissionObligations,
    quotas: LocalQuotaProvider,
    reserved: bool,
}

/// The same reservation after the scheduler has assigned a cell. Queue capacity
/// has been returned, but concurrency, CPU, memory, and trust capacity remain
/// reserved until this value is dropped after execution and cell disposition.
#[must_use = "retain the execution permit until the cell is released or quarantined"]
pub struct ExecutionPermit {
    admission: AdmissionPermit,
}

impl AdmissionPermit {
    pub(crate) fn reserve(
        quotas: LocalQuotaProvider,
        activation_id: ActivationId,
        mut revision: ResolvedRevision,
        grant: EffectiveActivationBudget,
        obligations: AdmissionObligations,
        timing: crate::timing::ReservationTiming,
    ) -> Result<Self, PlatformError> {
        // Caller-supplied metadata is not propagated as execution policy.
        revision.attributes.clear();
        let mut permit = Self {
            activation_id,
            revision,
            grant,
            obligations,
            quotas,
            reserved: false,
        };
        permit.quotas.reserve(ReservationSpec {
            activation_id: &permit.activation_id,
            tenant: &permit.revision.target.tenant,
            trust_class: &permit.obligations.trust_class,
            queue_class: &permit.obligations.queue_class,
            cell_class: &permit.obligations.cell_class,
            grant: &permit.grant,
            timing,
        })?;
        permit.reserved = true;
        Ok(permit)
    }

    #[must_use]
    pub fn activation_id(&self) -> &ActivationId {
        &self.activation_id
    }

    #[must_use]
    pub fn tenant(&self) -> &TenantId {
        &self.revision.target.tenant
    }

    #[must_use]
    pub fn revision(&self) -> &ResolvedRevision {
        &self.revision
    }

    #[must_use]
    pub fn granted_budget(&self) -> &ResourceBudget {
        &self.grant.budget
    }

    /// Pass this exact grant to activation accounting. Never recompute a new
    /// relative deadline when the request leaves the queue.
    #[must_use]
    pub fn effective_budget(&self) -> &EffectiveActivationBudget {
        &self.grant
    }

    #[must_use]
    pub fn deadline(&self) -> &EffectiveDeadline {
        &self.grant.deadline
    }

    #[must_use]
    pub fn obligations(&self) -> &AdmissionObligations {
        &self.obligations
    }

    /// Check immediately before allocating/handing off an execution cell.
    pub fn ensure_schedulable_at(&self, now: Instant) -> Result<(), PlatformError> {
        if self.grant.deadline.is_expired_at(now) {
            Err(rejection(
                PlatformErrorCode::DeadlineExceeded,
                "request",
                "deadline",
                "deadline-exceeded",
            ))
        } else {
            Ok(())
        }
    }

    /// Consume only after the scheduler has assigned a cell and before invoking
    /// the guest. On error this permit is dropped; the scheduler must also drop
    /// or quarantine its independently owned cell lease. A second dequeue is
    /// prevented by ownership rather than an idempotent counter decrement.
    pub fn start_execution_at(self, now: Instant) -> Result<ExecutionPermit, PlatformError> {
        self.ensure_schedulable_at(now)?;
        self.quotas.start(&self.activation_id)?;
        Ok(ExecutionPermit { admission: self })
    }

    pub fn start_execution(self) -> Result<ExecutionPermit, PlatformError> {
        self.start_execution_at(Instant::now())
    }
}

impl ExecutionPermit {
    pub fn admission(&self) -> &AdmissionPermit {
        &self.admission
    }
}

impl fmt::Debug for AdmissionPermit {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("AdmissionPermit")
            .field("obligations", &self.obligations)
            .field("reserved", &self.reserved)
            .finish_non_exhaustive()
    }
}

impl fmt::Debug for ExecutionPermit {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_tuple("ExecutionPermit")
            .field(&self.admission)
            .finish()
    }
}

impl Drop for AdmissionPermit {
    fn drop(&mut self) {
        if self.reserved {
            self.quotas.release(&self.activation_id);
        }
    }
}
