//! Activation-scoped native state sessions over the existing protected owner.
mod authorization;
mod host;
mod initialization;
mod io;
pub use authorization::{PolicyCallBinding, StateAuthorization};

use latent_commit::atomic::{
    AdmittedCommand, CapturedIntent, CommandTime, IntentCaptureContext, PhysicalAttemptWork,
};
use latent_core::{ActivationId, HostMemoryReservation};
use latent_effects::authority::EffectAuthorityOwner;
use latent_executor::transaction::{CommandInfo, Mode, StateFailure};
use latent_state::{
    protected_store::{ProtectedStoreOperation, ProtectedStoreOwner, ProtectedStoreView},
    session::{StatePlan, StateScope, StateSession},
    store_io::StoreIoRetirementWitness,
};
use std::sync::{
    atomic::{AtomicBool, AtomicU8},
    Arc, Mutex,
};

/// Continuity is supplied by the protected node time/restore owner. Local wall
/// time alone cannot assert continuity after an older restore or process loss.
pub trait CommandTimeSource: Send + Sync {
    fn sample(&self) -> CommandTime;
}

pub struct CommandHostSelection {
    context: IntentCaptureContext,
    info: CommandInfo,
    work: PhysicalAttemptWork,
    key: latent_core::transaction_contract::CommandKey,
    publication: String,
}
impl CommandHostSelection {
    pub fn from_claim(
        claim: &AdmittedCommand,
        view: latent_executor::transaction::ViewIdentity,
    ) -> Result<Self, latent_commit::atomic::AtomicError> {
        let record = claim.record();
        if view.namespace != record.key().namespace
            || view.incarnation != record.key().incarnation
            || view.state_schema != record.source().state_schema
        {
            return Err(latent_commit::atomic::AtomicError::PermissionDenied);
        }
        Ok(Self {
            context: claim.intent_capture_context(),
            key: record.key().clone(),
            publication: record.source().publication.clone(),
            info: CommandInfo {
                view,
                command_id: record.id().hex(),
                attempt_id: record.attempt().to_string(),
                entity: record.key().entity.clone(),
            },
            work: claim.physical_work()?,
        })
    }
}
struct SessionPayload {
    session: StateSession,
    intents: Vec<CapturedIntent>,
    memory: Arc<HostMemoryReservation>,
}
struct OwnedSession {
    view: ProtectedStoreView,
    payload: SessionPayload,
}
struct Physical {
    operation: ProtectedStoreOperation,
    work: Option<PhysicalAttemptWork>,
}

pub struct StateTransactionHost {
    activation: ActivationId,
    mode: Mode,
    scope: StateScope,
    authorization: Arc<StateAuthorization>,
    store: Arc<ProtectedStoreOwner>,
    session: Mutex<Option<OwnedSession>>,
    witness: StoreIoRetirementWitness,
    physical: Mutex<Option<Physical>>,
    acquired: AtomicU8,
    released: AtomicBool,
    guest_closed: AtomicBool,
    technical_fault: AtomicBool,
    context: Option<IntentCaptureContext>,
    command: Option<CommandInfo>,
    effects: Option<EffectAuthorityOwner>,
    time: Arc<dyn CommandTimeSource>,
    retained_bytes: u64,
}

/// Only host coordination receives the affine view and staged state/intent
/// owners. Carry memory through actual writer and native-view retirement.
pub struct StateHandoff {
    pub view: ProtectedStoreView,
    pub plan: StatePlan,
    pub intents: Vec<CapturedIntent>,
    pub memory: Arc<HostMemoryReservation>,
}
impl StateTransactionHost {
    #[must_use]
    pub fn authority(&self) -> &StateAuthorization {
        &self.authorization
    }

    /// Guest Store destruction must already be positively observed. A busy
    /// detached native read returns unavailable until its issued witness proves
    /// destruction; it never releases an operation pin based on elapsed time.
    pub async fn retire(&self) -> Result<(), StateFailure> {
        use std::sync::atomic::Ordering;
        if !self.guest_closed.load(Ordering::Acquire) {
            return Err(StateFailure::HandleClosed);
        }
        let owned = self
            .session
            .lock()
            .map_err(|_| StateFailure::Unavailable)?
            .take();
        if let Some(owned) = owned {
            drop(owned.payload);
            owned.view.retire().await;
        }
        if !self.witness.has_retired() {
            return Err(StateFailure::Unavailable);
        }
        let physical = self
            .physical
            .lock()
            .map_err(|_| StateFailure::Unavailable)?
            .take()
            .ok_or(StateFailure::HandleClosed)?;
        physical.operation.retire().await;
        if let Some(work) = physical.work {
            work.retire();
        }
        Ok(())
    }

    /// Seal only after actual guest references are severed. The returned native
    /// view stays owned by the command coordinator until its real destruction.
    pub async fn handoff(&self) -> Result<StateHandoff, StateFailure> {
        use std::sync::atomic::Ordering;
        if self.mode != Mode::Command
            || !self.guest_closed.load(Ordering::Acquire)
            || self.technical_fault.load(Ordering::Acquire)
        {
            return Err(StateFailure::WrongMode);
        }
        self.authorization
            .authorize("commit", 0, 0, || Ok(()))
            .map_err(|_| StateFailure::PermissionDenied)?;
        let owned = self
            .session
            .lock()
            .map_err(|_| StateFailure::Unavailable)?
            .take()
            .ok_or(StateFailure::Unavailable)?;
        let auth = Arc::clone(&self.authorization);
        let payload = owned.payload;
        let job = self
            .store
            .with_view(owned.view, self.retained_bytes, move |view| {
                let plan = payload.session.seal(view, |_, _| {
                    auth.authorize("commit", 0, 0, || Ok(()))
                        .map_err(|_| latent_state::session::StateError::PermissionDenied)
                });
                if let Err(error) = &plan {
                    if let Some(fatal) = error.storage_error() {
                        return Err(fatal);
                    }
                }
                Ok((plan, payload.intents, payload.memory))
            })
            .map_err(io::protected_error)?;
        let (view, result) = job.await.map_err(|_| StateFailure::Unavailable)?;
        let (plan, intents, memory) = match result {
            Ok(result) => result,
            Err(error) => {
                view.retire().await;
                return Err(io::protected_error(error));
            }
        };
        let plan = match plan {
            Ok(plan) => plan,
            Err(error) => {
                view.retire().await;
                return Err(io::state_error(error, false));
            }
        };
        Ok(StateHandoff {
            view,
            plan,
            intents,
            memory,
        })
    }
}
