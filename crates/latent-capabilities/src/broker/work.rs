use super::session::{HandleEntry, SessionCore, Stats};
use super::{
    busy, capacity, denied, error, stopped, CapabilitySession, Charge, GuestCapabilityHandle, Kind,
    PlatformError,
};
use latent_core::{ActivationBudget, BudgetDimension, BudgetReservationGroup, PlatformErrorCode};
use latent_policy::capability::ResourceTarget;
use std::{
    future::Future,
    sync::{atomic::Ordering, Arc},
    time::{Duration, Instant},
};
use zeroize::Zeroizing;

mod pending;
pub(super) use pending::PendingWork;

/// The trusted provider/host adapter derives this from its actual operation.
/// Input bytes come from the actual slice, rather than a caller-declared length.
#[derive(Debug, Clone, Copy)]
pub struct CapabilityCallCost {
    pub maximum_output_bytes: usize,
    typed_input_bytes: usize,
    stream_budget: Option<super::CapabilityStreamBudget>,
    typed_request_digest: Option<super::CapabilityRequestDigest>,
    charges: [Option<(BudgetDimension, u64)>; 9],
}
impl CapabilityCallCost {
    #[must_use]
    pub const fn new(maximum_output_bytes: usize) -> Self {
        Self {
            maximum_output_bytes,
            typed_input_bytes: 0,
            stream_budget: None,
            typed_request_digest: None,
            charges: [None; 9],
        }
    }
    /// Explicit streaming calls authorize total bytes separately from the small
    /// inline/lowering window. Only an affine I/O transfer can spend this budget.
    #[must_use]
    pub const fn with_stream_budget(mut self, budget: super::CapabilityStreamBudget) -> Self {
        self.stream_budget = Some(budget);
        self
    }
    /// Trusted typed adapters count their actual payload before encoding or
    /// copying it and retain the affine call until that payload is destroyed.
    /// This is additional to the actual byte slice passed to dispatch.
    #[must_use]
    pub const fn with_typed_input_bytes(mut self, bytes: usize) -> Self {
        self.typed_input_bytes = bytes;
        self
    }
    #[must_use]
    pub const fn with_typed_request_digest(
        mut self,
        digest: super::CapabilityRequestDigest,
    ) -> Self {
        self.typed_request_digest = Some(digest);
        self
    }
    /// The installed provider derives cumulative costs from its actual request.
    /// Each dimension occurs once; all dimensions are reserved atomically.
    pub fn with_charge(
        mut self,
        dimension: BudgetDimension,
        amount: u64,
    ) -> Result<Self, PlatformError> {
        let index = BudgetDimension::CUMULATIVE
            .iter()
            .position(|d| *d == dimension)
            .ok_or_else(super::invalid)?;
        if amount == 0 || self.charges[index].is_some() {
            return Err(super::invalid());
        }
        self.charges[index] = Some((dimension, amount));
        Ok(self)
    }
    fn validate_minimum(
        &self,
        operation: &str,
        required: &[super::provider::RequiredCharge],
    ) -> Result<(), PlatformError> {
        for required in required.iter().filter(|r| r.operation == operation) {
            if !self.charges.iter().flatten().any(|(dimension, amount)| {
                *dimension == required.dimension && *amount >= required.minimum
            }) {
                return Err(denied());
            }
        }
        Ok(())
    }
    fn reserve(
        &self,
        budget: &ActivationBudget,
    ) -> Result<Option<BudgetReservationGroup>, PlatformError> {
        let mut charges = [(BudgetDimension::CpuFuel, 0); 9];
        let mut count = 0;
        for charge in self.charges.into_iter().flatten() {
            charges[count] = charge;
            count += 1;
        }
        if count == 0 {
            Ok(None)
        } else {
            budget
                .reserve_group(&charges[..count])
                .map(Some)
                .map_err(|e| e.to_platform_error())
        }
    }
}

struct WorkLifetime {
    stats: Arc<Stats>,
    active: bool,
    buffer_bytes: usize,
    _slot: Charge,
}
impl Drop for WorkLifetime {
    fn drop(&mut self) {
        if self.active {
            self.stats.calls.fetch_sub(1, Ordering::AcqRel);
            self.stats
                .buffer_bytes
                .fetch_sub(self.buffer_bytes, Ordering::AcqRel);
        }
    }
}
struct Work {
    audit: Option<Box<super::audit::CallAudit>>,
    required_audit: bool,
    input_size: usize,
    pending_budget: Option<BudgetReservationGroup>,
    input: Zeroizing<Vec<u8>>,
    row: Arc<HandleEntry>,
    session: Arc<SessionCore>,
    id: u64,
    deadline: Instant,
    maximum_output_bytes: usize,
    stream_budget: Option<super::CapabilityStreamBudget>,
    input_bytes: Charge,
    output_bytes: Charge,
    result: Charge,
    metadata: Charge,
    lifetime: WorkLifetime,
}
impl Work {
    fn recheck_dispatch(&mut self) -> Result<(), PlatformError> {
        let core = Arc::clone(&self.session);
        let row = Arc::clone(&self.row);
        let live = core.owner.live.try_read().map_err(|_| busy())?;
        let binding = &core.plan.bindings[row.binding];
        let installed = binding.provider.live.try_read().map_err(|_| busy())?;
        let state = core.state.try_lock().map_err(|_| busy())?;
        if !*live
            || !*installed
            || state
                .slots
                .get(usize::from(row.id.wire_parts().0))
                .and_then(Option::as_ref)
                .is_none_or(|current| !Arc::ptr_eq(current, &row))
        {
            return Err(denied());
        }
        let dimensions = super::stream_budget::policy_bytes(
            self.input_size,
            self.maximum_output_bytes,
            self.stream_budget,
        )?;
        let decision = core.decision_with_streaming(
            row.binding,
            &row.operation,
            row.resource.target(),
            dimensions,
            self.stream_budget.is_some(),
        )?;
        if !decision.requires_audit() {
            return Err(denied());
        }
        core.plan.with_routes(&mut || {
            core.owner.policies.with_current_dependencies(
                &decision,
                core.plan.dependencies_for(row.binding),
                &mut |_, _| {
                    core.check()?;
                    if core.owner.clock.monotonic_now() >= self.deadline {
                        return Err(error(
                            PlatformErrorCode::DeadlineExceeded,
                            "capability-call-deadline",
                        ));
                    }
                    if let Some(reservation) = self.pending_budget.take() {
                        reservation.commit().map_err(|e| e.to_platform_error())?;
                    }
                    Ok(())
                },
            )
        })
    }
}
/// One accepted operation, movable into the actual provider job. A waiting
/// future must not be the sole owner when its provider has detached real work.
/// There is no public constructor or Clone implementation.
pub struct ProviderCall {
    work: Option<Work>,
}
/// Bounded owned preparation for asynchronous host adapters. Only `dispatch`
/// exposes the affine provider call, after any required journal admission and
/// the final authority recheck. No public DTO can construct this owner.
pub struct CapabilityDispatch {
    call: Option<ProviderCall>,
    _lookup: Option<LookupOwner>,
}
struct LookupOwner {
    core: Arc<SessionCore>,
    id: GuestCapabilityHandle,
}
impl Drop for LookupOwner {
    fn drop(&mut self) {
        let mut state = self
            .core
            .state
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        if let Some(slot) = state.slots.get_mut(usize::from(self.id.wire_parts().0)) {
            if slot.as_ref().is_some_and(|row| row.id == self.id) {
                *slot = None;
            }
        }
    }
}
impl CapabilityDispatch {
    pub async fn dispatch<T>(
        mut self,
        provider: impl FnOnce(ProviderCall) -> T,
    ) -> Result<T, PlatformError> {
        self.call
            .as_mut()
            .expect("affine prepared call")
            .audit_before_dispatch()
            .await?;
        Ok(provider(self.call.take().expect("affine prepared call")))
    }
}
/// Bytes and their original activation/handle/buffer ownership are inseparable.
/// All response bytes are zeroed before their reservation is released.
struct ResultLifetime {
    stats: Arc<Stats>,
    buffer_bytes: usize,
}
impl Drop for ResultLifetime {
    fn drop(&mut self) {
        self.stats.results.fetch_sub(1, Ordering::AcqRel);
        self.stats
            .buffer_bytes
            .fetch_sub(self.buffer_bytes, Ordering::AcqRel);
    }
}
pub struct OwnedCapabilityResponse {
    audit: Option<Box<super::audit::CallAudit>>,
    deadline: Instant,
    bytes: Zeroizing<Vec<u8>>,
    pub(super) session: Arc<SessionCore>,
    _row: Arc<HandleEntry>,
    id: u64,
    _bytes: Charge,
    _metadata: Charge,
    _result: Charge,
    _lifetime: ResultLifetime,
}
impl OwnedCapabilityResponse {
    #[must_use]
    pub fn audit_durability(&self) -> super::CapabilityAuditDurability {
        self.audit
            .as_ref()
            .map_or(super::CapabilityAuditDurability::NotRequired, |audit| {
                audit.durability()
            })
    }
    #[must_use]
    pub fn provider_outcome(&self) -> Option<latent_audit::AuditProviderOutcome> {
        self.audit.as_ref().map(|audit| audit.outcome())
    }
    pub async fn finish_audit(&mut self) -> super::CapabilityAuditDurability {
        match &mut self.audit {
            Some(audit) => audit.finish(self.deadline).await,
            None => super::CapabilityAuditDurability::NotRequired,
        }
    }
    #[must_use]
    pub fn bytes(&self) -> &[u8] {
        &self.bytes
    }
}
impl ProviderCall {
    pub(super) fn stream_budget(&self) -> Option<super::CapabilityStreamBudget> {
        self.work.as_ref().expect("affine call").stream_budget
    }
    pub(super) fn session_core(&self) -> Arc<SessionCore> {
        Arc::clone(&self.work.as_ref().expect("affine call").session)
    }
    pub(super) fn take_audit(&mut self) -> Option<Box<super::audit::CallAudit>> {
        self.work.as_mut().expect("affine call").audit.take()
    }
    pub(super) fn restore_audit(&mut self, audit: Box<super::audit::CallAudit>) {
        let work = self.work.as_mut().expect("affine call");
        debug_assert!(work.audit.is_none());
        work.audit = Some(audit);
    }
    /// A trusted adapter records the evidence it actually received, including
    /// after cancellation. This method neither grants nor refreshes permission.
    pub fn record_provider_outcome(
        &mut self,
        outcome: latent_audit::AuditProviderOutcome,
    ) -> Result<(), PlatformError> {
        if let Some(audit) = &mut self.work.as_mut().expect("affine call").audit {
            audit.record_outcome(outcome)?;
        }
        Ok(())
    }
    pub async fn finish_audit(&mut self) -> super::CapabilityAuditDurability {
        let work = self.work.as_mut().expect("affine call");
        match &mut work.audit {
            Some(audit) => audit.finish(work.deadline).await,
            None => super::CapabilityAuditDurability::NotRequired,
        }
    }
    async fn audit_before_dispatch(&mut self) -> Result<(), PlatformError> {
        let work = self.work.as_mut().expect("affine call");
        if let Some(audit) = &mut work.audit {
            audit.begin(&work.session, work.deadline).await?;
            audit.arm()?;
        }
        if work.required_audit {
            #[cfg(test)]
            super::audit::after_begin();
            work.recheck_dispatch()?;
        }
        if let Some(audit) = &mut work.audit {
            audit.dispatched();
        }
        Ok(())
    }
    fn dispatched(&mut self) {
        if let Some(audit) = &mut self.work.as_mut().expect("affine call").audit {
            audit.dispatched();
        }
    }
    /// Require the physical host mode before running an in-process host adapter.
    /// A direct local interface binding is not permission to run its host twin.
    pub fn require_host_mode(&self) -> Result<(), PlatformError> {
        self.check()?;
        let work = self.work.as_ref().expect("affine call");
        let binding = &work.session.plan.bindings[work.row.binding];
        if binding.local_target.is_some() || binding.invocation_target.is_some() {
            return Err(denied());
        }
        Ok(())
    }

    /// Resolve only the target whose exact Service resource was authorized by
    /// this affine call. Neither this descriptor nor a guest target is a permit.
    pub fn local_invocation_target(
        &self,
        requested: &latent_routing::InvocationTarget,
    ) -> Result<latent_routing::ResolvedRevision, PlatformError> {
        self.check()?;
        let work = self.work.as_ref().expect("affine call");
        let target = work.session.plan.bindings[work.row.binding]
            .invocation_target
            .as_ref()
            .ok_or_else(denied)?
            .resolve(requested)?;
        match &work.row.resource {
            latent_policy::capability::ResourceRequest::Service {
                service,
                publication,
            } if service == &target.target.service.0
                && target
                    .publication
                    .as_ref()
                    .is_some_and(|id| id.as_str() == publication)
                && work.row.operation == "call" =>
            {
                Ok(target)
            }
            _ => Err(denied()),
        }
    }

    /// Trusted source identity for a child, deliberately without caller claims
    /// or administrator privileges. The target tenant remains a separate check.
    #[must_use]
    pub fn local_invocation_principal(
        &self,
        tenant: latent_core::TenantId,
    ) -> latent_core::InvocationPrincipal {
        let session = &self.work.as_ref().expect("affine call").session;
        let source = &session.plan.target;
        latent_core::InvocationPrincipal {
            subject: format!(
                "service:{}:{}:{}:{}",
                source.tenant.0.len(),
                source.tenant.0,
                source.service.0.len(),
                source.service.0
            ),
            kind: latent_core::PrincipalKind::Service,
            tenant: Some(tenant),
            service: Some(source.service.clone()),
            claims: latent_core::Metadata::new(),
        }
    }

    #[must_use]
    pub fn root_activation_id(&self) -> &latent_core::ActivationId {
        &self
            .work
            .as_ref()
            .expect("affine call")
            .session
            .root_activation_id
    }
    pub fn check_local_node(
        &self,
        clock: &Arc<dyn latent_core::ActivationClock>,
        publication: &latent_artifacts::ReleaseUseEligibility,
    ) -> Result<(), PlatformError> {
        self.check()?;
        let owner = &self.work.as_ref().expect("affine call").session.owner;
        if !Arc::ptr_eq(&owner.clock, clock) {
            return Err(denied());
        }
        publication.check_for_catalog(&owner.catalog)
    }

    /// The exact local revision and operation compiled for this accepted call.
    /// This owned descriptor grants no independent execution authority: a child
    /// must retain this call's admission, cancellation and descendant budget.
    pub fn local_target(&self) -> Result<latent_routing::ResolvedRevision, PlatformError> {
        self.check()?;
        let work = self.work.as_ref().expect("affine call");
        let mut target = work.session.plan.bindings[work.row.binding]
            .local_target
            .as_ref()
            .ok_or_else(denied)?
            .clone();
        target.target.function.0.clone_from(&work.row.operation);
        Ok(target)
    }

    pub(super) fn provider_matches(&self, provider: &super::ProviderReference) -> bool {
        let work = self.work.as_ref().expect("affine call");
        Arc::ptr_eq(
            &work.session.plan.bindings[work.row.binding].provider,
            &provider.entry,
        )
    }
    /// The original runtime-owned ledger, never an independently minted grant.
    /// Retaining this handle does not make ledger finalization a cleanup proof.
    /// `CapabilityCallCost` reserves and commits actual provider charges before
    /// dispatch. #208 extends the admission/delegation profile for later counters.
    #[must_use]
    pub fn budget_accounting(&self) -> &ActivationBudget {
        &self.work.as_ref().expect("affine call").session.budget
    }
    #[must_use]
    pub fn input(&self) -> &[u8] {
        &self.work.as_ref().expect("affine call").input
    }
    #[must_use]
    pub fn activation_id(&self) -> &latent_core::ActivationId {
        &self
            .work
            .as_ref()
            .expect("affine call")
            .session
            .activation_id
    }
    #[must_use]
    pub fn deadline(&self) -> Instant {
        self.work.as_ref().expect("affine call").deadline
    }
    #[must_use]
    pub fn is_cancelled(&self) -> bool {
        self.check().is_err()
    }
    pub(super) fn same_session(&self, session: &Arc<SessionCore>) -> bool {
        Arc::ptr_eq(&self.work.as_ref().expect("affine call").session, session)
    }
    #[must_use]
    pub fn maximum_output_bytes(&self) -> usize {
        self.work
            .as_ref()
            .expect("affine call")
            .maximum_output_bytes
    }
    pub(super) fn check(&self) -> Result<(), PlatformError> {
        let work = self.work.as_ref().expect("affine call");
        work.session.check()?;
        if work.session.owner.clock.monotonic_now() >= work.deadline {
            return Err(error(
                PlatformErrorCode::DeadlineExceeded,
                "capability-call-deadline",
            ));
        }
        if !*work.session.owner.live.try_read().map_err(|_| busy())? {
            return Err(stopped());
        }
        Ok(())
    }
    pub fn complete(mut self, bytes: &[u8]) -> Result<OwnedCapabilityResponse, PlatformError> {
        self.check()?;
        if bytes.len()
            > self
                .work
                .as_ref()
                .expect("affine call")
                .maximum_output_bytes
        {
            return Err(capacity());
        }
        let data = Zeroizing::new(bytes.to_vec());
        let Work {
            audit,
            required_audit: _,
            stream_budget: _,
            input_size,
            pending_budget: _,
            input,
            row,
            session,
            id,
            deadline,
            maximum_output_bytes,
            input_bytes,
            output_bytes,
            result,
            metadata,
            mut lifetime,
        } = self.work.take().expect("affine call");
        drop(input);
        drop(input_bytes);
        session.stats.results.fetch_add(1, Ordering::AcqRel);
        let result_lifetime = ResultLifetime {
            stats: Arc::clone(&session.stats),
            buffer_bytes: maximum_output_bytes,
        };
        lifetime.buffer_bytes = input_size;
        let response = OwnedCapabilityResponse {
            audit,
            deadline,
            bytes: data,
            session,
            _row: row,
            id,
            _bytes: output_bytes,
            _metadata: metadata,
            _result: result,
            _lifetime: result_lifetime,
        };
        drop(lifetime);
        Ok(response)
    }
}
impl CapabilitySession {
    pub fn prepare_owned_dispatch(
        &self,
        capability: &str,
        operation: &str,
        resource: ResourceTarget<'_>,
        input: &[u8],
        cost: CapabilityCallCost,
    ) -> Result<CapabilityDispatch, PlatformError> {
        let handle = self.bind(capability, operation, resource)?;
        let lookup = LookupOwner {
            core: Arc::clone(&self.core),
            id: handle,
        };
        let call = self.start_call(handle, operation, resource, input, cost, true)?;
        Ok(CapabilityDispatch {
            call: Some(call),
            _lookup: Some(lookup),
        })
    }
    /// Synchronous trusted adapter dispatch. The constructor is entered directly
    /// after the guarded start, with all fences released. It must move the affine
    /// call into the actual work/lowering owner before returning; this API does
    /// not declare caller-owned typed results to be reclaimed.
    pub fn dispatch<T>(
        &self,
        handle: GuestCapabilityHandle,
        operation: &str,
        resource: ResourceTarget<'_>,
        input: &[u8],
        cost: CapabilityCallCost,
        provider: impl FnOnce(ProviderCall) -> T,
    ) -> Result<T, PlatformError> {
        let mut call = self.start_call(handle, operation, resource, input, cost, false)?;
        call.dispatched();
        Ok(provider(call))
    }
    /// Await required audit admission outside all authority/Store fences, then
    /// recheck currentness before entering the real provider constructor.
    pub async fn dispatch_audited<T>(
        &self,
        handle: GuestCapabilityHandle,
        operation: &str,
        resource: ResourceTarget<'_>,
        input: &[u8],
        cost: CapabilityCallCost,
        provider: impl FnOnce(ProviderCall) -> T,
    ) -> Result<T, PlatformError> {
        let call = self.start_call(handle, operation, resource, input, cost, true)?;
        CapabilityDispatch {
            call: Some(call),
            _lookup: None,
        }
        .dispatch(provider)
        .await
    }
    /// No work is accepted until this future is polled. The provider constructor
    /// is called immediately after final admission, with every fence released.
    /// Pool queueing belongs before this call; there is no internal work queue.
    pub async fn call<F, Fut>(
        &self,
        handle: GuestCapabilityHandle,
        operation: &str,
        resource: ResourceTarget<'_>,
        input: &[u8],
        cost: CapabilityCallCost,
        provider: F,
    ) -> Result<OwnedCapabilityResponse, PlatformError>
    where
        F: FnOnce(ProviderCall) -> Fut,
        Fut: Future<Output = Result<OwnedCapabilityResponse, PlatformError>>,
    {
        let mut call = self.start_call(handle, operation, resource, input, cost, true)?;
        call.audit_before_dispatch().await?;
        let id = call.work.as_ref().expect("new call").id;
        let mut response = provider(call).await.map_err(|failure| {
            let code = failure.code;
            drop(failure);
            error(code, "capability-provider-failed")
        })?;
        if !Arc::ptr_eq(&response.session, &self.core) || response.id != id {
            return Err(denied());
        }
        response.finish_audit().await;
        self.core.check()?;
        Ok(response)
    }
    #[expect(
        clippy::too_many_lines,
        reason = "affine reservations and the final start fence form one call admission boundary"
    )]
    fn start_call(
        &self,
        handle: GuestCapabilityHandle,
        operation: &str,
        resource: ResourceTarget<'_>,
        input: &[u8],
        cost: CapabilityCallCost,
        audited: bool,
    ) -> Result<ProviderCall, PlatformError> {
        let live = self.core.owner.live.try_read().map_err(|_| busy())?;
        if !*live {
            return Err(denied());
        }
        let row = self.row(handle)?;
        if row.operation != operation || row.resource.target() != resource {
            return Err(denied());
        }
        let binding = &self.core.plan.bindings[row.binding];
        let installed = binding.provider.live.try_read().map_err(|_| busy())?;
        if !*installed {
            return Err(denied());
        }
        let state = self.core.state.try_lock().map_err(|_| busy())?;
        self.core.check()?;
        if state
            .slots
            .get(usize::from(handle.wire_parts().0))
            .and_then(Option::as_ref)
            .is_none_or(|current| !Arc::ptr_eq(current, &row))
        {
            return Err(denied());
        }
        let limits = self.core.owner.limits;
        let input_size = input
            .len()
            .checked_add(cost.typed_input_bytes)
            .ok_or_else(capacity)?;
        if input_size > limits.maximum_input_bytes
            || cost.maximum_output_bytes > limits.maximum_output_bytes
            || cost.stream_budget.is_some_and(|stream| {
                stream.input_bytes() > limits.maximum_stream_input_bytes
                    || stream.output_bytes() > limits.maximum_stream_output_bytes
            })
            || self.core.stats.calls.load(Ordering::Acquire) >= limits.maximum_calls_per_session
        {
            return Err(capacity());
        }
        let call_slot = self.core.owner.counters.acquire(Kind::Call, 1)?;
        let result = self.core.owner.counters.acquire(Kind::Result, 1)?;
        let input_bytes = self.core.owner.counters.acquire(Kind::Buffer, input_size)?;
        let output_bytes = self
            .core
            .owner
            .counters
            .acquire(Kind::Buffer, cost.maximum_output_bytes)?;
        let metadata = self.core.owner.counters.acquire(
            Kind::Metadata,
            if self.core.owner.audit.is_some() {
                16384
            } else {
                4096
            },
        )?;
        let dimensions = super::stream_budget::policy_bytes(
            input_size,
            cost.maximum_output_bytes,
            cost.stream_budget,
        )?;
        let decision = self.core.decision_with_streaming(
            row.binding,
            operation,
            resource,
            dimensions,
            cost.stream_budget.is_some(),
        )?;
        let required_audit = decision.requires_audit();
        if required_audit
            && (!audited || (cost.typed_input_bytes != 0 && cost.typed_request_digest.is_none()))
        {
            return Err(error(
                PlatformErrorCode::PermissionDenied,
                "capability-required-audit-path",
            ));
        }
        cost.validate_minimum(operation, &binding.provider.minimum_call_charges)?;
        let budget_reservation = cost.reserve(&self.core.budget)?;
        let id = super::session::next_incarnation()?;
        let audit = if self.core.owner.audit.is_some() || required_audit {
            if cost.typed_input_bytes != 0 && cost.typed_request_digest.is_none() {
                if let Some(configuration) = &self.core.owner.audit {
                    configuration.note_dropped();
                }
                None // Optional diagnostics must never assert a digest of omitted typed inputs.
            } else {
                super::audit::CallAudit::prepare(
                    &self.core,
                    row.binding,
                    operation,
                    resource,
                    super::audit::request_digest(
                        operation,
                        resource,
                        input,
                        cost.typed_request_digest,
                    ),
                    required_audit,
                    id,
                )?
            }
        } else {
            None
        };
        let mut work = Work {
            audit,
            required_audit,
            input_size,
            pending_budget: budget_reservation,
            input: Zeroizing::new(input.to_vec()),
            row: Arc::clone(&row),
            session: Arc::clone(&self.core),
            id,
            deadline: self.core.owner.clock.monotonic_now(),
            maximum_output_bytes: cost.maximum_output_bytes,
            stream_budget: cost.stream_budget,
            input_bytes,
            output_bytes,
            result,
            metadata,
            lifetime: WorkLifetime {
                stats: Arc::clone(&self.core.stats),
                active: false,
                buffer_bytes: input_size + cost.maximum_output_bytes,
                _slot: call_slot,
            },
        };
        self.core.plan.with_routes(&mut || {
            self.core.owner.policies.with_current_dependencies(
                &decision,
                self.core.plan.dependencies_for(row.binding),
                &mut |_, ceiling| {
                    self.core.check()?;
                    let now = self.core.owner.clock.monotonic_now();
                    let policy_deadline = now
                        .checked_add(Duration::from_millis(ceiling.wall_time_millis))
                        .ok_or_else(capacity)?;
                    work.deadline = self
                        .core
                        .deadline
                        .monotonic()
                        .map_or(policy_deadline, |d| d.min(policy_deadline));
                    if now >= work.deadline {
                        return Err(error(
                            PlatformErrorCode::DeadlineExceeded,
                            "capability-call-deadline",
                        ));
                    }
                    if !required_audit {
                        if let Some(reservation) = work.pending_budget.take() {
                            reservation.commit().map_err(|e| e.to_platform_error())?;
                        }
                    }
                    work.lifetime.active = true;
                    self.core.stats.calls.fetch_add(1, Ordering::AcqRel);
                    self.core
                        .stats
                        .buffer_bytes
                        .fetch_add(work.lifetime.buffer_bytes, Ordering::AcqRel);
                    Ok(())
                },
            )
        })?;
        Ok(ProviderCall { work: Some(work) })
    }
}
