//! One explicit transaction admission within the existing activation lifecycle.
use latent_activation::{ActivationEnvelope, ActivationOutcome};
use latent_core::{ActivationBudget, BoxFuture, PlatformError};
use latent_executor::transaction::{Mode, TransactionHost};
use std::sync::Arc;

pub use crate::transaction_runtime::command_completion::{
    TransactionCompletion, TransactionDisposition,
};

/// The node supplies this control from its original registration and budget,
/// before command admission can publish a durable claim. No caller can mint it.
pub struct TransactionAdmissionControl {
    cancellation: crate::CancellationHandle,
    budget: ActivationBudget,
}
impl TransactionAdmissionControl {
    pub(super) fn new(cancellation: crate::CancellationHandle, budget: ActivationBudget) -> Self {
        Self {
            cancellation,
            budget,
        }
    }

    pub fn bind_command(
        &self,
        authorization: &crate::transaction_runtime::StateAuthorization,
    ) -> Result<(), PlatformError> {
        if authorization.authority_mode() != latent_capabilities::namespace::Mode::Command
            || authorization.activation_id() != self.cancellation.activation_id()
            || !authorization.budget().is_same_instance(&self.budget)
        {
            return Err(super::control::error(
                latent_core::PlatformErrorCode::PermissionDenied,
                "transaction admission control owner mismatch",
            ));
        }
        self.cancellation
            .bind_commit_gate(authorization.cancellation())
    }
}

/// An existing command completes from current authorized durable state. It
/// never supplies another execution host or schedules another application call.
pub enum TransactionAdmission {
    Execute(TransactionExecution),
    Existing(TransactionCompletion),
}

/// Host completion is called only after the backend's actual teardown (or a
/// positively never-started path). It owns any remaining native retirement.
pub trait TransactionCompletionHook: Send + Sync {
    fn complete<'a>(&'a self, outcome: ActivationOutcome) -> BoxFuture<'a, TransactionCompletion>;
}

pub struct TransactionExecution {
    pub(crate) host: Arc<dyn TransactionHost>,
    pub(crate) completion: Arc<dyn TransactionCompletionHook>,
    pub(crate) cancellation: Option<latent_capabilities::namespace::CommitCancellation>,
}
impl TransactionExecution {
    pub fn query(
        host: Arc<dyn TransactionHost>,
        completion: Arc<dyn TransactionCompletionHook>,
    ) -> Result<Self, PlatformError> {
        if host.mode() != Mode::Query {
            return Err(super::control::error(
                latent_core::PlatformErrorCode::PermissionDenied,
                "query completion requires query host",
            ));
        }
        Ok(Self {
            host,
            completion,
            cancellation: None,
        })
    }
}

/// The trusted state runtime validates the selected companion/publication and
/// authenticated scope, reserves durable command capacity before guest work,
/// and retains the original physical owners. Implementations cannot replace
/// this activation's accepted source, budget or monotonic deadline.
pub trait TransactionActivationAdmission: Send + Sync {
    /// Queries need no command gate. Command implementations retain the actual
    /// control and bind their original sealed gate before publishing a claim.
    fn bind_control(&self, _control: TransactionAdmissionControl) -> Result<(), PlatformError> {
        Ok(())
    }

    fn admit<'a>(
        &'a self,
        envelope: &'a ActivationEnvelope,
        budget: &'a ActivationBudget,
    ) -> BoxFuture<'a, Result<TransactionAdmission, PlatformError>>;
}
