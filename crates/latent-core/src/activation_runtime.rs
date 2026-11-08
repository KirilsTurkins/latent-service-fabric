//! Activation-local logical ownership shared by language schedulers. This
//! module creates no executor, worker, guest Store, timer or capability grant.
use crate::{ActivationBudget, HostMemoryReservation, PlatformError, PlatformErrorCode};
use std::sync::{
    atomic::{AtomicU64, Ordering},
    Mutex,
};
use std::time::Instant;

mod owner_refusal;
mod shared;
use shared::{Shared, SharedWeak};
mod timer;
pub use timer::{RuntimeTimer, TimerWait};

pub const PROFILE: &str = "activation-owned-v1";
/// Frozen capability identity and operation names shared by optional node
/// installation and language qualification. These constants grant no authority.
pub const CAPABILITY: &str = "latent:runtime/activation@0.1.0";
pub const OPERATIONS: [&str; 11] = [
    "register",
    "park",
    "wake",
    "settle",
    "close",
    "observe",
    "wait-for",
    "wait-until",
    "timer-start",
    "timer-next",
    "timer-stop",
];
static GENERATION: AtomicU64 = AtomicU64::new(1);

/// Finite operator-selected ceilings. There is deliberately no product default:
/// language qualification determines the selected limits and native costs.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct RuntimeLimits {
    pub tasks: u32,
    pub executors: u32,
    pub queued_work: u32,
    pub waits: u32,
    pub timers: u32,
    pub results: u32,
    pub native_owners: u32,
}
impl RuntimeLimits {
    pub fn validate(self) -> Result<(), PlatformError> {
        let total: u64 = self.values().into_iter().map(u64::from).sum();
        if total == 0 || total > 8192 {
            return Err(error(PlatformErrorCode::InvalidArgument, "runtime-limits"));
        }
        Ok(())
    }
    const fn values(self) -> [u32; 7] {
        [
            self.tasks,
            self.executors,
            self.queued_work,
            self.waits,
            self.timers,
            self.results,
            self.native_owners,
        ]
    }
    #[must_use]
    pub fn total(self) -> usize {
        self.values().into_iter().map(|n| n as usize).sum()
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum OwnerKind {
    Task,
    ManagedIdleWorker,
    Executor,
    QueuedWork,
    Wait,
    Timer,
    Result,
    Native,
}
impl OwnerKind {
    const fn limit_reason(self) -> crate::diagnostic::DiagnosticReason {
        use crate::diagnostic::DiagnosticReason as R;
        match self {
            Self::Task | Self::ManagedIdleWorker => R::RuntimeTaskLimit,
            Self::Executor => R::RuntimeExecutorLimit,
            Self::QueuedWork => R::RuntimeQueueLimit,
            Self::Wait => R::RuntimeWaitLimit,
            Self::Timer => R::RuntimeTimerLimit,
            Self::Result => R::RuntimeResultLimit,
            Self::Native => R::RuntimeNativeOwnerLimit,
        }
    }
    const fn index(self) -> usize {
        match self {
            Self::Task | Self::ManagedIdleWorker => 0,
            Self::Executor => 1,
            Self::QueuedWork => 2,
            Self::Wait => 3,
            Self::Timer => 4,
            Self::Result => 5,
            Self::Native => 6,
        }
    }
}
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum RuntimePhase {
    Running,
    Waiting,
    Closing,
    Draining,
    Cancelling,
    Retired,
}

/// Descriptive token only. A matching token cannot create an owner or resurrect
/// settled work; every fresh Store has an independently allocated generation.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct RuntimeToken {
    pub generation: u64,
    pub id: u64,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct RuntimeSnapshot {
    pub phase: RuntimePhase,
    pub owners: [u32; 7],
    pub parked_tasks: u32,
    pub managed_idle_workers: u32,
    pub host_memory_bytes: u64,
    pub admission_failures: u64,
    pub stale_wakes: u64,
}

#[derive(Debug, Clone)]
pub struct ActivationRuntime {
    inner: Shared<Inner>,
}
#[derive(Debug)]
struct Inner {
    budget: ActivationBudget,
    limits: RuntimeLimits,
    generation: u64,
    state: Mutex<State>,
}
#[derive(Debug)]
struct State {
    phase: RuntimePhase,
    next_id: u64,
    owners: [u32; 7],
    slab: Option<Slab>,
    admission_failures: u64,
    stale_wakes: u64,
}
#[derive(Debug)]
struct Slab {
    records: Vec<Option<Record>>,
    // Drop the real records/allocation before releasing its native charge.
    _allocation: HostMemoryReservation,
}
// The repository's native allocation model reserves this much bookkeeping for
// each backing allocation. It is a finite allowance, not an RSS measurement.
const SLAB_ALLOCATION_BOOKKEEPING: usize = 64;
#[derive(Debug, Clone, Copy)]
struct Record {
    id: u64,
    kind: OwnerKind,
    parked: bool,
}

#[derive(Clone, Copy, PartialEq, Eq)]
enum AdmissionStep {
    CheckedBeforeAccounting,
    ChargedFuel,
    PreparedSlot,
    CheckedBeforePublication,
    #[cfg(test)]
    HoldingPublicationGuard,
}

/// This affine owner must remain with actual logical work/native ownership.
/// A detached provider keeps its own owner, independently of a dropped waiter.
#[derive(Debug)]
#[must_use = "retain with accepted work until actual settlement"]
pub struct RuntimeOwner {
    inner: Shared<Inner>,
    token: RuntimeToken,
}

/// Non-owning readiness delivery. The weak header retains its original memory
/// charge until actual destruction, without retaining the runtime payload.
#[derive(Debug, Clone)]
pub struct RuntimeWake {
    inner: SharedWeak<Inner>,
    token: RuntimeToken,
}

impl ActivationRuntime {
    pub fn new(budget: ActivationBudget, limits: RuntimeLimits) -> Result<Self, PlatformError> {
        limits.validate()?;
        if budget.profile() != crate::BudgetProfile::Phase3 {
            return Err(error(
                PlatformErrorCode::PermissionDenied,
                "runtime-budget-profile",
            ));
        }
        budget.descendant_snapshot()?;
        let allocation = Shared::<Inner>::reserve(&budget)?;
        let generation = GENERATION
            .fetch_update(Ordering::AcqRel, Ordering::Acquire, |n| n.checked_add(1))
            .map_err(|_| {
                error(
                    PlatformErrorCode::ResourceExhausted,
                    "runtime-generation-exhausted",
                )
            })?;
        let inner = allocation.allocate(Inner {
            budget,
            limits,
            generation,
            state: Mutex::new(State {
                phase: RuntimePhase::Running,
                next_id: 1,
                owners: [0; 7],
                slab: None,
                admission_failures: 0,
                stale_wakes: 0,
            }),
        });
        Ok(Self { inner })
    }

    /// Reserve native records before allocation/admission. Closing accepts only
    /// continuations of still-owned work under the same finite ceilings. It
    /// creates no new authority, deadline, fuel counter or physical cell.
    pub fn register(
        &self,
        kind: OwnerKind,
        continuation: Option<RuntimeToken>,
    ) -> Result<RuntimeOwner, PlatformError> {
        self.register_after_live_check(kind, continuation, || {})
    }

    fn register_after_live_check(
        &self,
        kind: OwnerKind,
        continuation: Option<RuntimeToken>,
        after_check: impl FnOnce(),
    ) -> Result<RuntimeOwner, PlatformError> {
        self.check_live()?;
        after_check();
        let mut state = self
            .inner
            .state
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        let result = self.register_locked(&mut state, kind, continuation);
        if result.is_err() {
            state.admission_failures = state.admission_failures.saturating_add(1);
        }
        result
    }

    /// Admit support owned by a still-live original Task. Checking its kind
    /// and reserving the new record share the existing registration lock, so
    /// a wrong-kind, stale or settled token cannot start native child work.
    /// This grants no external authority and preserves normal phase/limits.
    pub fn register_from_task(
        &self,
        kind: OwnerKind,
        continuation: RuntimeToken,
    ) -> Result<RuntimeOwner, PlatformError> {
        self.register_from_task_after_live_check(kind, continuation, || {})
    }

    fn register_from_task_after_live_check(
        &self,
        kind: OwnerKind,
        continuation: RuntimeToken,
        after_check: impl FnOnce(),
    ) -> Result<RuntimeOwner, PlatformError> {
        self.check_live()?;
        after_check();
        let mut state = self
            .inner
            .state
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        let result = if self
            .record(&state, continuation)
            .is_some_and(|record| record.kind == OwnerKind::Task)
        {
            self.register_locked(&mut state, kind, Some(continuation))
        } else {
            Err(error(
                PlatformErrorCode::InvalidArgument,
                "runtime-task-continuation",
            ))
        };
        if result.is_err() {
            state.admission_failures = state.admission_failures.saturating_add(1);
        }
        result
    }

    fn register_locked(
        &self,
        state: &mut State,
        kind: OwnerKind,
        continuation: Option<RuntimeToken>,
    ) -> Result<RuntimeOwner, PlatformError> {
        self.register_locked_with_hook(state, kind, continuation, |_| {})
    }

    fn register_locked_with_hook(
        &self,
        state: &mut State,
        kind: OwnerKind,
        continuation: Option<RuntimeToken>,
        mut hook: impl FnMut(AdmissionStep),
    ) -> Result<RuntimeOwner, PlatformError> {
        let inherited = match continuation {
            Some(token) if self.record(state, token).is_some() => true,
            Some(_) => {
                return Err(error(PlatformErrorCode::InvalidArgument, "runtime-token"));
            }
            None => false,
        };
        match state.phase {
            RuntimePhase::Running | RuntimePhase::Waiting => {}
            RuntimePhase::Closing | RuntimePhase::Draining if inherited => {}
            _ => {
                return Err(error(
                    PlatformErrorCode::Cancelled,
                    "runtime-admission-closed",
                ));
            }
        }
        let index = kind.index();
        if state.owners[index] >= self.inner.limits.values()[index] {
            let mut observed = crate::diagnostic::ActivationDiagnostic::new(
                crate::diagnostic::DiagnosticStage::Execution,
                kind.limit_reason(),
            );
            observed.configured_bound = Some(u64::from(self.inner.limits.values()[index]));
            observed.calculated_requirement = Some(u64::from(state.owners[index]) + 1);
            return Err(observed.attach(error(
                PlatformErrorCode::ResourceExhausted,
                "runtime-owner-limit",
            )));
        }
        let next_id = state.next_id.checked_add(1).ok_or_else(|| {
            error(
                PlatformErrorCode::ResourceExhausted,
                "runtime-token-exhausted",
            )
        })?;
        // Preserve the existing token, phase and capacity error precedence.
        // Then recheck before doing any new accounting/allocation: the first
        // liveness check preceded this lock and the original ledger may have
        // closed or reached its deadline while this operation waited.
        self.check_commit_ledger_locked(state)?;
        hook(AdmissionStep::CheckedBeforeAccounting);
        // Scanning is bounded and charged on the original fuel ledger.
        self.inner
            .budget
            .consume_cpu_fuel(100 + self.inner.limits.total() as u64)
            .map_err(|failure| match failure {
                crate::BudgetError::AccountingFinalized => {
                    state.phase = RuntimePhase::Cancelling;
                    error(PlatformErrorCode::Cancelled, "runtime-cancelled")
                }
                other => other.to_platform_error(),
            })?;
        hook(AdmissionStep::ChargedFuel);
        if state.slab.is_none() {
            let count = self.inner.limits.total();
            let bytes = std::alloc::Layout::array::<Option<Record>>(count)
                .ok()
                .and_then(|layout| layout.size().checked_add(SLAB_ALLOCATION_BOOKKEEPING))
                .and_then(|bytes| u64::try_from(bytes).ok())
                .ok_or_else(|| {
                    error(
                        PlatformErrorCode::ResourceExhausted,
                        "runtime-record-allocation",
                    )
                })?;
            let mut allocation =
                self.inner
                    .budget
                    .reserve_host_memory(bytes)
                    .map_err(|failure| match failure {
                        crate::BudgetError::AccountingFinalized => {
                            state.phase = RuntimePhase::Cancelling;
                            error(PlatformErrorCode::Cancelled, "runtime-cancelled")
                        }
                        other => other.to_host_memory_error(),
                    })?;
            let mut records = Vec::new();
            records.try_reserve_exact(count).map_err(|_| {
                error(
                    PlatformErrorCode::ResourceExhausted,
                    "runtime-record-allocation",
                )
            })?;
            allocation.confirm();
            // The pinned Global RawVec requests and records exactly `count`.
            // Refuse a changed allocator contract before publishing owners.
            if records.capacity() != count {
                return Err(error(
                    PlatformErrorCode::ResourceExhausted,
                    "runtime-record-capacity",
                ));
            }
            records.resize(count, None);
            state.slab = Some(Slab {
                records,
                _allocation: allocation,
            });
        }
        let token = RuntimeToken {
            generation: self.inner.generation,
            id: state.next_id,
        };
        let slot = state
            .slab
            .as_ref()
            .expect("reserved slab")
            .records
            .iter()
            .position(|slot| slot.is_none())
            .ok_or_else(|| error(PlatformErrorCode::ResourceExhausted, "runtime-record-limit"))?;
        hook(AdmissionStep::PreparedSlot);
        // A first admission can also have spent time reserving/allocating the
        // bounded slab, or scanning it. Recheck ledger closure and deadline;
        // the physical allocation remains prepaid until retirement.
        self.check_commit_ledger_locked(state)?;
        hook(AdmissionStep::CheckedBeforePublication);
        // Same-ledger finalization takes this accounting lock before closing.
        // Hold it through the owner write, with no production callback or
        // budget-locking operation here. Explicit cancellation, ancestor
        // closure, external probes and clock passage remain independent.
        let _publication = self.inner.budget.runtime_publication_guard();
        self.check_commit_ledger_locked(state)?;
        #[cfg(test)]
        hook(AdmissionStep::HoldingPublicationGuard);
        state.slab.as_mut().expect("reserved slab").records[slot] = Some(Record {
            id: token.id,
            kind,
            parked: false,
        });
        state.next_id = next_id;
        state.owners[index] += 1;
        if matches!(state.phase, RuntimePhase::Waiting) {
            state.phase = RuntimePhase::Running;
        }
        Ok(RuntimeOwner {
            inner: self.inner.clone(),
            token,
        })
    }

    fn record<'a>(&self, state: &'a State, token: RuntimeToken) -> Option<&'a Record> {
        if token.generation != self.inner.generation {
            return None;
        }
        state
            .slab
            .as_ref()?
            .records
            .iter()
            .flatten()
            .find(|r| r.id == token.id)
    }

    pub fn park(&self, token: RuntimeToken) -> Result<RuntimeWake, PlatformError> {
        self.park_with_after_live_check(token, || {})
    }

    fn park_with_after_live_check(
        &self,
        token: RuntimeToken,
        after_check: impl FnOnce(),
    ) -> Result<RuntimeWake, PlatformError> {
        self.check_live()?;
        after_check();
        let mut state = self
            .inner
            .state
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        let phase = state.phase;
        if token.generation != self.inner.generation {
            return Err(error(PlatformErrorCode::InvalidArgument, "runtime-token"));
        }
        let slot = state
            .slab
            .as_ref()
            .and_then(|slab| {
                slab.records
                    .iter()
                    .position(|r| r.is_some_and(|r| r.id == token.id))
            })
            .ok_or_else(|| error(PlatformErrorCode::InvalidArgument, "runtime-token"))?;
        // Cancellation can win the state lock after check_live returns. Do not
        // publish a parked owner after that transition; already accepted work
        // may still park in Closing/Draining until cancellation actually wins.
        if matches!(phase, RuntimePhase::Cancelling | RuntimePhase::Retired) {
            return Err(error(PlatformErrorCode::Cancelled, "runtime-retired"));
        }
        self.check_commit_ledger_locked(&mut state)?;
        state.slab.as_mut().expect("checked slab").records[slot]
            .as_mut()
            .expect("checked owner")
            .parked = true;
        if matches!(state.phase, RuntimePhase::Running) {
            let runnable = state.slab.as_ref().is_some_and(|slab| {
                slab.records
                    .iter()
                    .flatten()
                    .any(|r| r.kind.index() == 0 && !r.parked)
            });
            if !runnable {
                state.phase = RuntimePhase::Waiting;
            }
        }
        Ok(RuntimeWake {
            inner: self.inner.downgrade(),
            token,
        })
    }

    /// Deliver readiness without creating or changing logical ownership.
    #[must_use]
    pub fn wake(&self, token: RuntimeToken) -> bool {
        RuntimeWake {
            inner: self.inner.downgrade(),
            token,
        }
        .wake()
    }

    pub fn close(&self) {
        let mut state = self
            .inner
            .state
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        if matches!(state.phase, RuntimePhase::Running | RuntimePhase::Waiting) {
            state.phase = RuntimePhase::Closing;
        }
    }
    pub fn begin_drain(&self) {
        self.close();
        let mut state = self
            .inner
            .state
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        if state.phase == RuntimePhase::Closing {
            state.phase = RuntimePhase::Draining;
        }
    }
    pub fn cancel(&self) {
        let mut state = self
            .inner
            .state
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        if state.phase != RuntimePhase::Retired {
            state.phase = RuntimePhase::Cancelling;
            drop(state);
            // The original tree signals accepted child/provider work without
            // finalizing or releasing its actual reservations.
            let _ = self.inner.budget.cancel_descendants();
        }
    }

    /// Quiescence is based on actual settlement, never daemon/parked status or
    /// an empty logical executor queue. All native allocations remain owned
    /// through failure and are freed only with their actual Store/owners.
    pub fn retire(&self) -> Result<(), PlatformError> {
        self.close();
        let mut state = self
            .inner
            .state
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        if state.owners.iter().any(|n| *n != 0) {
            let failure = error(PlatformErrorCode::Internal, "runtime-lifecycle-unproven");
            let owners = state.owners;
            drop(state);
            owner_refusal::record(owners);
            return Err(failure);
        }
        state.phase = RuntimePhase::Retired;
        drop(state.slab.take());
        Ok(())
    }

    pub fn check_live(&self) -> Result<(), PlatformError> {
        if self.inner.budget.finalized().is_some() || self.inner.budget.descendant_is_cancelled() {
            self.cancel();
            return Err(error(PlatformErrorCode::Cancelled, "runtime-cancelled"));
        }
        self.inner
            .budget
            .check_deadline_at(Instant::now())
            .map_err(|failure| failure.to_platform_error())?;
        let phase = self
            .inner
            .state
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
            .phase;
        if matches!(phase, RuntimePhase::Cancelling | RuntimePhase::Retired) {
            return Err(error(PlatformErrorCode::Cancelled, "runtime-retired"));
        }
        Ok(())
    }

    // Called while the mutation lock is held, immediately before publication.
    // The immutable deadline and original/ancestor ledger atomic flags take no
    // locks. Do not call an external cancellation probe here: even the shipped
    // node probe takes a lifecycle mutex whose ordering is not guaranteed here.
    // This is an observation, not a handshake with a concurrent terminal event.
    fn check_commit_ledger(&self) -> Result<(), PlatformError> {
        if self.inner.budget.descendant_ledger_is_closed() {
            return Err(error(PlatformErrorCode::Cancelled, "runtime-cancelled"));
        }
        self.inner
            .budget
            .check_deadline_at(Instant::now())
            .map_err(|failure| failure.to_platform_error())
    }

    fn check_commit_ledger_locked(&self, state: &mut State) -> Result<(), PlatformError> {
        let result = self.check_commit_ledger();
        if result
            .as_ref()
            .is_err_and(|failure| failure.code == PlatformErrorCode::Cancelled)
            && state.phase != RuntimePhase::Retired
        {
            // The original/ancestor ledger owns terminal signalling. Do not
            // invoke that callback here: callers may hold other native locks.
            state.phase = RuntimePhase::Cancelling;
        }
        result
    }

    #[must_use]
    pub fn snapshot(&self) -> RuntimeSnapshot {
        let state = self
            .inner
            .state
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        let records = state
            .slab
            .as_ref()
            .map_or(&[][..], |slab| slab.records.as_slice());
        RuntimeSnapshot {
            phase: state.phase,
            owners: state.owners,
            parked_tasks: u32::try_from(
                records
                    .iter()
                    .flatten()
                    .filter(|r| r.kind.index() == 0 && r.parked)
                    .count(),
            )
            .expect("bounded runtime records"),
            managed_idle_workers: u32::try_from(
                records
                    .iter()
                    .flatten()
                    .filter(|r| r.kind == OwnerKind::ManagedIdleWorker)
                    .count(),
            )
            .expect("bounded runtime records"),
            host_memory_bytes: self.inner.budget.host_memory_bytes(),
            admission_failures: state.admission_failures,
            stale_wakes: state.stale_wakes,
        }
    }
}

impl RuntimeOwner {
    #[must_use]
    pub const fn token(&self) -> RuntimeToken {
        self.token
    }
    /// Explicit settlement has the same affine behavior as dropping the actual
    /// owner; a token, cancellation acknowledgement or root result cannot do it.
    pub fn settle(self) {
        drop(self);
    }
}
impl Drop for RuntimeOwner {
    fn drop(&mut self) {
        let mut state = self
            .inner
            .state
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        if let Some(slot) = state.slab.as_mut().and_then(|slab| {
            slab.records
                .iter_mut()
                .find(|slot| slot.is_some_and(|r| r.id == self.token.id))
        }) {
            let record = slot.take().expect("matching live owner");
            state.owners[record.kind.index()] -= 1;
        }
    }
}
impl RuntimeWake {
    /// Stale/foreign/retired completion cannot re-enter any activation. A wake
    /// reports readiness only; the language scheduler owns execution ordering.
    pub fn wake(&self) -> bool {
        self.wake_with_after_live_check(|| {})
    }

    fn wake_with_after_live_check(&self, after_check: impl FnOnce()) -> bool {
        let Some(inner) = self.inner.upgrade() else {
            return false;
        };
        let runtime = ActivationRuntime { inner };
        if runtime.check_live().is_err() {
            return false;
        }
        after_check();
        let mut state = runtime
            .inner
            .state
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        let phase = state.phase;
        let slot = state.slab.as_ref().and_then(|slab| {
            slab.records
                .iter()
                .position(|r| r.is_some_and(|r| r.id == self.token.id))
        });
        if self.token.generation != runtime.inner.generation || slot.is_none() {
            state.stale_wakes = state.stale_wakes.saturating_add(1);
            return false;
        }
        // Keep stale-token accounting above, then fence cancellation that won
        // the lock after the earlier liveness check. Closing/Draining still
        // allow already-owned work to receive readiness.
        if matches!(phase, RuntimePhase::Cancelling | RuntimePhase::Retired) {
            return false;
        }
        if runtime.check_commit_ledger_locked(&mut state).is_err() {
            return false;
        }
        state.slab.as_mut().expect("checked slab").records[slot.expect("checked slot")]
            .as_mut()
            .expect("checked owner")
            .parked = false;
        if state.phase == RuntimePhase::Waiting {
            state.phase = RuntimePhase::Running;
        }
        true
    }
}

fn error(code: PlatformErrorCode, reason: &str) -> PlatformError {
    PlatformError {
        code,
        message: reason.into(),
        details: Vec::new(),
        retryable: false,
    }
}

#[cfg(test)]
mod tests;
