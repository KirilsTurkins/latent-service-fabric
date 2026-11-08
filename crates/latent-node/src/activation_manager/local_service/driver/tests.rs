use super::*;
use crate::activation_manager::ActivationTransportInterruption;
use latent_core::{BudgetProfile, ClockSample, EffectiveActivationBudget, ResourceBudget};
use std::{
    mem::{align_of, size_of},
    panic::{catch_unwind, AssertUnwindSafe},
    sync::{
        atomic::{AtomicBool, AtomicUsize, Ordering},
        Arc,
    },
    task::Waker,
    time::Instant,
};

fn budget(bytes: u64) -> ActivationBudget {
    let request = ResourceBudget {
        cpu_fuel: 1_000,
        memory_bytes: bytes,
        wall_time_limit_millis: Some(60_000),
        child_calls: 1,
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
        &request,
        &request,
        &request,
        None,
        ClockSample::new(1000, Instant::now()),
    )
    .unwrap();
    ActivationBudget::with_profile(grant, BudgetProfile::Phase3).unwrap()
}

struct Tracked {
    budget: ActivationBudget,
    drops: Arc<AtomicUsize>,
    panic_drop: Arc<AtomicBool>,
}
impl Future for Tracked {
    type Output = ();
    fn poll(self: Pin<&mut Self>, _: &mut Context<'_>) -> Poll<()> {
        Poll::Pending
    }
}
impl Drop for Tracked {
    fn drop(&mut self) {
        assert!(self.budget.host_memory_bytes() >= charge::<Self>().unwrap());
        self.drops.fetch_add(1, Ordering::SeqCst);
        assert!(!self.panic_drop.load(Ordering::Acquire), "driver drop");
    }
}

#[test]
fn refuses_before_builder_and_keeps_owning_charge_through_drop() {
    let bytes = charge::<Tracked>().unwrap();
    let rejected = budget(bytes - 1);
    assert!(PreparedDriver::<Tracked>::new(&rejected).is_err());
    assert_eq!(rejected.host_memory_bytes(), 0);

    let parent = budget(bytes);
    let count = Arc::new(AtomicUsize::new(0));
    let fail_drop = Arc::new(AtomicBool::new(false));
    let prepared = PreparedDriver::<Tracked>::new(&parent).unwrap();
    assert_eq!(parent.host_memory_bytes(), bytes);
    let mut driver = prepared.finish(|| Tracked {
        budget: parent.clone(),
        drops: count.clone(),
        panic_drop: fail_drop.clone(),
    });
    assert!(Pin::new(&mut driver)
        .poll(&mut Context::from_waker(Waker::noop()))
        .is_pending());
    assert_eq!(parent.host_memory_bytes(), bytes);
    drop(driver);
    assert_eq!(count.load(Ordering::SeqCst), 1);
    assert_eq!(parent.host_memory_bytes(), 0);
}

#[test]
fn builder_unwind_refunds_only_unallocated_storage() {
    let parent = budget(charge::<Tracked>().unwrap());
    let prepared = PreparedDriver::<Tracked>::new(&parent).unwrap();
    assert!(catch_unwind(AssertUnwindSafe(|| {
        let _ = prepared.finish(|| -> Tracked {
            panic!("driver builder");
        });
    }))
    .is_err());
    assert_eq!(parent.host_memory_bytes(), 0);
}

#[test]
fn destructor_unwind_retains_the_original_driver_charge() {
    let parent = budget(charge::<Tracked>().unwrap());
    let drops = Arc::new(AtomicUsize::new(0));
    let panic_drop = Arc::new(AtomicBool::new(true));
    let driver = PreparedDriver::<Tracked>::new(&parent)
        .unwrap()
        .finish(|| Tracked {
            budget: parent.clone(),
            drops: drops.clone(),
            panic_drop,
        });
    assert!(catch_unwind(AssertUnwindSafe(|| drop(driver))).is_err());
    assert_eq!(drops.load(Ordering::SeqCst), 1);
    assert_eq!(parent.host_memory_bytes(), charge::<Tracked>().unwrap());
    assert_eq!(parent.outstanding_reservations(), 1);
}

// This is the pre-change driver body. Its future type witnesses the inline
// Tokio task payload that existed before the separate charged driver Box.
async fn original_driver(
    mut activation: ActivationHandle,
    child: ChildBudgetOwner,
    call: ProviderCall,
    mut sender: tokio::sync::oneshot::Sender<LocalServiceCompletion>,
) {
    let receipt = tokio::select! {
        biased;
        () = call.budget_accounting().descendant_cancelled() => None,
        () = sender.closed() => None,
        receipt = &mut activation => Some(receipt),
    };
    let receipt = match receipt {
        Some(receipt) => receipt,
        None => {
            activation
                .interrupt_for_cleanup(ActivationTransportInterruption::Disconnected)
                .await
        }
    };
    let outcome = super::super::result::bounded(receipt.outcome, call.maximum_output_bytes());
    let _ = sender.send(LocalServiceCompletion {
        outcome,
        call,
        child,
    });
}

fn original_layout<F>(
    _: fn(
        ActivationHandle,
        ChildBudgetOwner,
        ProviderCall,
        tokio::sync::oneshot::Sender<LocalServiceCompletion>,
    ) -> F,
) -> (usize, usize) {
    (size_of::<F>(), align_of::<F>())
}

fn current_layout<F>(
    _: fn(
        ActivationHandle,
        ChildBudgetOwner,
        ProviderCall,
        DescendantCancellation,
        tokio::sync::oneshot::Sender<LocalServiceCompletion>,
    ) -> F,
) -> (usize, usize, usize, usize) {
    (
        size_of::<F>(),
        align_of::<F>(),
        size_of::<OwnedDriver<F>>(),
        align_of::<OwnedDriver<F>>(),
    )
}

#[test]
fn spawned_inline_wrapper_does_not_grow_the_original_task_payload() {
    let (old_bytes, old_align) = original_layout(original_driver);
    let (new_bytes, new_align, wrapper_bytes, wrapper_align) =
        current_layout(super::super::drive_child);
    eprintln!("original={old_bytes}/{old_align}, boxed_driver={new_bytes}/{new_align}, inline_wrapper={wrapper_bytes}/{wrapper_align}");
    assert!(wrapper_bytes <= old_bytes);
    assert!(wrapper_align <= old_align);
}
