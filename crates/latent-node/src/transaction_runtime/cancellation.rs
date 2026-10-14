//! A native claim binds cancellation to its original manager registration.
use super::{authorization, StateTransactionHost};
use latent_commit::atomic::{AdmittedCommand, CommandRecord, Outcome};
use latent_core::{ActivationBudget, ActivationId, PlatformError, TenantId};
use latent_state::protected_store::ProtectedStoreOwner;
use std::sync::{Arc, Weak};

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
    identity: CommandCancellationIdentity,
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
            identity: CommandCancellationIdentity {
                tenant: TenantId(record.key().tenant.clone()),
                command: record.id().hex(),
                attempt: record.attempt(),
                transaction: record.transaction_id().hex(),
                publication: record.source().publication.clone(),
                fingerprint: record.fingerprint().bytes(),
                store: Arc::downgrade(&host.store),
            },
        })
    }

    pub(crate) fn matches_activation(&self, id: &ActivationId, budget: &ActivationBudget) -> bool {
        &self.activation == id && self.budget.is_same_instance(budget)
    }

    pub(crate) fn into_identity(self) -> CommandCancellationIdentity {
        self.identity
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
        .try_fold(0usize, usize::checked_add)
    }

    pub(crate) fn matches_record(
        &self,
        record: &CommandRecord,
        store: &ProtectedStoreOwner,
    ) -> bool {
        record.outcome() == Outcome::Pending
            && self.tenant.0 == record.key().tenant
            && self.command == record.id().hex()
            && self.attempt == record.attempt()
            && self.transaction == record.transaction_id().hex()
            && self.publication == record.source().publication
            && self.fingerprint == record.fingerprint().bytes()
            && self
                .store
                .upgrade()
                .is_some_and(|original| original.is_same_owner(store))
    }
}
