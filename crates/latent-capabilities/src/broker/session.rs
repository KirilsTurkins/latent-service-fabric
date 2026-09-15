use super::{
    busy, capacity, checked_text, denied, stopped, token, ActivationCapabilityBroker, Charge,
    CompiledCapabilityPlan, Inner, Kind, PlatformError,
};
use latent_artifacts::ReleaseUseEligibility;
use latent_core::{ActivationBudget, ActivationId, InvocationPrincipal, Metadata, PrincipalKind};
use latent_executor::{ExecutionCancellation, ExecutionCancellationProbe, ExecutionRequest};
use latent_policy::capability::{
    CallRestrictions, CapabilityCeiling, EvaluationInput, ResourceRequest, ResourceTarget,
    SealedPolicyDecision,
};
use std::sync::{
    atomic::{AtomicBool, AtomicU64, AtomicUsize, Ordering},
    Arc, Mutex, Weak,
};

/// Wire lookup data. Knowing or constructing this value grants no authority.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub struct GuestCapabilityHandle {
    slot: u16,
    incarnation: u64,
}
impl GuestCapabilityHandle {
    #[must_use]
    pub const fn from_wire(slot: u16, incarnation: u64) -> Self {
        Self { slot, incarnation }
    }
    #[must_use]
    pub const fn wire_parts(self) -> (u16, u64) {
        (self.slot, self.incarnation)
    }
}
pub(super) struct Stats {
    pub tenant: latent_core::TenantId,
    pub closed: AtomicBool,
    pub handles: AtomicUsize,
    pub calls: AtomicUsize,
    pub waiting: AtomicUsize,
    pub results: AtomicUsize,
    pub buffer_bytes: AtomicUsize,
    _metadata: Charge,
}
#[derive(Default, Clone)]
pub(super) struct RegistryEntry {
    pub core: Weak<SessionCore>,
    pub stats: Weak<Stats>,
}
impl RegistryEntry {
    fn reusable(&self) -> bool {
        self.core.strong_count() == 0
            && self.stats.upgrade().is_none_or(|stats| {
                stats.handles.load(Ordering::Acquire) == 0
                    && stats.calls.load(Ordering::Acquire) == 0
                    && stats.results.load(Ordering::Acquire) == 0
                    && stats.waiting.load(Ordering::Acquire) == 0
                    && stats.buffer_bytes.load(Ordering::Acquire) == 0
            })
    }
}
struct HandleLifetime {
    stats: Arc<Stats>,
    counted: AtomicBool,
}
impl Drop for HandleLifetime {
    fn drop(&mut self) {
        if self.counted.load(Ordering::Acquire) {
            self.stats.handles.fetch_sub(1, Ordering::AcqRel);
        }
    }
}
pub(super) struct HandleEntry {
    pub id: GuestCapabilityHandle,
    pub binding: usize,
    pub operation: String,
    pub resource: ResourceRequest,
    _metadata: Charge,
    _slot: Charge,
    lifetime: HandleLifetime,
}
pub(super) struct SessionState {
    pub slots: Vec<Option<Arc<HandleEntry>>>,
}
pub(super) struct SessionCore {
    pub owner: Arc<Inner>,
    pub plan: Arc<CompiledCapabilityPlan>,
    pub activation_id: ActivationId,
    pub root_activation_id: ActivationId,
    pub parent_activation_id: Option<ActivationId>,
    pub principal: InvocationPrincipal,
    pub budget: ActivationBudget,
    pub deadline: latent_core::EffectiveDeadline,
    pub probe: Arc<dyn ExecutionCancellationProbe>,
    pub stats: Arc<Stats>,
    pub state: Mutex<SessionState>,
    pub random_bytes: AtomicUsize,
    pub metrics: Mutex<super::metrics::SessionUsage>,
    _metadata: Charge,
    _slot: Charge,
}
/// Affine activation lifetime. It is never retained by a prepared component.
pub struct CapabilitySession {
    pub(super) core: Arc<SessionCore>,
    // Only the original Store owner closes the scope. A short internal view
    // borrows an already-owned operation; it cannot reopen or prolong authority.
    close_on_drop: bool,
}
/// Store-owned resource-table backing storage, independent of provider permits.
/// It counts as a retained host handle until actual table destruction.
pub struct SessionResourceTableReservation {
    core: Arc<SessionCore>,
    _metadata: Charge,
    _slot: Charge,
}
impl SessionResourceTableReservation {
    /// Re-enter only the original sealed session. Every new provider operation
    /// still requires current admission and a guarded policy/audit dispatch.
    pub fn with_session<T>(&self, inspect: impl FnOnce(&CapabilitySession) -> T) -> T {
        CapabilitySession::with_work_scope(Arc::clone(&self.core), inspect)
    }
}

impl Drop for SessionResourceTableReservation {
    fn drop(&mut self) {
        self.core.stats.handles.fetch_sub(1, Ordering::AcqRel);
    }
}
/// Compact tenant-scoped accounting only; no plan, provider or guest Store.
#[derive(Clone)]
pub struct CapabilitySessionObserver {
    stats: Arc<Stats>,
}
impl CapabilitySessionObserver {
    #[must_use]
    pub fn reserved_buffer_bytes(&self) -> usize {
        self.stats.buffer_bytes.load(Ordering::Acquire)
    }
    #[must_use]
    pub fn is_closed(&self) -> bool {
        self.stats.closed.load(Ordering::Acquire)
    }
    #[must_use]
    pub fn live_calls(&self) -> usize {
        self.stats.calls.load(Ordering::Acquire) + self.stats.waiting.load(Ordering::Acquire)
    }
    #[must_use]
    pub fn retained_results(&self) -> usize {
        self.stats.results.load(Ordering::Acquire)
    }
    #[must_use]
    pub fn retained_handles(&self) -> usize {
        self.stats.handles.load(Ordering::Acquire)
    }
    #[must_use]
    pub fn is_quiescent(&self) -> bool {
        self.is_closed()
            && self.live_calls() == 0
            && self.retained_results() == 0
            && self.retained_handles() == 0
            && self.reserved_buffer_bytes() == 0
    }
    /// The embedder calls this after destroying the guest future and Store.
    /// Queue owners, blocking jobs, streams and lowering/consumer leases all
    /// prevent reuse; a timeout response or finalized ledger is insufficient.
    #[must_use]
    pub fn after_store_dropped(
        &self,
        outcome: Result<latent_executor::GuestOutcome, PlatformError>,
    ) -> latent_executor::ExecutionReport {
        if self.is_quiescent() {
            latent_executor::ExecutionReport::reusable(outcome)
        } else {
            latent_executor::ExecutionReport::quarantine(
                outcome,
                "capability work or lowering ownership remains",
            )
        }
    }
}
fn check_envelope(
    plan: &CompiledCapabilityPlan,
    request: &ExecutionRequest,
    cancellation: &dyn ExecutionCancellation,
    publication: &ReleaseUseEligibility,
    budget: &ActivationBudget,
    deadline: &latent_core::EffectiveDeadline,
) -> Result<(), PlatformError> {
    let revision = request
        .activation
        .resolved_revision
        .as_ref()
        .ok_or_else(denied)?;
    let actor = &request.activation.principal;
    if !plan.target.matches(revision)
        || revision.target != request.activation.target
        || request.prepared.key.publication.as_ref() != Some(publication.publication())
        || &request.prepared.key.release != publication.release()
        || actor.tenant.as_ref() != Some(&plan.target.tenant)
        || actor.kind == PrincipalKind::Anonymous
        || !token(&actor.subject)
        || actor.service.as_ref().is_some_and(|s| !token(&s.0))
        || !token(&request.activation.activation_id.0)
        || cancellation.activation_id() != &request.activation.activation_id
        || budget
            .deadline()
            .monotonic()
            .is_some_and(|limit| deadline.monotonic().is_none_or(|actual| actual > limit))
        || request
            .activation
            .deadline_unix_millis
            .is_some_and(|limit| deadline.unix_millis().is_none_or(|actual| actual > limit))
        || budget.granted() != &request.budget
        || request.activation.budget != request.budget
        || request.imports.len() != plan.bindings.len()
        || !plan.bindings.iter().all(|b| {
            request
                .imports
                .iter()
                .filter(|i| {
                    i.contract == b.provider.capability && i.capability.0 == b.provider.capability
                })
                .count()
                == 1
        })
    {
        return Err(denied());
    }
    Ok(())
}
impl ActivationCapabilityBroker {
    pub fn open_session(
        &self,
        plan: Arc<CompiledCapabilityPlan>,
        request: &ExecutionRequest,
        cancellation: &dyn ExecutionCancellation,
        publication: &ReleaseUseEligibility,
    ) -> Result<CapabilitySession, PlatformError> {
        let live = self.inner.live.try_read().map_err(|_| busy())?;
        if !*live || !Arc::ptr_eq(&plan.owner, &self.inner) || &plan.publication != publication {
            return Err(denied());
        }
        let actor = &request.activation.principal;
        let budget = cancellation.budget_accounting().ok_or_else(denied)?;
        let probe = cancellation.probe().ok_or_else(denied)?;
        let deadline = cancellation.effective_deadline().ok_or_else(denied)?;
        check_envelope(&plan, request, cancellation, publication, budget, deadline)?;
        plan.check_current()?;
        if cancellation.is_cancelled() || probe.is_cancelled() || budget.finalized().is_some() {
            return Err(stopped());
        }
        budget
            .check_deadline_at(self.inner.clock.monotonic_now())
            .map_err(|e| e.to_platform_error())?;
        let mut sessions = self.inner.sessions.try_lock().map_err(|_| busy())?;
        if sessions
            .iter()
            .filter_map(|entry| entry.core.upgrade())
            .any(|s| s.budget.is_same_instance(budget))
        {
            return Err(denied());
        }
        let index = sessions
            .iter()
            .position(RegistryEntry::reusable)
            .ok_or_else(capacity)?;
        let slot = self.inner.counters.acquire(Kind::Session, 1)?;
        let metadata = self.inner.counters.acquire(
            Kind::Metadata,
            4096 + size_of::<super::metrics::SessionUsage>()
                + self.inner.limits.maximum_handles_per_session
                    * std::mem::size_of::<Option<Arc<HandleEntry>>>(),
        )?;
        let stats_metadata = self.inner.counters.acquire(Kind::Metadata, 512)?;
        let stats = Arc::new(Stats {
            tenant: plan.target.tenant.clone(),
            closed: AtomicBool::new(false),
            handles: AtomicUsize::new(0),
            calls: AtomicUsize::new(0),
            waiting: AtomicUsize::new(0),
            results: AtomicUsize::new(0),
            buffer_bytes: AtomicUsize::new(0),
            _metadata: stats_metadata,
        });
        let core = Arc::new(SessionCore {
            owner: Arc::clone(&self.inner),
            plan,
            activation_id: ActivationId(checked_text(&request.activation.activation_id.0)?),
            root_activation_id: ActivationId(checked_text(
                &request.activation.root_activation_id.0,
            )?),
            parent_activation_id: request
                .activation
                .parent_activation_id
                .as_ref()
                .map(|id| checked_text(&id.0).map(ActivationId))
                .transpose()?,
            principal: InvocationPrincipal {
                subject: checked_text(&actor.subject)?,
                kind: actor.kind,
                tenant: actor.tenant.clone(),
                service: actor.service.clone(),
                claims: Metadata::new(),
            },
            budget: budget.clone(),
            deadline: deadline.clone(),
            probe,
            stats,
            random_bytes: AtomicUsize::new(0),
            metrics: Mutex::new(super::metrics::SessionUsage::default()),
            state: Mutex::new(SessionState {
                slots: (0..self.inner.limits.maximum_handles_per_session)
                    .map(|_| None)
                    .collect(),
            }),
            _metadata: metadata,
            _slot: slot,
        });
        core.check()?;
        sessions[index] = RegistryEntry {
            core: Arc::downgrade(&core),
            stats: Arc::downgrade(&core.stats),
        };
        Ok(CapabilitySession {
            core,
            close_on_drop: true,
        })
    }
}
impl SessionCore {
    pub(super) fn check(&self) -> Result<(), PlatformError> {
        if self.stats.closed.load(Ordering::Acquire)
            || self.probe.is_cancelled()
            || self.budget.finalized().is_some()
        {
            return Err(stopped());
        }
        if self
            .deadline
            .is_expired_at(self.owner.clock.monotonic_now())
        {
            return Err(super::error(
                latent_core::PlatformErrorCode::DeadlineExceeded,
                "capability-session-deadline",
            ));
        }
        Ok(())
    }
    pub(super) fn decision<'a>(
        &'a self,
        binding: usize,
        operation: &'a str,
        resource: ResourceTarget<'a>,
        input_bytes: u64,
        output_bytes: u64,
    ) -> Result<SealedPolicyDecision<'a>, PlatformError> {
        self.decision_with_streaming(
            binding,
            operation,
            resource,
            (input_bytes, output_bytes),
            false,
        )
    }
    pub(super) fn decision_with_streaming<'a>(
        &'a self,
        binding: usize,
        operation: &'a str,
        resource: ResourceTarget<'a>,
        dimensions: (u64, u64),
        streaming: bool,
    ) -> Result<SealedPolicyDecision<'a>, PlatformError> {
        let (input_bytes, output_bytes) = dimensions;
        self.check()?;
        let binding = &self.plan.bindings[binding];
        let remaining_time = self
            .deadline
            .remaining_at(self.owner.clock.monotonic_now())
            .map_or(300_000, |d| {
                u64::try_from(d.as_nanos().div_ceil(1_000_000))
                    .unwrap_or(300_000)
                    .min(300_000)
            });
        binding.policies.authorize(
            EvaluationInput {
                principal: &self.principal,
                service: &self.plan.target.service.0,
                publication: self.plan.target.publication.as_str(),
                capability: &binding.provider.capability,
                operation,
                resource,
            },
            &CallRestrictions {
                imported_operations: &binding.operations,
                deployment: &binding.deployment,
                provider_configuration: &binding.provider.restriction,
                provider_profile: &binding.provider.profile,
                configuration_digest: &binding.provider.digest,
                configuration_epoch: binding.provider.epoch,
                remaining: CapabilityCeiling {
                    operations: 1,
                    input_bytes: self.owner.limits.maximum_input_bytes as u64
                        + if streaming {
                            self.owner.limits.maximum_stream_input_bytes
                        } else {
                            0
                        },
                    output_bytes: self.owner.limits.maximum_output_bytes as u64
                        + if streaming {
                            self.owner.limits.maximum_stream_output_bytes
                        } else {
                            0
                        },
                    wall_time_millis: remaining_time,
                },
                input_bytes,
                output_bytes,
            },
            &self.plan.publication,
        )
    }
}
impl CapabilitySession {
    pub fn reserve_resource_table(
        &self,
        bytes: usize,
    ) -> Result<SessionResourceTableReservation, PlatformError> {
        if bytes == 0 || bytes > 65536 {
            return Err(capacity());
        }
        let _state = self.core.state.try_lock().map_err(|_| busy())?;
        self.core.check()?;
        if self.core.stats.handles.load(Ordering::Acquire)
            >= self.core.owner.limits.maximum_handles_per_session
        {
            return Err(capacity());
        }
        let slot = self.core.owner.counters.acquire(Kind::Handle, 1)?;
        let metadata = self.core.owner.counters.acquire(Kind::Metadata, bytes)?;
        self.core.stats.handles.fetch_add(1, Ordering::AcqRel);
        Ok(SessionResourceTableReservation {
            core: Arc::clone(&self.core),
            _metadata: metadata,
            _slot: slot,
        })
    }

    pub(super) fn with_work_scope<T>(
        core: Arc<SessionCore>,
        inspect: impl FnOnce(&Self) -> T,
    ) -> T {
        inspect(&Self {
            core,
            close_on_drop: false,
        })
    }
    /// Trusted adapter selection only; the later broker dispatch still checks
    /// every grant and currentness fence. No public descriptor grants authority.
    pub fn uses_provider(
        &self,
        provider: &super::ProviderReference,
    ) -> Result<bool, PlatformError> {
        self.core.check()?;
        Ok(self
            .core
            .plan
            .bindings
            .iter()
            .any(|binding| Arc::ptr_eq(&binding.provider, &provider.entry)))
    }
    pub fn deadline(&self) -> Result<std::time::Instant, PlatformError> {
        self.core.check()?;
        self.core.deadline.monotonic().ok_or_else(denied)
    }
    /// Check cancellation, closure and an optional deadline. This does not
    /// authorize a provider call or refresh its pinned grants.
    pub fn check_liveness(&self) -> Result<(), PlatformError> {
        self.core.check()
    }

    #[must_use]
    pub fn captures_audit(&self) -> bool {
        self.core.owner.audit.is_some()
    }
    #[must_use]
    pub fn observer(&self) -> CapabilitySessionObserver {
        CapabilitySessionObserver {
            stats: Arc::clone(&self.core.stats),
        }
    }
    pub fn bind(
        &self,
        capability: &str,
        operation: &str,
        resource: ResourceTarget<'_>,
    ) -> Result<GuestCapabilityHandle, PlatformError> {
        let result = self.bind_inner(capability, operation, resource);
        super::audit::observe_grant(&self.core, capability, operation, resource, &result);
        result
    }
    fn bind_inner(
        &self,
        capability: &str,
        operation: &str,
        resource: ResourceTarget<'_>,
    ) -> Result<GuestCapabilityHandle, PlatformError> {
        let live = self.core.owner.live.try_read().map_err(|_| busy())?;
        if !*live {
            return Err(denied());
        }
        let index = self
            .core
            .plan
            .bindings
            .iter()
            .position(|b| b.provider.capability == capability)
            .ok_or_else(denied)?;
        let binding = &self.core.plan.bindings[index];
        let installed = binding.provider.live.try_read().map_err(|_| busy())?;
        if !*installed {
            return Err(denied());
        }
        let mut state = self.core.state.try_lock().map_err(|_| busy())?;
        self.core.check()?;
        if self.core.stats.handles.load(Ordering::Acquire)
            >= self.core.owner.limits.maximum_handles_per_session
        {
            return Err(capacity());
        }
        let slot = state
            .slots
            .iter()
            .position(Option::is_none)
            .ok_or_else(capacity)?;
        let charge = self.core.owner.counters.acquire(Kind::Handle, 1)?;
        let metadata = self.core.owner.counters.acquire(Kind::Metadata, 8192)?;
        let decision = self.core.decision(index, operation, resource, 0, 0)?;
        let id = GuestCapabilityHandle {
            slot: u16::try_from(slot).map_err(|_| capacity())?,
            incarnation: next_incarnation()?,
        };
        let row = Arc::new(HandleEntry {
            id,
            binding: index,
            operation: checked_text(operation)?,
            resource: own_resource(resource),
            _metadata: metadata,
            _slot: charge,
            lifetime: HandleLifetime {
                stats: Arc::clone(&self.core.stats),
                counted: AtomicBool::new(false),
            },
        });
        self.core.plan.with_routes(&mut || {
            self.core.owner.policies.with_current_dependencies(
                &decision,
                self.core.plan.dependencies_for(index),
                &mut |_, _| {
                    self.core.check()?;
                    row.lifetime.counted.store(true, Ordering::Release);
                    self.core.stats.handles.fetch_add(1, Ordering::AcqRel);
                    state.slots[slot] = Some(Arc::clone(&row));
                    Ok(())
                },
            )
        })?;
        Ok(id)
    }
    /// Closing a handle never refunds work or responses which still retain it.
    pub fn close_handle(&self, handle: GuestCapabilityHandle) -> Result<(), PlatformError> {
        let mut state = self.core.state.try_lock().map_err(|_| busy())?;
        let slot = state
            .slots
            .get_mut(usize::from(handle.slot))
            .ok_or_else(denied)?;
        if slot.as_ref().is_none_or(|row| row.id != handle) {
            return Err(denied());
        }
        *slot = None;
        Ok(())
    }
    /// The state lock defines close versus new-call start. Actual provider work
    /// observes cancellation and retains its own resources after this returns.
    pub fn close(&self) {
        let mut state = self
            .core
            .state
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        self.core.stats.closed.store(true, Ordering::Release);
        state.slots.clear();
    }
    pub(super) fn row(
        &self,
        handle: GuestCapabilityHandle,
    ) -> Result<Arc<HandleEntry>, PlatformError> {
        let state = self.core.state.try_lock().map_err(|_| busy())?;
        self.core.check()?;
        state
            .slots
            .get(usize::from(handle.slot))
            .and_then(Option::as_ref)
            .filter(|row| row.id == handle)
            .cloned()
            .ok_or_else(denied)
    }
}
impl Drop for CapabilitySession {
    fn drop(&mut self) {
        if self.close_on_drop {
            self.close();
        }
    }
}
pub(super) fn next_incarnation() -> Result<u64, PlatformError> {
    static NEXT: AtomicU64 = AtomicU64::new(1);
    issue_incarnation(&NEXT)
}
pub(super) fn issue_incarnation(counter: &AtomicU64) -> Result<u64, PlatformError> {
    let mut current = counter.load(Ordering::Acquire);
    for _ in 0..16 {
        let next = current.checked_add(1).ok_or_else(capacity)?;
        match counter.compare_exchange_weak(current, next, Ordering::AcqRel, Ordering::Acquire) {
            Ok(_) => return Ok(current),
            Err(actual) => current = actual,
        }
    }
    Err(busy())
}
// Called only after PolicySnapshot::authorize has validated every borrowed fact.
fn own_resource(resource: ResourceTarget<'_>) -> ResourceRequest {
    match resource {
        ResourceTarget::Context => ResourceRequest::Context,
        ResourceTarget::Clock => ResourceRequest::Clock,
        ResourceTarget::Random => ResourceRequest::Random,
        ResourceTarget::Log { level } => ResourceRequest::Log {
            level: level.to_owned(),
        },
        ResourceTarget::Http {
            origin,
            method,
            path,
        } => ResourceRequest::Http {
            origin: origin.clone(),
            method: method.to_owned(),
            path: path.to_owned(),
        },
        ResourceTarget::Blob { namespace } => ResourceRequest::Blob {
            namespace: namespace.to_owned(),
        },
        ResourceTarget::Secrets { reference } => ResourceRequest::Secrets {
            reference: reference.to_owned(),
        },
        ResourceTarget::Events { subject } => ResourceRequest::Events {
            subject: subject.to_owned(),
        },
        ResourceTarget::Telemetry { name } => ResourceRequest::Telemetry {
            name: name.to_owned(),
        },
        ResourceTarget::Service {
            service,
            publication,
        } => ResourceRequest::Service {
            service: service.to_owned(),
            publication: publication.to_owned(),
        },
    }
}
