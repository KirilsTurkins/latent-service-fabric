//! An affine staged-root transition into a new, still-paused physical owner.
//! Paths, matching receipts and elapsed time cannot construct this transition.

use super::{
    custody::ProtectedCustodyJob, restore_stage::RestoreStageReceipt, snapshot::SnapshotFile,
    ProtectedRestoreDestinationConfig, ProtectedSnapshot, ProtectedStoreError, ProtectedStoreOwner,
    ProtectedStoreStartup,
};
use crate::{
    embedded::{ReadView, StoreError},
    store_io::{StoreIoError, StoreIoRetirementWitness},
};
use latent_core::{
    native_capacity::{NativeBufferPermit, NativeReservation},
    ActivationClock,
};
use std::{
    cell::Cell,
    future::Future,
    pin::Pin,
    sync::Arc,
    task::{Context, Poll},
};

mod prepare;
mod startup;

/// This small extra response charge holds both bounded configured root names,
/// physical identity descriptions and original adoption metadata. The decoded
/// snapshot/window keeps its SAME separate prepaid 8 MiB response owner.
pub const RESTORE_ADOPTION_RESPONSE_BYTES: u64 = 128 * 1024;
const PLAN_RESPONSE_BYTES: u64 = RESTORE_ADOPTION_RESPONSE_BYTES;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(super) struct RestoredRootFence {
    pub(super) root: (u64, u64),
    pub(super) file: (u64, u64),
    pub(super) lock: (u64, u64),
}

/// Original reviewed identities only; no caller path, ready flag or permission.
pub struct RestoreAdoptionRequest {
    pub operator_id: String,
    pub operation_digest: [u8; 32],
    pub checkpoint_digest: [u8; 32],
    pub loss_window_acknowledgement: [u8; 32],
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum RestoreAdoptionKind {
    Prepare,
    PublishPaused,
}

/// The installed current owner must consume this SAME original native fence
/// within its current role/audit/publication/clock metadata fences. It renews no
/// deadline, grant, command, effect identity, provider status or Fresh witness.
pub struct RestoreAdoptionFence<'a> {
    original: &'a NativeReservation,
    consumed: &'a Cell<bool>,
    request: &'a RestoreAdoptionRequest,
    kind: RestoreAdoptionKind,
}
impl RestoreAdoptionFence<'_> {
    #[must_use]
    pub const fn request(&self) -> &RestoreAdoptionRequest {
        self.request
    }

    #[must_use]
    pub const fn kind(&self) -> RestoreAdoptionKind {
        self.kind
    }

    pub fn accept(self) -> Result<(), StoreError> {
        if self.consumed.get() {
            return Err(StoreError::Invalid);
        }
        self.original
            .with_live(|| self.consumed.set(true))
            .map_err(|_| StoreError::SnapshotExpired)
    }
}

/// Current installed complete-store review and separate live authority owners.
/// Review bounds decoding and validates linked formats/artifacts/payloads,
/// fresh local attempt/boot fences and present result access in the same view.
/// No callback defaults to approved or performs provider work. `accept` is a
/// short no-I/O fence; readiness remains paused for explicit reconciliation.
pub trait RestoreAdoptionOwners: Send + Sync + 'static {
    fn review(
        &self,
        view: &ReadView,
        stage: &RestoreStageReceipt,
        request: &RestoreAdoptionRequest,
    ) -> Result<(), StoreError>;
    fn current_role(&self) -> Result<(), StoreError>;
    fn current_audit(&self) -> Result<(), StoreError>;
    fn current_publication(&self) -> Result<(), StoreError>;
    fn current_clock(&self) -> Result<(), StoreError>;
    fn accept(&self, original: RestoreAdoptionFence<'_>) -> Result<(), StoreError>;
}

/// Closed physical-source association. Neither this value nor its descriptive
/// digests can resume restored business work. The original source must be
/// closed/drained and the actual snapshot/staged native resource must retire
/// before initialization can open the same destination objects.
pub struct RestoreAdoptionPlan {
    config: ProtectedRestoreDestinationConfig,
    store_fence: RestoredRootFence,
    checkpoint_fence: RestoredRootFence,
    stage: RestoreStageReceipt,
    request: RestoreAdoptionRequest,
    owners: Arc<dyn RestoreAdoptionOwners>,
    source: ProtectedStoreOwner,
    retired: StoreIoRetirementWitness,
    _buffer: NativeBufferPermit,
}

impl RestoreAdoptionPlan {
    #[must_use]
    pub const fn request(&self) -> &RestoreAdoptionRequest {
        &self.request
    }

    #[must_use]
    pub const fn staged_receipt(&self) -> &RestoreStageReceipt {
        &self.stage
    }

    /// Observe the associated physical owners, never caller-supplied status.
    pub fn check_retired(&self) -> Result<(), ProtectedStoreError> {
        current(self).map_err(ProtectedStoreError::Store)?;
        if !self.retired.has_retired() || !self.source.snapshot()?.physically_retired() {
            return Err(ProtectedStoreError::Store(StoreError::Unavailable));
        }
        Ok(())
    }

    /// Preserve this SAME plan on a healthy pre-admission refusal. Once native
    /// initialization is accepted, the returned startup owns its execution and
    /// destruction even when its observer disappears.
    pub fn start(
        self,
        clock: Arc<dyn ActivationClock>,
    ) -> Result<ProtectedStoreStartup, RestoreAdoptionStartError> {
        startup::start(self, clock)
    }
}

pub struct RestoreAdoptionStartError {
    pub reason: ProtectedStoreError,
    pub plan: Option<RestoreAdoptionPlan>,
}

impl std::fmt::Debug for RestoreAdoptionStartError {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        formatter
            .debug_struct("RestoreAdoptionStartError")
            .field("reason", &self.reason)
            .field("original_plan_retained", &self.plan.is_some())
            .finish()
    }
}

#[must_use = "accepted staged review and resource custody survive waiter loss"]
pub struct ProtectedRestoreAdoptionJob {
    inner: ProtectedCustodyJob<Option<SnapshotFile>, Result<RestoreAdoptionPlan, StoreError>>,
}

impl Future for ProtectedRestoreAdoptionJob {
    type Output = Result<
        (
            ProtectedSnapshot,
            Result<Result<RestoreAdoptionPlan, StoreError>, ProtectedStoreError>,
        ),
        StoreIoError,
    >;

    fn poll(self: Pin<&mut Self>, context: &mut Context<'_>) -> Poll<Self::Output> {
        match Pin::new(&mut self.get_mut().inner).poll(context) {
            Poll::Ready(Ok((custody, result))) => {
                Poll::Ready(Ok((ProtectedSnapshot { custody }, result)))
            }
            Poll::Ready(Err(error)) => Poll::Ready(Err(error)),
            Poll::Pending => Poll::Pending,
        }
    }
}

fn current(plan: &RestoreAdoptionPlan) -> Result<(), StoreError> {
    plan.stage.check().map_err(|error| match error {
        super::RestoreStageError::Review(error) | super::RestoreStageError::Checkpoint(error) => {
            error
        }
        super::RestoreStageError::Destination(_) => StoreError::Unavailable,
    })?;
    let owners = plan.owners.as_ref();
    owners.current_role()?;
    owners.current_audit()?;
    owners.current_publication()?;
    owners.current_clock()
}

fn accept(plan: &RestoreAdoptionPlan, kind: RestoreAdoptionKind) -> Result<(), StoreError> {
    current(plan)?;
    let consumed = Cell::new(false);
    let original = plan.stage.input.original();
    plan.owners.accept(RestoreAdoptionFence {
        original: &original,
        consumed: &consumed,
        request: &plan.request,
        kind,
    })?;
    if !consumed.get() {
        return Err(StoreError::Invalid);
    }
    current(plan)
}
