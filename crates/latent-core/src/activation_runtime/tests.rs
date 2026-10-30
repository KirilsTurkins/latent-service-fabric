use super::*;
use crate::{BudgetProfile, ClockSample, EffectiveActivationBudget, ResourceBudget};
use std::sync::Arc;

struct Signal;
impl crate::BudgetCancellationProbe for Signal {
    fn is_cancelled(&self) -> bool {
        false
    }
    fn cancelled(&self) -> crate::BoxFuture<'_, ()> {
        Box::pin(std::future::pending())
    }
    fn mark_terminal(&self) {}
}

pub(super) fn runtime() -> ActivationRuntime {
    let budget = ResourceBudget {
        cpu_fuel: 1_000_000,
        memory_bytes: 1_000_000,
        wall_time_limit_millis: Some(5000),
        child_calls: 0,
        outbound_requests: 0,
        state_read_bytes: 0,
        state_write_bytes: 0,
        blob_read_bytes: 0,
        blob_write_bytes: 0,
        log_bytes: 0,
        effect_count: 0,
    };
    let grant = EffectiveActivationBudget::admit_profile_at(
        BudgetProfile::Phase3,
        &budget,
        &budget,
        &budget,
        None,
        ClockSample::new(1000, Instant::now()),
    )
    .unwrap();
    let budget = ActivationBudget::with_profile(grant, BudgetProfile::Phase3).unwrap();
    budget
        .enable_descendants(crate::DelegationLimits::default(), Arc::new(Signal))
        .unwrap();
    ActivationRuntime::new(
        budget,
        RuntimeLimits {
            tasks: 2,
            executors: 2,
            queued_work: 2,
            waits: 2,
            timers: 2,
            results: 2,
            native_owners: 2,
        },
    )
    .unwrap()
}

#[test]
fn lazy_path_allocates_no_records_and_accepted_owners_share_finite_limits() {
    let runtime = runtime();
    let metadata = runtime.snapshot().host_memory_bytes;
    assert!(metadata > 0);
    assert!(runtime.inner.state.lock().unwrap().slab.is_none());
    let first = runtime.register(OwnerKind::Task, None).unwrap();
    let second = runtime
        .register(OwnerKind::ManagedIdleWorker, None)
        .unwrap();
    assert!(runtime.register(OwnerKind::Task, None).is_err());
    let memory = runtime.snapshot().host_memory_bytes;
    assert!(memory > 0);
    drop(first);
    assert_eq!(runtime.snapshot().host_memory_bytes, memory);
    drop(second);
    runtime.retire().unwrap();
    assert_eq!(runtime.snapshot().host_memory_bytes, metadata);
    let budget = runtime.inner.budget.clone();
    drop(runtime);
    assert_eq!(budget.host_memory_bytes(), 0);
}

#[test]
fn actual_owner_refusals_name_only_the_original_bucket_without_refunding_live_owners() {
    use crate::diagnostic::{ActivationDiagnostic, DiagnosticReason as R};
    for (kind, reason) in [
        (OwnerKind::Task, R::RuntimeTaskLimit),
        (OwnerKind::ManagedIdleWorker, R::RuntimeTaskLimit),
        (OwnerKind::Executor, R::RuntimeExecutorLimit),
        (OwnerKind::QueuedWork, R::RuntimeQueueLimit),
        (OwnerKind::Wait, R::RuntimeWaitLimit),
        (OwnerKind::Timer, R::RuntimeTimerLimit),
        (OwnerKind::Result, R::RuntimeResultLimit),
        (OwnerKind::Native, R::RuntimeNativeOwnerLimit),
    ] {
        let runtime = runtime();
        let first = runtime.register(kind, None).unwrap();
        let second = runtime.register(kind, None).unwrap();
        let before = runtime.snapshot();
        let failure = runtime.register(kind, None).unwrap_err();
        let observed = ActivationDiagnostic::from_error(&failure).unwrap();
        assert_eq!(failure.code, PlatformErrorCode::ResourceExhausted);
        assert_eq!(observed.reason, reason);
        assert_eq!(observed.configured_bound, Some(2));
        assert_eq!(observed.calculated_requirement, Some(3));
        assert_eq!(runtime.snapshot().owners, before.owners);
        drop(first);
        drop(second);
        runtime.retire().unwrap();
        assert_eq!(runtime.snapshot().owners, [0; 7]);
    }
}

#[test]
fn actual_native_reservation_refusal_keeps_original_budget_and_does_not_guess_other_dimensions() {
    use crate::diagnostic::{ActivationDiagnostic, DiagnosticReason};
    let runtime = runtime();
    let budget = &runtime.inner.budget;
    let before = budget.host_memory_bytes();
    let limit = budget.granted().memory_bytes;
    let failure = budget.reserve_host_memory(limit + 1).err().unwrap();
    assert!(ActivationDiagnostic::from_error(&failure.to_platform_error()).is_none());
    let observed = ActivationDiagnostic::from_error(&failure.to_host_memory_error()).unwrap();
    assert_eq!(observed.reason, DiagnosticReason::NativeMemoryExhausted);
    assert_eq!(observed.configured_bound, Some(limit));
    assert!(observed.calculated_requirement.unwrap() > limit);
    assert_eq!(budget.host_memory_bytes(), before);
    let fuel = budget
        .consume_cpu_fuel(budget.granted().cpu_fuel + 1)
        .unwrap_err();
    assert!(ActivationDiagnostic::from_error(&fuel.to_host_memory_error()).is_none());
}

#[test]
fn continuations_require_live_original_generation_before_any_admission() {
    let foreign = runtime();
    let runtime = runtime();
    let foreign_owner = foreign.register(OwnerKind::Task, None).unwrap();
    let metadata = runtime.snapshot().host_memory_bytes;
    let reject = |token| {
        let before = runtime.snapshot();
        let failure = runtime
            .register(OwnerKind::Result, Some(token))
            .unwrap_err();
        assert_eq!(failure.code, PlatformErrorCode::InvalidArgument);
        assert_eq!(failure.message, "runtime-token");
        let after = runtime.snapshot();
        assert_eq!(after.owners, before.owners);
        assert_eq!(after.host_memory_bytes, before.host_memory_bytes);
        assert_eq!(after.admission_failures, before.admission_failures + 1);
    };
    reject(foreign_owner.token());
    assert!(runtime.inner.state.lock().unwrap().slab.is_none());
    assert_eq!(runtime.snapshot().host_memory_bytes, metadata);

    let settled = runtime.register(OwnerKind::Task, None).unwrap();
    let stale = settled.token();
    drop(settled);
    let live = runtime.register(OwnerKind::Task, None).unwrap();
    reject(stale);
    reject(RuntimeToken {
        generation: live.token().generation,
        id: u64::MAX,
    });
    let before = runtime.snapshot().host_memory_bytes;
    let failure = RuntimeTimer::new(&runtime, Instant::now(), None, Some(stale)).unwrap_err();
    assert_eq!(failure.code, PlatformErrorCode::InvalidArgument);
    assert_eq!(runtime.snapshot().host_memory_bytes, before);

    let result = runtime
        .register(OwnerKind::Result, Some(live.token()))
        .unwrap();
    drop(result);
    runtime.begin_drain();
    reject(stale);
    reject(foreign_owner.token());
    let result = runtime
        .register(OwnerKind::Result, Some(live.token()))
        .unwrap();
    drop(result);
    drop(live);
    runtime.retire().unwrap();
    drop(foreign_owner);
    foreign.retire().unwrap();
}

#[test]
fn close_allows_bounded_live_continuations_and_rejects_independent_work() {
    let runtime = runtime();
    let task = runtime.register(OwnerKind::Task, None).unwrap();
    let token = task.token();
    runtime.close();
    runtime.begin_drain();
    assert!(runtime.register(OwnerKind::Task, None).is_err());
    let result = runtime.register(OwnerKind::Result, Some(token)).unwrap();
    let owners = runtime.snapshot().owners;
    let failure = runtime.retire().unwrap_err();
    assert_eq!(failure.code, PlatformErrorCode::Internal);
    assert_eq!(failure.message, "runtime-lifecycle-unproven");
    assert!(!failure.retryable);
    assert!(failure.details.is_empty());
    assert_eq!(runtime.snapshot().owners, owners);
    drop(task);
    assert!(runtime.register(OwnerKind::Result, Some(token)).is_err());
    drop(result);
    runtime.retire().unwrap();
    assert!(runtime.register(OwnerKind::Task, None).is_err());
}

#[test]
fn task_support_admission_checks_original_kind_and_liveness_under_the_same_lock() {
    let foreign = runtime();
    let foreign_task = foreign.register(OwnerKind::Task, None).unwrap();
    let runtime = runtime();
    let wrong_kind = runtime.register(OwnerKind::Result, None).unwrap();
    let task = runtime.register(OwnerKind::Task, None).unwrap();
    let task_token = task.token();
    let reject = |token| {
        let before = runtime.snapshot();
        let failure = runtime
            .register_from_task(OwnerKind::Native, token)
            .unwrap_err();
        assert_eq!(failure.code, PlatformErrorCode::InvalidArgument);
        assert_eq!(failure.message, "runtime-task-continuation");
        let after = runtime.snapshot();
        assert_eq!(after.owners, before.owners);
        assert_eq!(after.host_memory_bytes, before.host_memory_bytes);
        assert_eq!(after.admission_failures, before.admission_failures + 1);
    };
    reject(wrong_kind.token());
    reject(foreign_task.token());
    reject(RuntimeToken {
        generation: task_token.generation,
        id: u64::MAX,
    });
    runtime.begin_drain();
    let native = runtime
        .register_from_task(OwnerKind::Native, task_token)
        .unwrap();
    drop(task);
    reject(task_token);
    drop(native);
    drop(wrong_kind);
    runtime.retire().unwrap();
    drop(foreign_task);
    foreign.retire().unwrap();
}

#[test]
fn waking_a_parked_thread_leaves_runnable_sibling_and_fences_reused_slots() {
    let runtime = runtime();
    let first = runtime.register(OwnerKind::Task, None).unwrap();
    let second = runtime.register(OwnerKind::Task, None).unwrap();
    let wake = runtime.park(first.token()).unwrap();
    assert_eq!(runtime.snapshot().phase, RuntimePhase::Running);
    assert_eq!(runtime.snapshot().parked_tasks, 1);
    assert!(wake.wake());
    let stale = runtime.park(first.token()).unwrap();
    drop(first);
    let replacement = runtime.register(OwnerKind::Task, None).unwrap();
    assert!(!stale.wake());
    assert_eq!(runtime.snapshot().stale_wakes, 1);
    runtime.cancel();
    assert!(!wake.wake());
    assert!(runtime.retire().is_err());
    drop(second);
    drop(replacement);
    runtime.retire().unwrap();
}

#[test]
fn foreign_store_token_and_opaque_sleeping_work_cannot_establish_quiescence() {
    let first = runtime();
    let fresh = runtime();
    let owner = first.register(OwnerKind::Task, None).unwrap();
    let waiter = first.park(owner.token()).unwrap();
    assert!(fresh.park(owner.token()).is_err());
    assert!(first.retire().is_err());
    drop(owner);
    first.retire().unwrap();
    assert!(!waiter.wake());
    fresh.retire().unwrap();
}

#[test]
fn recurring_timer_coalesces_storms_and_cancelled_waits_keep_physical_ownership() {
    use std::time::Duration;
    let runtime = runtime();
    let first = Instant::now();
    let timer = RuntimeTimer::new(&runtime, first, Some(Duration::from_nanos(1)), None).unwrap();
    let mut wait = timer.begin_wait().unwrap();
    assert!(timer.begin_wait().is_err());
    assert_eq!(
        wait.complete(first + Duration::from_secs(1)).unwrap(),
        1_000_000_000
    );
    drop(wait);
    let wait = timer.begin_wait().unwrap();
    assert_eq!(
        wait.requested(),
        first + Duration::from_secs(1) + Duration::from_nanos(1)
    );
    timer.close();
    assert!(wait.is_closed());
    assert!(timer.begin_wait().is_err());
    drop(timer);
    assert_eq!(runtime.snapshot().owners[4], 1);
    assert!(runtime.retire().is_err());
    drop(wait);
    assert_eq!(runtime.snapshot().owners[4], 0);
    runtime.retire().unwrap();
}

#[test]
fn readiness_weak_headers_remain_paid_without_retaining_runtime_payload() {
    let runtime = runtime();
    let budget = runtime.inner.budget.clone();
    let runtime_bytes = Shared::<Inner>::allocation_bytes().unwrap();
    let task = runtime.register(OwnerKind::Task, None).unwrap();
    let wake = runtime.park(task.token()).unwrap();
    let second = wake.clone();
    drop(task);
    // Do not retire: destruction itself must free the real record slab even
    // while readiness clones keep only the original runtime header alive.
    assert!(budget.host_memory_bytes() > runtime_bytes);
    drop(runtime);
    assert!(!wake.wake());
    assert!(!second.wake());
    assert_eq!(budget.host_memory_bytes(), runtime_bytes);
    assert_eq!(budget.outstanding_reservations(), 1);
    drop(wake);
    assert_eq!(budget.host_memory_bytes(), runtime_bytes);
    std::thread::spawn(move || drop(second)).join().unwrap();
    assert_eq!(budget.host_memory_bytes(), 0);
    assert_eq!(budget.outstanding_reservations(), 0);
}

#[test]
fn runtime_header_refusal_precedes_generation_and_keeps_original_ledger() {
    let runtime = runtime();
    let budget = runtime.inner.budget.clone();
    let bytes = Shared::<Inner>::allocation_bytes().unwrap();
    let remaining = budget.remaining_at(Instant::now()).memory_bytes;
    let padding = budget.reserve_host_memory(remaining - bytes + 1).unwrap();
    let before = budget.host_memory_bytes();
    let reservations = budget.outstanding_reservations();
    let peak = budget.snapshot_at(Instant::now()).peak_memory_bytes;
    let failure = ActivationRuntime::new(budget.clone(), runtime.inner.limits).unwrap_err();
    assert_eq!(failure.code, PlatformErrorCode::ResourceExhausted);
    assert_eq!(budget.host_memory_bytes(), before);
    assert_eq!(budget.outstanding_reservations(), reservations);
    assert_eq!(budget.snapshot_at(Instant::now()).peak_memory_bytes, peak);
    assert!(runtime.inner.state.lock().unwrap().slab.is_none());
    drop(padding);
    let fresh = ActivationRuntime::new(budget.clone(), runtime.inner.limits).unwrap();
    assert_ne!(fresh.inner.generation, runtime.inner.generation);
    assert_eq!(budget.host_memory_bytes(), bytes * 2);
    drop(fresh);
    drop(runtime);
    assert_eq!(budget.host_memory_bytes(), 0);
    assert_eq!(budget.outstanding_reservations(), 0);
}

#[test]
fn timer_header_refusal_precedes_admission_and_waiter_retains_actual_backing() {
    let runtime = runtime();
    let budget = runtime.inner.budget.clone();
    let first = Instant::now();
    // Establish the existing lazy slab independently of timer metadata.
    drop(runtime.register(OwnerKind::Task, None).unwrap());
    let base = budget.host_memory_bytes();
    let timer = RuntimeTimer::new(&runtime, first, None, None).unwrap();
    let timer_bytes = budget.host_memory_bytes() - base;
    assert!(timer_bytes > 2 * 64);
    drop(timer);
    assert_eq!(budget.host_memory_bytes(), base);
    let remaining = budget.remaining_at(Instant::now()).memory_bytes;
    let padding = budget
        .reserve_host_memory(remaining - timer_bytes + 1)
        .unwrap();
    let before = runtime.snapshot();
    let reservations = budget.outstanding_reservations();
    let failure = RuntimeTimer::new(&runtime, first, None, None).unwrap_err();
    assert_eq!(failure.code, PlatformErrorCode::ResourceExhausted);
    assert_eq!(runtime.snapshot(), before);
    assert_eq!(budget.outstanding_reservations(), reservations);
    drop(padding);
    let timer = RuntimeTimer::new(&runtime, first, None, None).unwrap();
    let waiter = timer.begin_wait().unwrap();
    let second = timer.clone();
    timer.close();
    drop(timer);
    std::thread::spawn(move || drop(second)).join().unwrap();
    assert_eq!(budget.host_memory_bytes(), base + timer_bytes);
    assert_eq!(runtime.snapshot().owners[OwnerKind::Timer.index()], 1);
    assert_eq!(runtime.snapshot().owners[OwnerKind::Wait.index()], 1);
    assert!(runtime.retire().is_err());
    assert!(waiter.is_closed());
    drop(waiter);
    assert_eq!(runtime.snapshot().owners, [0; 7]);
    assert_eq!(budget.host_memory_bytes(), base);
    runtime.retire().unwrap();
    drop(runtime);
    assert_eq!(budget.host_memory_bytes(), 0);
    assert_eq!(budget.outstanding_reservations(), 0);
}
