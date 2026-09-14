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

/// The trusted provider/host adapter derives this from its actual operation.
/// Input bytes come from the actual slice, rather than a caller-declared length.
#[derive(Debug, Clone, Copy)]
pub struct CapabilityCallCost {
    pub maximum_output_bytes: usize,
    typed_input_bytes: usize,
    charges: [Option<(BudgetDimension, u64)>; 9],
}
impl CapabilityCallCost {
    #[must_use]
    pub const fn new(maximum_output_bytes: usize) -> Self {
        Self {
            maximum_output_bytes,
            typed_input_bytes: 0,
            charges: [None; 9],
        }
    }
    /// Trusted typed adapters count their actual payload before encoding or
    /// copying it and retain the affine call until that payload is destroyed.
    /// This is additional to the actual byte slice passed to dispatch.
    #[must_use]
    pub const fn with_typed_input_bytes(mut self, bytes: usize) -> Self {
        self.typed_input_bytes = bytes;
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
    _slot: Charge,
}
impl Drop for WorkLifetime {
    fn drop(&mut self) {
        if self.active {
            self.stats.calls.fetch_sub(1, Ordering::AcqRel);
        }
    }
}
struct Work {
    input: Zeroizing<Vec<u8>>,
    row: Arc<HandleEntry>,
    session: Arc<SessionCore>,
    id: u64,
    deadline: Instant,
    maximum_output_bytes: usize,
    input_bytes: Charge,
    output_bytes: Charge,
    result: Charge,
    metadata: Charge,
    lifetime: WorkLifetime,
}
/// One accepted operation, movable into the actual provider job. A waiting
/// future must not be the sole owner when its provider has detached real work.
/// There is no public constructor or Clone implementation.
pub struct ProviderCall {
    work: Option<Work>,
}
/// Bytes and their original activation/handle/buffer ownership are inseparable.
/// All response bytes are zeroed before their reservation is released.
struct ResultLifetime {
    stats: Arc<Stats>,
}
impl Drop for ResultLifetime {
    fn drop(&mut self) {
        self.stats.results.fetch_sub(1, Ordering::AcqRel);
    }
}
pub struct OwnedCapabilityResponse {
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
    pub fn bytes(&self) -> &[u8] {
        &self.bytes
    }
}
impl ProviderCall {
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
    pub(super) fn maximum_output_bytes(&self) -> usize {
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
            input,
            row,
            session,
            id,
            deadline: _,
            maximum_output_bytes: _,
            input_bytes,
            output_bytes,
            result,
            metadata,
            lifetime,
        } = self.work.take().expect("affine call");
        drop(input);
        drop(input_bytes);
        session.stats.results.fetch_add(1, Ordering::AcqRel);
        let result_lifetime = ResultLifetime {
            stats: Arc::clone(&session.stats),
        };
        let response = OwnedCapabilityResponse {
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
        let call = self.start_call(handle, operation, resource, input, cost)?;
        Ok(provider(call))
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
        let call = self.start_call(handle, operation, resource, input, cost)?;
        let id = call.work.as_ref().expect("new call").id;
        let response = provider(call).await.map_err(|failure| {
            let code = failure.code;
            drop(failure);
            error(code, "capability-provider-failed")
        })?;
        if !Arc::ptr_eq(&response.session, &self.core) || response.id != id {
            return Err(denied());
        }
        self.core.check()?;
        Ok(response)
    }
    fn start_call(
        &self,
        handle: GuestCapabilityHandle,
        operation: &str,
        resource: ResourceTarget<'_>,
        input: &[u8],
        cost: CapabilityCallCost,
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
        let metadata = self.core.owner.counters.acquire(Kind::Metadata, 4096)?;
        let decision = self.core.decision(
            row.binding,
            operation,
            resource,
            input_size as u64,
            cost.maximum_output_bytes as u64,
        )?;
        cost.validate_minimum(operation, &binding.provider.minimum_call_charges)?;
        let mut budget_reservation = cost.reserve(&self.core.budget)?;
        let id = super::session::next_incarnation()?;
        let mut work = Work {
            input: Zeroizing::new(input.to_vec()),
            row: Arc::clone(&row),
            session: Arc::clone(&self.core),
            id,
            deadline: self.core.owner.clock.monotonic_now(),
            maximum_output_bytes: cost.maximum_output_bytes,
            input_bytes,
            output_bytes,
            result,
            metadata,
            lifetime: WorkLifetime {
                stats: Arc::clone(&self.core.stats),
                active: false,
                _slot: call_slot,
            },
        };
        self.core
            .owner
            .policies
            .with_current(&decision, &mut |_, ceiling| {
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
                if let Some(reservation) = budget_reservation.take() {
                    reservation.commit().map_err(|e| e.to_platform_error())?;
                }
                work.lifetime.active = true;
                self.core.stats.calls.fetch_add(1, Ordering::AcqRel);
                Ok(())
            })?;
        Ok(ProviderCall { work: Some(work) })
    }
}
