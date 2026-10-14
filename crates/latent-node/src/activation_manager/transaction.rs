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
    /// Only native admission can mint this opaque original-claim association.
    /// Default and query paths bind no command cancellation target.
    fn original_command_cancellation(
        &self,
    ) -> Result<Option<crate::transaction_runtime::OriginalCommandCancellation>, PlatformError>
    {
        Ok(None)
    }

    /// HTTP commands need the actual prepared component codec before claiming
    /// a durable identity. Other trusted callers retain their existing input path.
    fn requires_prepared_input(&self) -> bool {
        false
    }

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

/// Original fixed signals only; no budget, manager, registration or guest is
/// retained by metadata recovery. A late transport stop remains a refusal.
pub(crate) struct OriginalCancellationMetadataFence {
    transport: Arc<super::transport_stop::TransportStop>,
    cancellation: crate::cancellation::CancellationMetadataProbe,
    clock: Arc<dyn ActivationClock>,
    deadline: std::time::Instant,
}
impl OriginalCancellationMetadataFence {
    pub(crate) fn is_current(&self) -> bool {
        self.clock.monotonic_now() < self.deadline
            && self.transport.cause().is_none()
            && self.cancellation.is_current()
    }
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
        self.is_current_at(self.clock.monotonic_now())
    }

    /// Sample the original covered clock before entering an owner fence.
    pub(crate) fn observe_current(&self) -> Option<std::time::Instant> {
        let observed = self.clock.monotonic_now();
        self.is_current_at(observed).then_some(observed)
    }

    /// Recheck the original signals without consulting a clock under a fence.
    /// A caller reusing an observation must also fence the original finite
    /// deadline with the actual role/native owner; this cannot renew it.
    pub(crate) fn is_current_at(&self, observed: std::time::Instant) -> bool {
        !self.budget.retained_authority_is_cancelled_at(observed)
            && self.transport.cause().is_none()
    }

    pub(crate) fn accepted_original_cancellation(&self) -> bool {
        self.transport.cause().is_none()
            && !self
                .budget
                .deadline()
                .is_expired_at(self.clock.monotonic_now())
            && self.cancellation.accepted_cancellation()
    }

    pub(crate) fn cancelled_metadata_fence(&self) -> Option<OriginalCancellationMetadataFence> {
        let deadline = self.budget.deadline().monotonic()?;
        self.accepted_original_cancellation()
            .then(|| OriginalCancellationMetadataFence {
                transport: self.transport.clone(),
                cancellation: self.cancellation.metadata_probe(),
                clock: self.clock.clone(),
                deadline,
            })
    }
    pub(crate) fn matches_cancellation_owner(
        &self,
        owner: &crate::cancellation::WeakCancellationOwner,
    ) -> bool {
        owner.matches_handle(&self.cancellation)
    }

    #[cfg(all(test, unix))]
    pub(crate) fn stop_transport_for_native_test(&self) {
        self.transport
            .mark(super::transport_stop::ActivationTransportInterruption::Disconnected);
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

    #[cfg(all(test, unix))]
    pub(crate) fn with_native_test_clock(mut self, clock: Arc<dyn ActivationClock>) -> Self {
        self.clock = clock;
        self
    }
}
