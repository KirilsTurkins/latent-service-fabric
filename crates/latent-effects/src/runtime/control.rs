//! Node-wide controls. These affine values retain this actual dispatch owner;
//! descriptive IDs and generations never constitute operator authorization.

use std::sync::Arc;

use latent_state::embedded::{FencedStoreError, StoreError};
use latent_state::protected_store::ProtectedStoreError;
use latent_state::store_io::{StoreIoJob, StoreIoKind};
use serde::{Deserialize, Serialize};

use crate::authority::EffectTime;
use crate::dispatch_store::control::{ControlCatalog, PlannedControl};

use super::state::Shared;
use super::{DispatcherOwner, EffectTimeSource};

pub use crate::dispatch_store::control::DispatcherControlReceipt;

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct DispatcherControlGeneration {
    owner_epoch: u64,
    revision: u64,
}

impl DispatcherControlGeneration {
    pub(crate) const fn initial(owner_epoch: u64) -> Self {
        Self {
            owner_epoch,
            revision: 1,
        }
    }
    pub fn new(owner_epoch: u64, revision: u64) -> Result<Self, DispatcherControlError> {
        if owner_epoch == 0 || revision == 0 {
            return Err(DispatcherControlError::Invalid);
        }
        Ok(Self {
            owner_epoch,
            revision,
        })
    }

    #[must_use]
    pub const fn owner_epoch(self) -> u64 {
        self.owner_epoch
    }
    #[must_use]
    pub const fn revision(self) -> u64 {
        self.revision
    }

    pub(crate) fn next(self) -> Result<Self, DispatcherControlError> {
        Self::new(
            self.owner_epoch,
            self.revision
                .checked_add(1)
                .ok_or(DispatcherControlError::Capacity)?,
        )
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "kebab-case")]
pub enum DispatcherControlAction {
    Pause,
    Resume,
}

/// The host supplies actor identity from authentication. This data records an
/// exact request, not a permission to inspect or control another owner's node.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct DispatcherControlRequest {
    actor_tenant: String,
    actor_subject: String,
    operation_id: String,
    expected: DispatcherControlGeneration,
    action: DispatcherControlAction,
}

impl DispatcherControlRequest {
    pub fn new(
        actor_tenant: String,
        actor_subject: String,
        operation_id: String,
        expected: DispatcherControlGeneration,
        action: DispatcherControlAction,
    ) -> Result<Self, DispatcherControlError> {
        let request = Self {
            actor_tenant,
            actor_subject,
            operation_id,
            expected,
            action,
        };
        request.validate()?;
        Ok(request)
    }
    pub(crate) fn validate(&self) -> Result<(), DispatcherControlError> {
        DispatcherControlGeneration::new(self.expected.owner_epoch, self.expected.revision)?;
        if [&self.actor_tenant, &self.actor_subject, &self.operation_id]
            .into_iter()
            .any(|value| {
                value.is_empty()
                    || value.len() > 256
                    || value.capacity() > 1024
                    || value.chars().any(char::is_control)
            })
        {
            return Err(DispatcherControlError::Invalid);
        }
        self.expected.next()?;
        Ok(())
    }
    #[must_use]
    pub fn actor_tenant(&self) -> &str {
        &self.actor_tenant
    }
    #[must_use]
    pub fn actor_subject(&self) -> &str {
        &self.actor_subject
    }
    #[must_use]
    pub fn operation_id(&self) -> &str {
        &self.operation_id
    }
    #[must_use]
    pub const fn expected(&self) -> DispatcherControlGeneration {
        self.expected
    }
    #[must_use]
    pub const fn action(&self) -> DispatcherControlAction {
        self.action
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum DispatcherControlError {
    Invalid,
    Capacity,
    Conflict,
    Closed,
    RestoreReviewRequired,
    ClockDiscontinuity,
    RecoveryRequired,
    InvalidAuthorizationFence,
    Store(StoreError),
    PhysicalOwner(ProtectedStoreError),
}

impl From<StoreError> for DispatcherControlError {
    fn from(error: StoreError) -> Self {
        Self::Store(error)
    }
}
impl From<ProtectedStoreError> for DispatcherControlError {
    fn from(error: ProtectedStoreError) -> Self {
        Self::PhysicalOwner(error)
    }
}

/// A known durable control receipt describes logical acceptance. `published`
/// never implies provider cleanup, physical retirement or a clean shutdown.
#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct DispatcherControlOutcome {
    pub receipt: DispatcherControlReceipt,
    pub replayed: bool,
    pub published: bool,
    pub paused: bool,
}

/// Preparing does no I/O and changes no admission. Only this actual owner may
/// submit the immutable request; submission transfers it to fixed store workers.
pub struct PreparedDispatcherControl {
    shared: Arc<Shared>,
    time: Arc<dyn EffectTimeSource>,
    request: DispatcherControlRequest,
    restore_review: bool,
}

pub type DispatcherControlJob = StoreIoJob<
    Result<Result<DispatcherControlOutcome, DispatcherControlError>, ProtectedStoreError>,
>;
pub type DispatcherControlLookup =
    StoreIoJob<Result<Option<DispatcherControlReceipt>, ProtectedStoreError>>;

#[derive(Debug, Clone, Copy, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct DispatcherControlSnapshot {
    pub generation: DispatcherControlGeneration,
    pub pending: bool,
    pub restore_review_required: bool,
}

#[derive(Clone, Copy)]
pub(super) enum RestoreReview {
    Clear,
    Required,
}
impl RestoreReview {
    pub const fn is_required(self) -> bool {
        matches!(self, Self::Required)
    }
}

#[derive(Clone)]
pub(super) struct PendingControl {
    pub request: DispatcherControlRequest,
    pub generation: DispatcherControlGeneration,
}

impl DispatcherOwner {
    pub fn prepare_control(
        &self,
        request: DispatcherControlRequest,
    ) -> Result<PreparedDispatcherControl, DispatcherControlError> {
        request.validate()?;
        let state = self
            .services
            .shared
            .state
            .lock()
            .map_err(|_| DispatcherControlError::RecoveryRequired)?;
        check_request(&state, &request, self.services.time.observe())?;
        Ok(PreparedDispatcherControl {
            shared: Arc::clone(&self.services.shared),
            time: Arc::clone(&self.services.time),
            request,
            restore_review: state.restore_review.is_required(),
        })
    }

    /// The authorizer holds the current trusted node-operator policy fence
    /// through exactly one call to `accept`. No I/O, guest work or async wait is
    /// permitted inside that callback. Receipt durability uses this same engine.
    /// Dropping the returned waiter never cancels an accepted physical writer.
    pub fn submit_control(
        &self,
        prepared: PreparedDispatcherControl,
        authorize: impl FnOnce(
                &mut dyn FnMut() -> Result<(), DispatcherControlError>,
            ) -> Result<(), DispatcherControlError>
            + Send
            + 'static,
    ) -> Result<DispatcherControlJob, DispatcherControlError> {
        if !Arc::ptr_eq(&prepared.shared, &self.services.shared) {
            return Err(DispatcherControlError::Conflict);
        }
        self.services
            .store
            .with_store(StoreIoKind::RecoveryWrite, 64 * 1024, move |store| {
                // Keep domain errors separate from physical failures. Store errors
                // still trigger the protected owner's actual quarantine rules.
                match execute(store, &prepared, authorize) {
                    Err(DispatcherControlError::Store(error)) => Err(error),
                    result => Ok(result),
                }
            })
            .map_err(DispatcherControlError::from)
    }

    /// Current authorization is required before lookup or release. The exact
    /// request includes its original precondition; lookup never refreshes it.
    pub fn lookup_control(
        &self,
        request: DispatcherControlRequest,
    ) -> Result<DispatcherControlLookup, DispatcherControlError> {
        request.validate()?;
        self.services
            .store
            .with_store(StoreIoKind::RecoveryRead, 32 * 1024, move |store| {
                ControlCatalog::lookup(&store.snapshot()?, &request)
            })
            .map_err(DispatcherControlError::from)
    }

    /// Restore composition sets this before exposing readiness. Generic resume
    /// cannot clear it; a later reviewed restore-specific protocol must do so.
    pub fn require_restore_review(&self) -> Result<(), DispatcherControlError> {
        let mut state = self
            .services
            .shared
            .state
            .lock()
            .map_err(|_| DispatcherControlError::RecoveryRequired)?;
        let next = state.control_generation.next()?;
        state.restore_review = RestoreReview::Required;
        state.paused = true;
        state.control_generation = next;
        drop(state);
        self.wake();
        Ok(())
    }
}

fn execute(
    store: &latent_state::embedded::EmbeddedStore,
    prepared: &PreparedDispatcherControl,
    authorize: impl FnOnce(
        &mut dyn FnMut() -> Result<(), DispatcherControlError>,
    ) -> Result<(), DispatcherControlError>,
) -> Result<DispatcherControlOutcome, DispatcherControlError> {
    let planned = ControlCatalog::plan(
        store,
        &prepared.request,
        prepared.restore_review,
        prepared.time.observe(),
    )?;
    let PlannedControl::Write { batch, receipt } = planned else {
        // A replay is historical observation; it never republishes a resume.
        let PlannedControl::Replay(receipt) = planned else {
            unreachable!()
        };
        let mut calls = 0_u8;
        authorize(&mut || {
            calls = calls
                .checked_add(1)
                .ok_or(DispatcherControlError::InvalidAuthorizationFence)?;
            if calls != 1 {
                return Err(DispatcherControlError::InvalidAuthorizationFence);
            }
            Ok(())
        })?;
        if calls != 1 {
            return Err(DispatcherControlError::InvalidAuthorizationFence);
        }
        let state = prepared
            .shared
            .state
            .lock()
            .map_err(|_| DispatcherControlError::RecoveryRequired)?;
        return Ok(DispatcherControlOutcome {
            receipt,
            replayed: true,
            published: false,
            paused: state.paused,
        });
    };
    store
        .apply_fenced(batch, || {
            let mut calls = 0_u8;
            let mut accept = || {
                calls = calls
                    .checked_add(1)
                    .ok_or(DispatcherControlError::InvalidAuthorizationFence)?;
                if calls != 1 {
                    return Err(DispatcherControlError::InvalidAuthorizationFence);
                }
                prepared.accept(&receipt)
            };
            authorize(&mut accept)?;
            if calls != 1 {
                return Err(DispatcherControlError::InvalidAuthorizationFence);
            }
            Ok(())
        })
        .map_err(|error| match error {
            FencedStoreError::Store(error) => DispatcherControlError::Store(error),
            FencedStoreError::Fence(error) => error,
        })?;
    prepared.publish(receipt)
}

impl PreparedDispatcherControl {
    fn accept(&self, receipt: &DispatcherControlReceipt) -> Result<(), DispatcherControlError> {
        let mut state = self
            .shared
            .state
            .lock()
            .map_err(|_| DispatcherControlError::RecoveryRequired)?;
        let time = self.time.observe();
        check_request(&state, &self.request, time)?;
        if self.request.action == DispatcherControlAction::Resume
            && time.unix_millis < receipt.observed_at_millis()
        {
            return Err(DispatcherControlError::ClockDiscontinuity);
        }
        if receipt.request() != &self.request
            || receipt.restore_review() != state.restore_review.is_required()
        {
            return Err(DispatcherControlError::Conflict);
        }
        state.control_generation = receipt.generation();
        state.pending_control = Some(PendingControl {
            request: self.request.clone(),
            generation: receipt.generation(),
        });
        // Both pause and resume remain paused until the actual flush succeeds.
        state.paused = true;
        drop(state);
        self.shared.notify.notify_one();
        Ok(())
    }

    fn publish(
        &self,
        receipt: DispatcherControlReceipt,
    ) -> Result<DispatcherControlOutcome, DispatcherControlError> {
        let mut state = self
            .shared
            .state
            .lock()
            .map_err(|_| DispatcherControlError::RecoveryRequired)?;
        if state.pending_control.as_ref().is_none_or(|pending| {
            pending.request != self.request || pending.generation != receipt.generation()
        }) || state.control_generation != receipt.generation()
        {
            // The writer already proved durability. A later local safety fence
            // can prevent publication; it cannot turn that receipt into abort.
            return Ok(DispatcherControlOutcome {
                receipt,
                replayed: false,
                published: false,
                paused: state.paused,
            });
        }
        let time = self.time.observe();
        let can_resume = !state.closed
            && state.failure.is_none()
            && !state.restore_review.is_required()
            && time.continuity_proven
            && time.unix_millis >= receipt.observed_at_millis();
        state.paused = self.request.action == DispatcherControlAction::Pause || !can_resume;
        state.pending_control = None;
        let paused = state.paused;
        drop(state);
        self.shared.notify.notify_one();
        Ok(DispatcherControlOutcome {
            receipt,
            replayed: false,
            published: self.request.action == DispatcherControlAction::Pause || !paused,
            paused,
        })
    }
}

fn check_request(
    state: &super::state::State,
    request: &DispatcherControlRequest,
    time: EffectTime,
) -> Result<(), DispatcherControlError> {
    if state.closed {
        return Err(DispatcherControlError::Closed);
    }
    if state.pending_control.is_some() {
        return Err(DispatcherControlError::RecoveryRequired);
    }
    if state.control_generation != request.expected {
        return Err(DispatcherControlError::Conflict);
    }
    if request.action == DispatcherControlAction::Resume {
        if state.restore_review.is_required() {
            return Err(DispatcherControlError::RestoreReviewRequired);
        }
        if state.failure.is_some() {
            return Err(DispatcherControlError::RecoveryRequired);
        }
        if !time.continuity_proven {
            return Err(DispatcherControlError::ClockDiscontinuity);
        }
    }
    Ok(())
}

#[cfg(test)]
mod tests;
