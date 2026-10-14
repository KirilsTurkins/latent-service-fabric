//! A native claim binds cancellation to its original manager registration.
mod abort;
use super::{authorization, StateTransactionHost};
pub use abort::CommandCancellationAuthority;
pub(crate) use abort::{
    with_request_authority, CancellationAbortPermit, CancellationAbortSlot,
    PendingCancellationAbort,
};
use latent_commit::atomic::{AdmittedCommand, CommandRecord, Outcome};
use latent_core::{ActivationBudget, ActivationId, PlatformError, TenantId};
use latent_state::protected_store::ProtectedStoreOwner;
use std::sync::{Arc, Weak};
pub(crate) const CANCELLATION_RECORD_BYTES: usize = 2048;

/// An accepted request is not a durable command disposition.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum OriginalCommandCancelDisposition {
    Requested,
    RecoveryRequired,
}

/// An opaque association minted only from a real admitted claim and its host.
/// It grants no permission and retains no guest, Store, result or physical job.
pub struct OriginalCommandCancellation {
    activation: ActivationId,
    budget: ActivationBudget,
    identity: Arc<CommandCancellationIdentity>,
    abort_slot: Weak<CancellationAbortSlot>,
}

#[cfg_attr(test, derive(Clone))]
pub(crate) struct CommandCancellationIdentity {
    pub(crate) tenant: TenantId,
    command: String,
    attempt: u64,
    transaction: String,
    publication: String,
    fingerprint: [u8; 32],
    store: Weak<ProtectedStoreOwner>,
}

impl OriginalCommandCancellation {
    #[cfg(test)]
    pub(crate) fn without_abort_slot_for_test(mut self) -> Self {
        self.abort_slot = Weak::new();
        self
    }
    pub(super) fn from_claim(
        claim: &AdmittedCommand,
        host: &StateTransactionHost,
    ) -> Result<Self, PlatformError> {
        let record = claim.record();
        let command = host.command.as_ref().ok_or_else(authorization::denied)?;
        if record.outcome() != Outcome::Pending
            || host.scope.mode != latent_state::session::StateMode::Command
            || host.scope.tenant.0 != record.key().tenant
            || host.scope.namespace.0 != record.key().namespace
            || host.scope.incarnation.to_string() != record.key().incarnation
            || host.scope.state_schema != record.source().state_schema
            || host.scope.entity != record.key().entity
            || command.view.namespace != record.key().namespace
            || command.view.incarnation != record.key().incarnation
            || command.view.state_schema != record.source().state_schema
            || command.command_id != record.id().hex()
            || command.attempt_id != record.attempt().to_string()
            || host.authorization.publication() != record.source().publication
            || host.acquired.load(std::sync::atomic::Ordering::Acquire) != 0
            || host.guest_closed.load(std::sync::atomic::Ordering::Acquire)
            || host.released.load(std::sync::atomic::Ordering::Acquire)
        {
            return Err(authorization::denied());
        }
        Ok(Self {
            activation: host.activation.clone(),
            budget: host.authorization.budget.clone(),
            identity: Arc::new(CommandCancellationIdentity {
                tenant: TenantId(record.key().tenant.clone()),
                command: record.id().hex(),
                attempt: record.attempt(),
                transaction: record.transaction_id().hex(),
                publication: record.source().publication.clone(),
                fingerprint: record.fingerprint().bytes(),
                store: Arc::downgrade(&host.store),
            }),
            abort_slot: Weak::new(),
        })
    }

    pub(crate) fn matches_activation(&self, id: &ActivationId, budget: &ActivationBudget) -> bool {
        &self.activation == id && self.budget.is_same_instance(budget)
    }

    pub(crate) fn with_abort_slot(
        mut self,
        slot: &Arc<CancellationAbortSlot>,
        identity: Arc<CommandCancellationIdentity>,
    ) -> Self {
        self.abort_slot = Arc::downgrade(slot);
        self.identity = identity;
        self
    }

    pub(crate) fn identity(&self) -> Arc<CommandCancellationIdentity> {
        self.identity.clone()
    }
    pub(crate) fn activation_retained_bytes(&self) -> usize {
        self.abort_slot.upgrade().map_or(0, |slot| {
            slot.retained_scope_bytes() + abort::prepaid_bytes()
        })
    }

    pub(crate) fn into_identity(
        self,
    ) -> (
        Arc<CommandCancellationIdentity>,
        Weak<CancellationAbortSlot>,
    ) {
        (self.identity, self.abort_slot)
    }
}

impl CommandCancellationIdentity {
    pub(crate) fn retained_bytes(&self) -> Option<usize> {
        [
            self.tenant.0.capacity(),
            self.command.capacity(),
            self.transaction.capacity(),
            self.publication.capacity(),
        ]
        .into_iter()
        .try_fold(
            std::mem::size_of::<Self>() + 2 * std::mem::size_of::<usize>(),
            usize::checked_add,
        )
    }

    pub(crate) fn matches_record(
        &self,
        record: &CommandRecord,
        store: &ProtectedStoreOwner,
    ) -> bool {
        record.outcome() == Outcome::Pending
            && self.matches_identity(record)
            && self
                .store
                .upgrade()
                .is_some_and(|original| original.is_same_owner(store))
    }

    pub(crate) fn same_identity(&self, other: &Self) -> bool {
        self.tenant == other.tenant
            && self.command == other.command
            && self.attempt == other.attempt
            && self.transaction == other.transaction
            && self.publication == other.publication
            && self.fingerprint == other.fingerprint
            && Weak::ptr_eq(&self.store, &other.store)
    }

    pub(crate) fn matches_identity(&self, record: &CommandRecord) -> bool {
        self.tenant.0 == record.key().tenant
            && self.command == record.id().hex()
            && self.attempt == record.attempt()
            && self.transaction == record.transaction_id().hex()
            && self.publication == record.source().publication
            && self.fingerprint == record.fingerprint().bytes()
    }
}
