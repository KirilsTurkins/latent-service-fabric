use super::{
    denied, ActivationCapabilityBroker, CapabilityPlanSource, CapabilitySession, PlatformError,
};
use latent_artifacts::{LifecycleAuthorityHandle, ReleaseUseEligibility};
use latent_executor::{ExecutionCancellation, ExecutionRequest};
use std::sync::{Arc, OnceLock, RwLock};

/// One configured authority plus a trusted immutable-plan source. The full
/// control-plane source is implemented by #207; no second route journal exists.
pub struct ActivationCapabilityRuntime {
    broker: Arc<ActivationCapabilityBroker>,
    plans: RwLock<Option<Arc<dyn CapabilityPlanSource>>>,
    local_services: OnceLock<Arc<dyn super::LocalServiceInvoker>>,
}
impl ActivationCapabilityRuntime {
    #[must_use]
    pub fn new(
        broker: Arc<ActivationCapabilityBroker>,
        plans: Arc<dyn CapabilityPlanSource>,
    ) -> Self {
        Self {
            broker,
            plans: RwLock::new(Some(plans)),
            local_services: OnceLock::new(),
        }
    }
    #[must_use]
    pub fn broker(&self) -> &Arc<ActivationCapabilityBroker> {
        &self.broker
    }
    /// Configure one node-owned adapter during composition. Implementations
    /// must hold only a weak manager reference to avoid backend/runtime cycles.
    pub fn install_local_services(
        &self,
        invoker: Arc<dyn super::LocalServiceInvoker>,
    ) -> Result<(), PlatformError> {
        self.local_services.set(invoker).map_err(|_| denied())
    }
    pub fn local_services(&self) -> Result<Arc<dyn super::LocalServiceInvoker>, PlatformError> {
        self.local_services.get().cloned().ok_or_else(denied)
    }
    pub fn check_catalog(&self, owner: &LifecycleAuthorityHandle) -> Result<(), PlatformError> {
        if !self.broker.catalog_owner_matches(owner) {
            return Err(denied());
        }
        Ok(())
    }
    pub fn check_policy_owner(
        &self,
        policies: &Arc<latent_policy::capability::PolicyStore>,
    ) -> Result<(), PlatformError> {
        if !self.broker.policy_owner_matches(policies) {
            return Err(denied());
        }
        Ok(())
    }
    pub fn check_clock(
        &self,
        clock: &Arc<dyn latent_core::ActivationClock>,
    ) -> Result<(), PlatformError> {
        if !self.broker.clock_owner_matches(clock) {
            return Err(denied());
        }
        Ok(())
    }
    pub fn open_session(
        &self,
        request: &ExecutionRequest,
        cancellation: &dyn ExecutionCancellation,
        publication: &ReleaseUseEligibility,
        deadline: &latent_core::EffectiveDeadline,
    ) -> Result<CapabilitySession, PlatformError> {
        let revision = request
            .activation
            .resolved_revision
            .as_ref()
            .ok_or_else(denied)?;
        let source = self
            .plans
            .try_read()
            .map_err(|_| super::busy())?
            .as_ref()
            .cloned()
            .ok_or_else(denied)?;
        let plan = source.plan(revision)?;
        self.broker.open_session(
            plan,
            request,
            &RuntimeCancellation {
                owner: cancellation,
                deadline,
            },
            publication,
        )
    }
    pub fn retire(&self) {
        self.broker.retire();
        // Drop all dormant plan/snapshot ownership outside the source lock.
        let plans = self
            .plans
            .write()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
            .take();
        drop(plans);
    }
}
impl Drop for ActivationCapabilityRuntime {
    fn drop(&mut self) {
        self.retire();
    }
}

// Borrowed original execution owner; this only narrows its effective deadline.
struct RuntimeCancellation<'a> {
    owner: &'a dyn ExecutionCancellation,
    deadline: &'a latent_core::EffectiveDeadline,
}
impl ExecutionCancellation for RuntimeCancellation<'_> {
    fn activation_id(&self) -> &latent_core::ActivationId {
        self.owner.activation_id()
    }
    fn is_cancelled(&self) -> bool {
        self.owner.is_cancelled()
    }
    fn reason(&self) -> Option<String> {
        self.owner.reason()
    }
    fn budget_accounting(&self) -> Option<&latent_core::ActivationBudget> {
        self.owner.budget_accounting()
    }
    fn probe(&self) -> Option<Arc<dyn latent_executor::ExecutionCancellationProbe>> {
        self.owner.probe()
    }
    fn effective_deadline(&self) -> Option<&latent_core::EffectiveDeadline> {
        Some(self.deadline)
    }
}
