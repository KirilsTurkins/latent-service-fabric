//! The stronger receipt requires actual synchronous destruction, not just counts.
use super::*;
use latent_executor::ExecutionCleanup;

fn destroy_original(
    store: Store<Data>,
    state: &mut RuntimeRetirement,
    attempted: bool,
    lift_proven: bool,
) {
    let mut custody = StoreCustody::new(store, state);
    if attempted {
        // Reproduce a real unsettled guest capture, not a synthetic trap code.
        let result = custody.data().limiter.runtime.retire();
        assert!(result.is_err());
        custody.retirement.finalized(result.is_ok());
    }
    custody.retirement.lift_proven = lift_proven;
    custody.destroy(|data| Some(data.limiter.runtime.clone()));
}

#[test]
fn post_store_receipt_requires_the_real_allocator_and_complete_call_boundary() {
    for pooled in [false, true] {
        for attempted in [false, true] {
            for lift_proven in [false, true] {
                let (store, runtime, observed, _, _) = store(&engine(pooled));
                let mut state = RuntimeRetirement::default();
                destroy_original(store, &mut state, attempted, lift_proven);
                assert_eq!(observed.native_at_allocation_drop.load(Ordering::SeqCst), 1);
                assert_eq!(observed.allocation_drops.load(Ordering::SeqCst), 1);
                assert_eq!(runtime.snapshot().owners[6], 0);
                // Even synchronous destruction is insufficient before the final
                // original-owner/observer boundary has been checked.
                assert!(matches!(
                    state.apply(failure_report("arbitrary")).cleanup,
                    ExecutionCleanup::Quarantine { .. }
                ));
                state.after_store_dropped();
                let original = failure_report("runtime-lifecycle-unproven");
                let report = state.apply(original.clone());
                assert_eq!(report.outcome, original.outcome);
                assert_eq!(report.host_result, original.host_result);
                assert_eq!(
                    matches!(report.cleanup, ExecutionCleanup::Reusable),
                    cfg!(target_os = "linux") && !pooled && attempted && lift_proven
                );
                assert_eq!(
                    state.refused, attempted,
                    "logical result must not be erased"
                );
            }
        }
    }
}

#[test]
fn live_original_owner_refuses_post_store_receipt_without_retrying_or_refunding_it() {
    let (mut store, runtime, observed, _, _) = store(&engine(false));
    // Move the actual original owner out, without changing the one-owner limit.
    let additional = store.data_mut()._owner.take().unwrap();
    let mut state = RuntimeRetirement::default();
    destroy_original(store, &mut state, true, true);
    assert_eq!(observed.native_at_allocation_drop.load(Ordering::SeqCst), 1);
    assert_eq!(runtime.snapshot().owners[6], 1);
    state.after_store_dropped();
    assert!(matches!(
        state.apply(failure_report("original-trap")).cleanup,
        ExecutionCleanup::Quarantine { .. }
    ));
    assert_eq!(runtime.snapshot().owners[6], 1);
    drop(additional);
    // This failed invocation has already consumed its one physical receipt.
    // A later unrelated owner release cannot rewrite the disposition.
    state.after_store_dropped();
    assert!(!state.physical_proven);
    assert!(matches!(
        state.apply(failure_report("later")).cleanup,
        ExecutionCleanup::Quarantine { .. }
    ));
}

#[test]
fn post_store_receipt_preserves_prior_quarantine_and_cannot_cross_store_generations() {
    let (store, _, _, _, _) = store(&engine(false));
    let mut state = RuntimeRetirement::default();
    destroy_original(store, &mut state, true, true);
    state.after_store_dropped();
    for reason in [
        "native-stack-retirement-unproven",
        "original-capability-refusal",
    ] {
        let mut original = failure_report("original-trap");
        original.cleanup = ExecutionCleanup::Quarantine {
            reason: reason.into(),
        };
        assert_eq!(state.apply(original.clone()), original);
    }
    let (store, _, _, _, _) = super::store(&engine(false));
    destroy_original(store, &mut state, true, true);
    state.after_store_dropped();
    assert!(!state.physical_proven);
    assert!(matches!(
        state.apply(failure_report("second-store")).cleanup,
        ExecutionCleanup::Quarantine { .. }
    ));
}

#[test]
fn backing_panic_cannot_publish_a_post_store_receipt() {
    let engine = std::mem::ManuallyDrop::new(engine(false));
    let (store, runtime, observed, _, _) = store(&engine);
    let mut state = RuntimeRetirement::default();
    observed
        .panic_at_allocation_drop
        .store(true, Ordering::SeqCst);
    let failure = catch_unwind(AssertUnwindSafe(|| {
        destroy_original(store, &mut state, true, true);
    }));
    assert!(failure.is_err());
    assert_eq!(runtime.snapshot().owners[6], 1);
    assert!(!state.store_destroyed);
    assert!(state.original_runtime.is_none());
    state.after_store_dropped();
    assert!(matches!(
        state.apply(failure_report("original-trap")).cleanup,
        ExecutionCleanup::Quarantine { .. }
    ));
}
