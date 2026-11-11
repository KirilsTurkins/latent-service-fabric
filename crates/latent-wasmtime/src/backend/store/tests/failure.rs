//! Catastrophic teardown must not refund an unproven original owner.
use super::*;
use latent_executor::ExecutionCleanup;
use std::mem::ManuallyDrop;

#[test]
fn backing_destructor_panic_preserves_original_host_owners_and_vetoes_reuse() {
    for pooled in [false, true] {
        // An allocator interrupted by a destructor panic cannot be reused or
        // torn down a second time. Retain its engine for this terminal case,
        // matching the process-lifetime retention of the unproven Store data.
        let engine = ManuallyDrop::new(engine(pooled));
        let (store, runtime, observed, _, _) = store(&engine);
        let mut retirement = RuntimeRetirement::default();
        observed
            .panic_at_allocation_drop
            .store(true, Ordering::SeqCst);
        let custody = StoreCustody::new(store, &mut retirement);
        custody.retirement.finalized(true);
        let failure = catch_unwind(AssertUnwindSafe(move || drop(custody)));
        let payload = failure.expect_err("real table allocation destructor must panic");
        assert_eq!(
            payload.downcast_ref::<&str>(),
            Some(&"injected physical allocation retirement panic")
        );
        assert_eq!(observed.allocation_drops.load(Ordering::SeqCst), 1);
        assert_eq!(observed.native_at_allocation_drop.load(Ordering::SeqCst), 1);
        assert_eq!(
            runtime.snapshot().owners[6],
            1,
            "early original owner refund: pooled={pooled}"
        );
        assert!(!retirement.store_destroyed);
        assert!(matches!(
            retirement.apply(failure_report("original-outcome")).cleanup,
            ExecutionCleanup::Quarantine { .. }
        ));
        // Catching the panic and finishing logical work cannot manufacture a
        // physical witness or a new reusable generation.
        assert!(runtime.retire().is_err());
        retirement.finalized(true);
        assert!(matches!(
            retirement
                .apply(failure_report("later-observation"))
                .cleanup,
            ExecutionCleanup::Quarantine { .. }
        ));
    }
}
