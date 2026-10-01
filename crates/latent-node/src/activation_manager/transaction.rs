//! One explicit transaction admission within the existing activation lifecycle.
use latent_activation::{ActivationEnvelope, ActivationOutcome};
use latent_core::{
    ActivationBudget, ActivationClock, ActivationId, ActivationTerminalState, BoxFuture,
    PlatformError,
};
use latent_executor::transaction::TransactionHost;
use std::sync::Arc;

/// The trusted state runtime validates the selected companion/publication and
/// authenticated scope, reserves durable command capacity before guest work,
/// and retains the original physical owners. Implementations cannot replace
/// this activation's accepted source, budget or monotonic deadline.
pub trait TransactionActivationAdmission: Send + Sync {
    fn admit<'a>(
        &'a self,
        envelope: &'a ActivationEnvelope,
        budget: &'a ActivationBudget,
    ) -> BoxFuture<'a, Result<Arc<dyn TransactionHost>, PlatformError>>;

    /// The same handle invokes this after guest/cell cleanup and accounting
    /// observation, while its original cancellation registration is still live.
    fn complete(
        &self,
        outcome: ActivationOutcome,
        _control: TransactionCommitControl,
    ) -> BoxFuture<'_, ActivationOutcome> {
        Box::pin(async move { outcome })
    }
}

/// Opaque authority over the original activation's cancellation winner. It is
/// created only by the actual manager lifecycle; copied DTOs cannot mint it.
#[derive(Clone)]
pub struct TransactionCommitControl {
    cancellation: crate::CancellationHandle,
    transport: Arc<super::transport_stop::TransportStop>,
    clock: Arc<dyn ActivationClock>,
    budget: ActivationBudget,
}
impl TransactionCommitControl {
    pub(super) fn new(
        cancellation: crate::CancellationHandle,
        transport: Arc<super::transport_stop::TransportStop>,
        clock: Arc<dyn ActivationClock>,
        budget: ActivationBudget,
    ) -> Self {
        Self {
            cancellation,
            transport,
            clock,
            budget,
        }
    }

    pub(crate) fn matches(&self, activation: &ActivationId, budget: &ActivationBudget) -> bool {
        self.cancellation.activation_id() == activation && self.budget.is_same_instance(budget)
    }

    pub(crate) fn accept(&self, proposed: ActivationTerminalState) -> bool {
        if !self.is_current() {
            return false;
        }
        self.cancellation.accept_commit(proposed, || {
            !self
                .budget
                .deadline()
                .is_expired_at(self.clock.monotonic_now())
                && self.transport.cause().is_none()
        })
    }

    pub(crate) fn is_current(&self) -> bool {
        !self
            .budget
            .retained_authority_is_cancelled_at(self.clock.monotonic_now())
            && self.transport.cause().is_none()
    }

    #[cfg(all(test, unix))]
    pub(crate) fn for_native_test(
        registration: &crate::CancellationRegistration,
        budget: &ActivationBudget,
    ) -> Self {
        Self::new(
            registration.handle(),
            Arc::default(),
            Arc::new(latent_core::SystemActivationClock),
            budget.clone(),
        )
    }
}
