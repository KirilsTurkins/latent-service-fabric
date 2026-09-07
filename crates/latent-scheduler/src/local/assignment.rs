use std::sync::Arc;
use std::time::Instant;

use latent_admission::{AdmissionPermit, ExecutionPermit};
use latent_core::{ActivationId, PlatformError, PlatformErrorCode};

use super::state::Inner;
use super::{error, now, CellClass, SchedulingCancellation};
use crate::CellLease;

/// One execution-owned cell and its admission reservation. Fields are private
/// so quota ownership cannot be detached before cell cleanup. Dropping without
/// an explicit disposition conservatively quarantines the cell first.
///
/// ```compile_fail
/// fn duplicate(assignment: latent_scheduler::ScheduledActivation) {
///     let _second = assignment.clone();
/// }
/// ```
#[must_use = "release after proven cleanup, or quarantine the execution cell"]
pub struct ScheduledActivation {
    lease: Option<CellLease>,
    permit: Option<ExecutionPermit>,
    cancellation: Arc<dyn SchedulingCancellation>,
    registration: ActiveRegistration,
}

impl ScheduledActivation {
    pub fn lease(&self) -> &CellLease {
        self.lease.as_ref().expect("live assignment")
    }
    pub fn permit(&self) -> &ExecutionPermit {
        self.permit.as_ref().expect("live assignment")
    }
    #[must_use]
    pub fn cancellation(&self) -> &dyn SchedulingCancellation {
        self.cancellation.as_ref()
    }

    /// Call only after the backend has affirmatively proven cleanup. The
    /// reservation stays alive through the pool's release future and its drop.
    pub async fn release(mut self) -> Result<(), PlatformError> {
        let lease = self.lease.take().expect("live assignment");
        self.registration.owner.pools[&self.registration.class]
            .release(lease)
            .await
    }

    pub async fn quarantine(mut self, reason: String) -> Result<(), PlatformError> {
        let lease = self.lease.take().expect("live assignment");
        self.registration.owner.pools[&self.registration.class]
            .quarantine(lease, reason)
            .await
    }
}

impl std::fmt::Debug for ScheduledActivation {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        formatter
            .debug_struct("ScheduledActivation")
            .field("lease", &self.lease)
            .field("permit", &self.permit)
            .finish_non_exhaustive()
    }
}

impl Drop for ScheduledActivation {
    fn drop(&mut self) {
        if self.cancellation.is_cancelled() {
            self.registration
                .owner
                .record_cancellation(&self.registration.id, self.registration.sequence);
        }
        drop(self.lease.take());
        drop(self.permit.take());
        // ActiveRegistration is then dropped, after disposition and quota refund.
    }
}

pub(super) struct PendingAssignment {
    lease: Option<CellLease>,
    permit: Option<AdmissionPermit>,
    execution: Option<ExecutionPermit>,
    cancellation: Arc<dyn SchedulingCancellation>,
    registration: Option<ActiveRegistration>,
    enqueued_at: Instant,
}

impl PendingAssignment {
    pub fn new(
        lease: CellLease,
        permit: AdmissionPermit,
        cancellation: Arc<dyn SchedulingCancellation>,
        registration: ActiveRegistration,
        enqueued_at: Instant,
    ) -> Self {
        Self {
            lease: Some(lease),
            permit: Some(permit),
            execution: None,
            cancellation,
            registration: Some(registration),
            enqueued_at,
        }
    }

    pub fn accept(mut self) -> Result<ScheduledActivation, PlatformError> {
        let registration = self.registration.as_ref().expect("pending registration");
        let fail = |code, reason| {
            let failure = error(code, reason);
            registration
                .owner
                .record_failure(&registration.id, registration.sequence, code);
            failure
        };
        if self.cancellation.is_cancelled() {
            return Err(fail(PlatformErrorCode::Cancelled, "cancelled"));
        }
        if registration.owner.lock().shutdown {
            return Err(fail(PlatformErrorCode::Unavailable, "shutdown"));
        }
        let permit = self.permit.take().expect("pending admission permit");
        match permit.try_start_execution_at(now()) {
            Ok(execution) => self.execution = Some(execution),
            Err(failure) => {
                let (permit, error) = *failure;
                self.permit = Some(permit);
                registration.owner.record_failure(
                    &registration.id,
                    registration.sequence,
                    error.code,
                );
                return Err(error);
            }
        }
        // The quota transition may contend. Recheck the original deadline and
        // cancellation immediately before exposing the assignment to execution.
        if self.cancellation.is_cancelled() {
            return Err(fail(PlatformErrorCode::Cancelled, "cancelled"));
        }
        if registration.owner.lock().shutdown {
            return Err(fail(PlatformErrorCode::Unavailable, "shutdown"));
        }
        if let Err(error) = self
            .execution
            .as_ref()
            .expect("execution transition completed")
            .admission()
            .ensure_schedulable_at(now())
        {
            registration
                .owner
                .record_failure(&registration.id, registration.sequence, error.code);
            return Err(error);
        }
        registration
            .owner
            .record_grant(registration.class, self.enqueued_at);
        Ok(ScheduledActivation {
            lease: self.lease.take(),
            permit: self.execution.take(),
            cancellation: Arc::clone(&self.cancellation),
            registration: self.registration.take().expect("pending registration"),
        })
    }
}

impl Drop for PendingAssignment {
    fn drop(&mut self) {
        if let Some(registration) = &self.registration {
            registration.owner.record_failure(
                &registration.id,
                registration.sequence,
                PlatformErrorCode::Cancelled,
            );
        }
        if let Some(mut lease) = self.lease.take() {
            lease.reclaim_unaccepted();
        }
        drop(self.permit.take());
        drop(self.execution.take());
        drop(self.registration.take());
    }
}

pub(super) struct ActiveRegistration {
    pub owner: Arc<Inner>,
    id: ActivationId,
    pub class: CellClass,
    sequence: u64,
}

impl ActiveRegistration {
    pub fn new(owner: Arc<Inner>, id: ActivationId, class: CellClass, sequence: u64) -> Self {
        Self {
            owner,
            id,
            class,
            sequence,
        }
    }
}

impl Drop for ActiveRegistration {
    fn drop(&mut self) {
        self.owner.finish_active(&self.id, self.sequence);
    }
}
