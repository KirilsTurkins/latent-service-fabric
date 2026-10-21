//! A bounded diagnostic destination must not retain a child's execution grant.
use super::*;
use latent_core::{
    ActivationBudget, BudgetCancellationProbe, BudgetProfile, ClockSample, DelegationLimits,
    EffectiveActivationBudget, ResourceBudget, ResultPayload,
};
use std::sync::{atomic::AtomicBool, Mutex};
use std::task::{Poll, Waker};
use std::time::Instant;

#[derive(Default)]
struct Signal(AtomicBool, Mutex<Option<Waker>>);
impl BudgetCancellationProbe for Signal {
    fn is_cancelled(&self) -> bool {
        false
    }
    fn cancelled(&self) -> latent_core::BoxFuture<'_, ()> {
        Box::pin(std::future::poll_fn(|cx| {
            let mut waiter = self.1.lock().unwrap();
            if self.0.load(Ordering::Acquire) {
                Poll::Ready(())
            } else {
                *waiter = Some(cx.waker().clone());
                Poll::Pending
            }
        }))
    }
    fn mark_terminal(&self) {
        self.0.store(true, Ordering::Release);
        if let Some(waiter) = self.1.lock().unwrap().take() {
            waiter.wake();
        }
    }
}

#[test]
fn bounded_journal_copy_preserves_declared_error_and_retires_child_only_after_last_source_drop() {
    let sample = ClockSample::new(1000, Instant::now());
    let limits = ResourceBudget {
        cpu_fuel: 1000,
        memory_bytes: 64 * 1024,
        wall_time_limit_millis: Some(1000),
        child_calls: 16,
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
        &limits,
        &limits,
        &limits,
        None,
        sample,
    )
    .unwrap();
    let parent = ActivationBudget::with_profile(grant, BudgetProfile::Phase3).unwrap();
    parent
        .enable_descendants(DelegationLimits::default(), Arc::new(Signal::default()))
        .unwrap();
    let child_limits = ResourceBudget {
        cpu_fuel: 500,
        memory_bytes: 8 * 1024,
        child_calls: 7,
        ..limits.clone()
    };
    let pending = parent
        .delegate_at(&child_limits, &child_limits, &limits, None, sample)
        .unwrap();
    let admitted = pending.grant();
    let child = pending
        .accept(&admitted, Arc::new(Signal::default()), sample.monotonic())
        .unwrap();
    let memory = child.accounting().reserve_host_memory(4096 + 256).unwrap();
    let mut bytes = Vec::with_capacity(4096);
    bytes.extend_from_slice(b"tiny");
    let payload = ResultPayload::from_reserved(bytes, memory, child.accounting()).unwrap();
    let source_pointer = payload.as_ptr();
    child.accounting().observe_runtime_usage(7, 0).unwrap();
    let finalized = child.finish(None, sample.monotonic());
    assert!(finalized.violation().is_none());

    let (journal, _) = journal(3, 3);
    let mut input = envelope("accounted-declared-child");
    input.budget = child_limits;
    let mut owner = journal.begin(&input).unwrap();
    for phase in [
        ActivationPhase::Resolved,
        ActivationPhase::Admitted,
        ActivationPhase::Queued,
        ActivationPhase::Materializing,
        ActivationPhase::Running,
    ] {
        owner.advance(phase, Metadata::new()).unwrap();
    }
    let terminal = ActivationOutcome::DeclaredError {
        error: latent_core::DeclaredError {
            code: "domain".into(),
            message: "declared".into(),
            payload,
            media_type: "test".into(),
            metadata: Metadata::from([("meaning".into(), "preserved".into())]),
        },
        consumption: finalized.consumption().clone(),
    };
    owner.validate_terminal(&terminal).unwrap();
    let returned = owner.finish(terminal);
    let status = journal
        .status(&input.target.tenant, &input.activation_id)
        .unwrap()
        .unwrap();
    let Some(RetainedActivationOutcome::DeclaredError(retained)) = &status.terminal_outcome else {
        panic!("declared diagnostic")
    };
    assert_eq!(retained.payload.as_ref(), b"tiny");
    assert_eq!(retained.payload.capacity(), 4); // admitted compact controller copy
    assert_ne!(retained.payload.as_ptr(), source_pointer);
    assert_eq!(retained.code, "domain");
    assert_eq!(retained.metadata["meaning"], "preserved");
    assert_eq!(parent.descendant_snapshot().unwrap().live_children, 1);
    assert_eq!(parent.remaining_at(sample.monotonic()).child_calls, 8);
    assert_eq!(parent.remaining_at(sample.monotonic()).cpu_fuel, 500);
    let last_source = returned.clone();
    drop(returned);
    assert_eq!(parent.descendant_snapshot().unwrap().live_children, 1);
    drop(last_source);
    assert_eq!(parent.descendant_snapshot().unwrap().live_children, 0);
    assert_eq!(parent.remaining_at(sample.monotonic()).child_calls, 15);
    assert_eq!(parent.remaining_at(sample.monotonic()).cpu_fuel, 993);
    assert_eq!(
        parent.remaining_at(sample.monotonic()).memory_bytes,
        limits.memory_bytes
    );
    assert!(parent.snapshot_at(sample.monotonic()).peak_memory_bytes >= 4096);
    // Both cached status and its independent query clone still retain the full
    // domain classification and payload after original child ownership retires.
    assert_eq!(retained.payload.as_ref(), b"tiny");
    assert!(matches!(
        journal
            .status(&input.target.tenant, &input.activation_id)
            .unwrap()
            .unwrap()
            .terminal_outcome,
        Some(RetainedActivationOutcome::DeclaredError(_))
    ));
    assert_eq!(journal.snapshot().terminal, 1);
}
