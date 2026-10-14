use super::{
    denied, expired, namespace_error, unsupported, Arc, Inner, Instant, PlatformError,
    StateManagementBinding, StateManagementReservation,
};
use latent_commit::atomic::{CommandRecord, DurableResult};
use latent_core::{transaction_contract::CommandKey, ActivationClock};
use latent_effects::runtime::CommandAdmissionSource;
use latent_policy::capability::OwnedPolicyDecision;
use latent_state::namespace::{catalog::NamespaceRead, lifecycle::NamespaceLifecycleHandle};
use std::time::Duration;

pub(super) struct ReadAuthority {
    pub binding: Arc<StateManagementBinding>,
    pub decision: OwnedPolicyDecision,
    pub key: CommandKey,
    pub deadline: Instant,
    pub command_manager: Option<latent_node::LocalActivationManager>,
    // Original installation metadata and RPC capacity retire after all values.
    pub inner: Arc<Inner>,
    pub permit: Arc<dyn StateManagementReservation>,
}
impl ReadAuthority {
    pub fn before_lookup(&self) -> Result<(), PlatformError> {
        if self.inner.services.clock.monotonic_now() >= self.deadline {
            return Err(expired());
        }
        self.inner
            .services
            .policy
            .with_retained_decision(&self.decision, &mut |_, _| {
                self.permit.with_live_until(self.deadline, &mut || {})
            })
    }
    pub fn with_namespace(
        &self,
        namespace: &NamespaceRead,
        lifecycle: &NamespaceLifecycleHandle,
        cutoff: Instant,
        publish: &mut dyn FnMut(),
    ) -> Result<(), PlatformError> {
        self.inner
            .services
            .policy
            .with_retained_decision(&self.decision, &mut |_, _| {
                let mut result = None;
                lifecycle
                    .with_current(namespace, false, || {
                        result = Some(self.permit.with_live_until(cutoff, publish));
                        Ok(())
                    })
                    .map_err(namespace_error)?;
                result.ok_or_else(denied)?
            })
    }
}

pub(super) struct ResultWindow {
    floor: u64,
    expires: u64,
}
impl ResultWindow {
    pub fn capture(record: &CommandRecord, result: Option<&DurableResult>) -> Self {
        Self {
            floor: record.clock_floor(),
            expires: if result.is_some_and(|result| result.value().is_some()) {
                record.result_expires()
            } else {
                record.identity_expires()
            },
        }
    }
    pub(super) fn cutoff(
        &self,
        source: &CommandAdmissionSource,
        clock: &dyn ActivationClock,
        original: Instant,
    ) -> Result<Instant, PlatformError> {
        let observed = clock.monotonic_now();
        let time = source.command_time().map_err(|_| unsupported())?;
        if !time.continuity_proven
            || time.unix_millis < self.floor
            || time.unix_millis >= self.expires
        {
            return Err(expired());
        }
        observed
            .checked_add(Duration::from_millis(self.expires - time.unix_millis))
            .map(|cutoff| cutoff.min(original))
            .ok_or_else(expired)
    }
}

pub(super) struct ResponseOwner {
    pub namespace: NamespaceRead,
    pub lifecycle: NamespaceLifecycleHandle,
    pub window: ResultWindow,
    pub read: Arc<ReadAuthority>,
}
impl crate::phase4::Phase4ResponseOwner for ResponseOwner {
    fn reserved_bytes(&self) -> usize {
        self.read.permit.reserved_response_bytes()
    }
    fn with_current(&self, publish: &mut dyn FnMut()) -> Result<(), PlatformError> {
        let source = self
            .read
            .inner
            .command_source
            .as_ref()
            .ok_or_else(unsupported)?;
        let cutoff = self.window.cutoff(
            source,
            self.read.inner.services.clock.as_ref(),
            self.read.deadline,
        )?;
        self.read
            .with_namespace(&self.namespace, &self.lifecycle, cutoff, publish)
    }
}
