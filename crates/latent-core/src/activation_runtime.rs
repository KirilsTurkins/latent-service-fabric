//! Activation-local logical ownership shared by language schedulers. This
//! module creates no executor, worker, guest Store, timer or capability grant.
use crate::{ActivationBudget, HostMemoryReservation, PlatformError, PlatformErrorCode};
use std::sync::{
    atomic::{AtomicU64, Ordering},
    Arc, Mutex, Weak,
};
use std::time::Instant;

mod timer;
pub use timer::{RuntimeTimer, TimerWait};

pub const PROFILE: &str = "activation-owned-v1";
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
    inner: Arc<Inner>,
}
#[derive(Debug)]
struct Inner {
    budget: ActivationBudget,
    limits: RuntimeLimits,
    generation: u64,
    state: Mutex<State>,
    // The Arc and mutex live until the final actual runtime owner is dropped.
    allocation: HostMemoryReservation,
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
#[derive(Debug, Clone, Copy)]
struct Record {
    id: u64,
    kind: OwnerKind,
    parked: bool,
}

/// This affine owner must remain with actual logical work/native ownership.
/// A detached provider keeps its own owner, independently of a dropped waiter.
#[derive(Debug)]
#[must_use = "retain with accepted work until actual settlement"]
pub struct RuntimeOwner {
    inner: Arc<Inner>,
    token: RuntimeToken,
}

/// Non-owning readiness delivery; never retains a Store or budget after drop.
#[derive(Debug, Clone)]
pub struct RuntimeWake {
    inner: Weak<Inner>,
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
        let allocation = budget
            .reserve_host_memory(
                (std::mem::size_of::<Inner>() + 2 * std::mem::size_of::<usize>() + 64) as u64,
            )
            .map_err(|failure| failure.to_platform_error())?;
        let generation = GENERATION
            .fetch_update(Ordering::AcqRel, Ordering::Acquire, |n| n.checked_add(1))
            .map_err(|_| {
                error(
                    PlatformErrorCode::ResourceExhausted,
                    "runtime-generation-exhausted",
                )
            })?;
        let mut inner = Arc::new(Inner {
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
            allocation,
        });
        Arc::get_mut(&mut inner)
            .expect("fresh sole runtime owner")
            .allocation
            .confirm();
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
        self.check_live()?;
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

    fn register_locked(
        &self,
        state: &mut State,
        kind: OwnerKind,
        continuation: Option<RuntimeToken>,
    ) -> Result<RuntimeOwner, PlatformError> {
        let inherited = continuation.is_some_and(|token| self.record(state, token).is_some());
        match state.phase {
            RuntimePhase::Running | RuntimePhase::Waiting => {}
            RuntimePhase::Closing | RuntimePhase::Draining if inherited => {}
            _ => {
                return Err(error(
                    PlatformErrorCode::Cancelled,
                    "runtime-admission-closed",
                ))
            }
        }
        let index = kind.index();
        if state.owners[index] >= self.inner.limits.values()[index] {
            return Err(error(
                PlatformErrorCode::ResourceExhausted,
                "runtime-owner-limit",
            ));
        }
        let next_id = state.next_id.checked_add(1).ok_or_else(|| {
            error(
                PlatformErrorCode::ResourceExhausted,
                "runtime-token-exhausted",
            )
        })?;
        // Scanning is bounded and charged on the original fuel ledger.
        self.inner
            .budget
            .consume_cpu_fuel(100 + self.inner.limits.total() as u64)
            .map_err(|failure| failure.to_platform_error())?;
        if state.slab.is_none() {
            let count = self.inner.limits.total();
            let bytes = count as u64 * std::mem::size_of::<Option<Record>>() as u64;
            let mut allocation = self
                .inner
                .budget
                .reserve_host_memory(bytes)
                .map_err(|failure| failure.to_platform_error())?;
            let mut records = Vec::new();
            records.try_reserve_exact(count).map_err(|_| {
                error(
                    PlatformErrorCode::ResourceExhausted,
                    "runtime-record-allocation",
                )
            })?;
            records.resize(count, None);
            allocation.confirm();
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
            .as_mut()
            .expect("reserved slab")
            .records
            .iter_mut()
            .find(|slot| slot.is_none())
            .ok_or_else(|| error(PlatformErrorCode::ResourceExhausted, "runtime-record-limit"))?;
        *slot = Some(Record {
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
            inner: Arc::clone(&self.inner),
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
        self.check_live()?;
        let mut state = self
            .inner
            .state
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        if token.generation != self.inner.generation {
            return Err(error(PlatformErrorCode::InvalidArgument, "runtime-token"));
        }
        let record = state
            .slab
            .as_mut()
            .and_then(|slab| slab.records.iter_mut().flatten().find(|r| r.id == token.id))
            .ok_or_else(|| error(PlatformErrorCode::InvalidArgument, "runtime-token"))?;
        record.parked = true;
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
            inner: Arc::downgrade(&self.inner),
            token,
        })
    }

    /// Deliver readiness without creating or changing logical ownership.
    #[must_use]
    pub fn wake(&self, token: RuntimeToken) -> bool {
        RuntimeWake {
            inner: Arc::downgrade(&self.inner),
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
            return Err(error(
                PlatformErrorCode::Internal,
                "runtime-lifecycle-unproven",
            ));
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
        let Some(inner) = self.inner.upgrade() else {
            return false;
        };
        let runtime = ActivationRuntime { inner };
        if runtime.check_live().is_err() {
            return false;
        }
        let mut state = runtime
            .inner
            .state
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        let record = state.slab.as_mut().and_then(|slab| {
            slab.records
                .iter_mut()
                .flatten()
                .find(|r| r.id == self.token.id)
        });
        if self.token.generation != runtime.inner.generation || record.is_none() {
            state.stale_wakes = state.stale_wakes.saturating_add(1);
            return false;
        }
        record.expect("checked owner").parked = false;
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
