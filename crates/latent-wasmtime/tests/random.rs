//! Real guest/cell execution. No statistical claim about randomness quality.
#![cfg(target_os = "linux")]
#[path = "random/audit.rs"]
mod audit;
#[path = "random/component.rs"]
mod component;
#[path = "random/fixture.rs"]
#[allow(dead_code)]
mod fixture;
#[path = "random/ownership.rs"]
mod ownership;
#[path = "generic_backend/support.rs"]
#[allow(dead_code)]
mod support;
use fixture::*;
use latent_capabilities::broker::random::{RandomError, RandomLimits, TestEntropy};
use std::sync::{
    atomic::{AtomicBool, AtomicUsize},
    Mutex,
};

#[derive(Default)]
struct Source {
    calls: AtomicUsize,
    fail: AtomicBool,
    hook: Mutex<Option<Box<dyn FnOnce() + Send>>>,
}
impl TestEntropy for Source {
    fn fill(&self, bytes: &mut [u8]) -> Result<(), RandomError> {
        self.calls.fetch_add(1, Ordering::AcqRel);
        bytes.fill(42);
        if let Some(hook) = self.hook.lock().unwrap().take() {
            hook();
        }
        if self.fail.load(Ordering::Acquire) {
            Err(RandomError::Unavailable)
        } else {
            Ok(())
        }
    }
}
const INVALID: u64 = 1 << 63;
const EXHAUSTED: u64 = INVALID + 1;
const UNAVAILABLE: u64 = INVALID + 2;
const SCALAR: u64 = u64::from_le_bytes([42; 8]);
fn marker(length: u64) -> u64 {
    (42 << 32) | length
}
async fn invoke(f: &Fixture, mode: u32, length: u32, count: u32) -> u64 {
    let (request, control) = f.request("same-id-same-cell", mode, length, count);
    returned(f, request, control).await
}
async fn returned(
    f: &Fixture,
    request: latent_executor::ExecutionRequest,
    control: Control,
) -> u64 {
    let report = f.backend.invoke_contained(request, &control).await;
    let outcome = report.outcome.unwrap();
    let GuestOutcome::Returned {
        output,
        consumption,
        ..
    } = outcome
    else {
        panic!("guest result: {outcome:?}")
    };
    assert_eq!(report.cleanup, ExecutionCleanup::Reusable);
    let finalized = control
        .budget
        .finalize_at(Some(&consumption), Instant::now());
    assert!(finalized.violation().is_none());
    assert_eq!(consumption.outbound_requests, 0);
    assert_eq!(consumption.effect_count, 0);
    f.idle();
    serde_json::from_slice::<Vec<String>>(&output).unwrap()[0]
        .parse()
        .unwrap()
}

#[tokio::test]
async fn both_os_methods_execute_on_a_reused_cell_and_have_no_dormant_entropy_owner() {
    let f = Fixture::new(None, RandomLimits::default()).await;
    for _ in 0..3 {
        assert_eq!(invoke(&f, 0, 0, 1).await, 0);
        assert_eq!(invoke(&f, 0, 4096, 1).await & 0xffff_ffff, 4096);
        let _ = invoke(&f, 1, 0, 1).await;
    }
    assert_eq!(f.provider.snapshot().generated_bytes, 3 * (4096 + 8));
    assert_eq!(f.backend.cache_snapshot().entries, 1);
}
#[tokio::test]
async fn zero_max_overflow_and_shared_aggregate_return_exact_typed_results() {
    let source = Arc::new(Source::default());
    let f = Fixture::new(
        Some(source.clone()),
        RandomLimits {
            maximum_bytes_per_call: 8,
            maximum_bytes_per_activation: 16,
        },
    )
    .await;
    assert_eq!(invoke(&f, 0, 0, 1).await, 0);
    assert_eq!(source.calls.load(Ordering::Acquire), 0);
    assert_eq!(invoke(&f, 0, 9, 1).await, INVALID);
    assert_eq!(invoke(&f, 0, u32::MAX, 1).await, INVALID);
    assert_eq!(source.calls.load(Ordering::Acquire), 0);
    assert_eq!(invoke(&f, 0, 8, 2).await, marker(8));
    assert_eq!(invoke(&f, 2, 8, 2).await, SCALAR);
    assert_eq!(invoke(&f, 2, 8, 3).await, EXHAUSTED);
    assert_eq!(source.calls.load(Ordering::Acquire), 6);
    // A new activation on the same prepared cell gets a fresh shared allowance.
    assert_eq!(invoke(&f, 1, 0, 2).await, SCALAR);
    assert_eq!(f.provider.snapshot().budget_exhaustions, 1);
}
#[tokio::test]
async fn denied_principal_and_retired_provider_never_access_entropy() {
    let source = Arc::new(Source::default());
    let f = Fixture::new(Some(source.clone()), RandomLimits::default()).await;
    let (mut request, control) = f.request("no-grant", 0, 8, 1);
    request.activation.principal.subject = "ungranted-subject".into();
    assert_eq!(returned(&f, request, control).await, UNAVAILABLE);
    f.provider.retire();
    let (request, control) = f.request("retired", 1, 0, 1);
    let report = f.backend.invoke_contained(request, &control).await;
    assert!(!matches!(report.outcome, Ok(GuestOutcome::Returned { .. })));
    assert_eq!(source.calls.load(Ordering::Acquire), 0);
    f.idle();
}
#[tokio::test]
async fn failed_entropy_never_returns_partial_bytes_and_does_not_refund_attempted_bytes() {
    let source = Arc::new(Source::default());
    source.fail.store(true, Ordering::Release);
    let f = Fixture::new(Some(source.clone()), RandomLimits::default()).await;
    assert_eq!(invoke(&f, 0, 8, 1).await, UNAVAILABLE);
    assert_eq!(invoke(&f, 1, 0, 1).await, UNAVAILABLE);
    assert_eq!(f.provider.snapshot().generated_bytes, 0);
    source.fail.store(false, Ordering::Release);
    assert_eq!(invoke(&f, 0, 8, 1).await, marker(8));
    assert_eq!(f.provider.snapshot().unavailable, 2);
}
#[tokio::test]
async fn cancellation_before_and_after_entropy_prevents_delivery_and_reclaims_the_store() {
    let source = Arc::new(Source::default());
    let f = Fixture::new(Some(source.clone()), RandomLimits::default()).await;
    let (request, control) = f.request("already-cancelled", 0, 8, 2);
    control.probe.0.store(true, Ordering::Release);
    let report = f.backend.invoke_contained(request, &control).await;
    assert!(!matches!(report.outcome, Ok(GuestOutcome::Returned { .. })));
    assert_eq!(source.calls.load(Ordering::Acquire), 0);
    f.idle();
    for mode in 0..=1 {
        let (request, control) = f.request("cancel-source", mode, 8, 2);
        let probe = control.probe.clone();
        *source.hook.lock().unwrap() =
            Some(Box::new(move || probe.0.store(true, Ordering::Release)));
        let report = f.backend.invoke_contained(request, &control).await;
        assert!(!matches!(report.outcome, Ok(GuestOutcome::Returned { .. })));
        assert_eq!(report.cleanup, ExecutionCleanup::Reusable);
        assert_eq!(source.calls.load(Ordering::Acquire), mode as usize + 1);
        f.idle();
    }
    assert_eq!(invoke(&f, 0, 8, 1).await, marker(8));
}
#[tokio::test]
async fn revocation_after_one_guest_call_denies_the_next_without_reusing_cached_authority() {
    let source = Arc::new(Source::default());
    let f = Fixture::new(Some(source.clone()), RandomLimits::default()).await;
    let policies = f.policies.clone();
    *source.hook.lock().unwrap() = Some(Box::new(move || revoke(&policies)));
    assert_eq!(invoke(&f, 0, 8, 2).await, UNAVAILABLE);
    assert_eq!(source.calls.load(Ordering::Acquire), 1);
}
