//! Exercise the real guarded activation-start boundary, not a synthetic error.

use std::sync::{
    atomic::{AtomicBool, Ordering},
    Arc,
};
use std::task::{Context, Waker};
use std::time::{Duration, Instant};

use super::fixture::{Fence, Fixture, Timer};
use crate::WasmtimeHostServices;
use latent_artifacts::ArtifactRepository;
use latent_core::{
    ActivationClock, ActivationId, CapabilityId, ClockSample, PlatformErrorCode, TenantId,
};
use latent_executor::{
    BoundImport, ExecutionBackend, ExecutionCancellation, ExecutionCleanup, ExecutionRequest,
    GuestInterruptionKind, GuestOutcome, PreparedActivation,
};

#[path = "../../../host/accounting/tests/support.rs"]
mod input;

struct Clock;
impl ActivationClock for Clock {
    fn sample(&self) -> ClockSample {
        ClockSample::new(9000, self.monotonic_now())
    }
    fn monotonic_now(&self) -> Instant {
        tokio::time::Instant::now().into_std()
    }
}
struct Cancellation {
    id: ActivationId,
    cancelled: AtomicBool,
}
impl ExecutionCancellation for Cancellation {
    fn activation_id(&self) -> &ActivationId {
        &self.id
    }
    fn is_cancelled(&self) -> bool {
        self.cancelled.load(Ordering::SeqCst)
    }
    fn reason(&self) -> Option<String> {
        None
    }
}
fn services(wait: bool) -> WasmtimeHostServices {
    WasmtimeHostServices {
        clock: Arc::new(Clock),
        currentness_read_wait: wait
            .then(|| Arc::new(Timer) as Arc<dyn latent_executor::PreparationReadWait>),
        ..Default::default()
    }
}
fn request(active: &PreparedActivation) -> (ExecutionRequest, Cancellation) {
    let mut request = input::request();
    request.prepared = active.prepared.descriptor().clone();
    request.activation.target.tenant = TenantId("tests".into());
    request.activation.principal.tenant = Some(TenantId("tests".into()));
    request.activation.target.contract.0 = "tests:packaging/api@1.0.0".into();
    request.activation.target.function.0 = "inspect".into();
    request.activation.input = br#"[{"count":1,"outcome":{"ok":{"case":"empty"}}}]"#.to_vec();
    request.activation.deadline_unix_millis = None;
    request.budget.cpu_fuel = 1_000_000;
    request.budget.memory_bytes = 4 * 1024 * 1024;
    request.budget.log_bytes = 0;
    request.budget.wall_time_limit_millis = None;
    request.activation.budget = request.budget.clone();
    request.cell.maximum_memory_bytes = request.budget.memory_bytes;
    request.imports = active
        .imports
        .iter()
        .map(|id| BoundImport {
            capability: CapabilityId(id.0.clone()),
            contract: id.0.clone(),
            opaque_handle: "test-clock".into(),
        })
        .collect();
    let cancel = Cancellation {
        id: request.activation.activation_id.clone(),
        cancelled: AtomicBool::new(false),
    };
    (request, cancel)
}

#[tokio::test(flavor = "current_thread", start_paused = true)]
async fn busy_activation_start_retains_original_owner_and_executes_guest_once() {
    let f = Fixture::with_services(services(true)).await;
    let active = f.backend.materialize_ready(f.ready().await).unwrap();
    let (request, cancel) = request(&active);
    let activity = f.backend.preparation_activity_snapshot();
    let jobs = f.backend.compiler_snapshot().jobs_started;
    let reads = f.repository.verification_snapshot();
    let fence = Fence::hold(&f.eligibility);
    let mut pending = f
        .backend
        .invoke_prepared_contained(request, active.prepared, &cancel);
    assert!(pending
        .as_mut()
        .poll(&mut Context::from_waker(Waker::noop()))
        .is_pending());
    assert_eq!(f.backend.active_instance_reservations(), 1);
    assert_eq!(f.backend.resource_snapshot().stores_created, 0);
    fence.release();
    let report = pending.await;
    assert_eq!(report.cleanup, ExecutionCleanup::Reusable);
    let GuestOutcome::Returned { output, .. } = report.outcome.unwrap() else {
        panic!("guest must execute")
    };
    assert_eq!(output, b"[7]");
    assert_eq!(f.backend.resource_snapshot().stores_created, 1);
    assert_eq!(f.backend.active_instance_reservations(), 0);
    assert_eq!(f.backend.compiler_snapshot().jobs_started, jobs);
    assert_eq!(f.backend.preparation_activity_snapshot(), activity);
    assert_eq!(f.repository.verification_snapshot(), reads);
}

#[tokio::test(flavor = "current_thread", start_paused = true)]
async fn unpolled_and_busy_invocation_drop_reclaims_the_materialized_owner_without_guest_work() {
    for poll in [false, true] {
        let f = Fixture::with_services(services(true)).await;
        let active = f.backend.materialize_ready(f.ready().await).unwrap();
        let (request, cancel) = request(&active);
        let fence = Fence::hold(&f.eligibility);
        let mut pending = f
            .backend
            .invoke_prepared_contained(request, active.prepared, &cancel);
        if poll {
            assert!(pending
                .as_mut()
                .poll(&mut Context::from_waker(Waker::noop()))
                .is_pending());
        }
        drop(pending);
        f.idle();
        fence.release();
        tokio::time::advance(Duration::from_secs(6)).await;
        f.idle();
    }
}

#[tokio::test(flavor = "current_thread", start_paused = true)]
async fn timerless_activation_start_remains_immediate_and_fail_closed() {
    let f = Fixture::with_services(services(false)).await;
    let active = f.backend.materialize_ready(f.ready().await).unwrap();
    let (request, cancel) = request(&active);
    let fence = Fence::hold(&f.eligibility);
    let report = f
        .backend
        .invoke_prepared_contained(request, active.prepared, &cancel)
        .await;
    assert_eq!(report.cleanup, ExecutionCleanup::Reusable);
    assert!(super::super::wait::busy(&report.outcome.unwrap_err()));
    f.idle();
    fence.release();
}

#[tokio::test(flavor = "current_thread", start_paused = true)]
async fn activation_start_wait_observes_original_cancellation_and_deadline_before_guest_execution()
{
    for cancelled in [true, false] {
        let f = Fixture::with_services(services(true)).await;
        let active = f.backend.materialize_ready(f.ready().await).unwrap();
        let (mut request, cancel) = request(&active);
        request.budget.wall_time_limit_millis = Some(20);
        request.activation.budget = request.budget.clone();
        let fence = Fence::hold(&f.eligibility);
        let mut pending = f
            .backend
            .invoke_prepared_contained(request, active.prepared, &cancel);
        assert!(pending
            .as_mut()
            .poll(&mut Context::from_waker(Waker::noop()))
            .is_pending());
        if cancelled {
            cancel.cancelled.store(true, Ordering::SeqCst);
        }
        tokio::time::advance(Duration::from_millis(20)).await;
        let report = pending.await;
        assert_eq!(report.cleanup, ExecutionCleanup::Reusable);
        let GuestOutcome::Interrupted {
            kind, consumption, ..
        } = report.outcome.unwrap()
        else {
            panic!("stop must precede guest")
        };
        assert_eq!(
            kind,
            if cancelled {
                GuestInterruptionKind::Cancelled
            } else {
                GuestInterruptionKind::DeadlineExceeded
            }
        );
        assert_eq!(consumption.cpu_fuel, 0);
        assert_eq!(consumption.peak_memory_bytes, 0);
        f.idle();
        fence.release();
    }
}

#[tokio::test(flavor = "current_thread", start_paused = true)]
async fn activation_start_busy_window_expires_without_renewing_or_reexecuting() {
    let f = Fixture::with_services(services(true)).await;
    let active = f.backend.materialize_ready(f.ready().await).unwrap();
    let (request, cancel) = request(&active);
    let fence = Fence::hold(&f.eligibility);
    let mut pending = f
        .backend
        .invoke_prepared_contained(request, active.prepared, &cancel);
    assert!(pending
        .as_mut()
        .poll(&mut Context::from_waker(Waker::noop()))
        .is_pending());
    tokio::time::advance(Duration::from_secs(5)).await;
    let report = pending.await;
    assert_eq!(report.cleanup, ExecutionCleanup::Reusable);
    assert!(super::super::wait::busy(&report.outcome.unwrap_err()));
    f.idle();
    fence.release();
}

#[tokio::test(flavor = "current_thread", start_paused = true)]
async fn activation_start_wait_keeps_original_grant_after_reverification_and_expiry() {
    for reverify in [true, false] {
        let f = Fixture::with_services(services(true)).await;
        let active = f.backend.materialize_ready(f.ready().await).unwrap();
        let (request, cancel) = request(&active);
        let fence = Fence::hold(&f.eligibility);
        let mut pending = f
            .backend
            .invoke_prepared_contained(request, active.prepared, &cancel);
        assert!(pending
            .as_mut()
            .poll(&mut Context::from_waker(Waker::noop()))
            .is_pending());
        fence.release();
        if reverify {
            let mut policy = f.policy.clone();
            policy["generation"] = serde_json::json!(2);
            f.authority
                .replace_policy(
                    latent_policy::supply_chain::SupplyChainPolicy::from_json(
                        &serde_json::to_vec(&policy).unwrap(),
                    )
                    .unwrap(),
                )
                .unwrap();
            let publication = f
                .repository
                .select_execution_publication(
                    &TenantId("tests".into()),
                    &f.key.release,
                    f.key.publication.as_ref(),
                )
                .unwrap()
                .unwrap();
            f.repository.reverify_publication(&publication).unwrap();
        } else {
            f.clock.0.fetch_add(5, Ordering::SeqCst);
        }
        let report = pending.await;
        assert_eq!(report.cleanup, ExecutionCleanup::Reusable);
        let error = report.outcome.unwrap_err();
        if reverify {
            assert_eq!(error.code, PlatformErrorCode::PermissionDenied);
        } else {
            assert_eq!(
                error.details[0].fields.get("reason").map(String::as_str),
                Some("admission-clock-lease-uncovered")
            );
        }
        assert!(!super::super::wait::busy(&error));
        f.idle();
    }
}

#[tokio::test(flavor = "current_thread", start_paused = true)]
async fn foreign_or_mismatched_invocation_owner_is_rejected_before_waiting() {
    let f = Fixture::with_services(services(true)).await;
    let other = Fixture::with_services(services(true)).await;
    for foreign in [true, false] {
        let active = f.backend.materialize_ready(f.ready().await).unwrap();
        let (mut request, cancel) = request(&active);
        if !foreign {
            request.prepared.opaque_handle.push_str("-changed");
        }
        let fence = Fence::hold(&f.eligibility);
        let backend = if foreign { &other.backend } else { &f.backend };
        let report = backend
            .invoke_prepared_contained(request, active.prepared, &cancel)
            .await;
        assert_eq!(report.cleanup, ExecutionCleanup::Reusable);
        assert_eq!(
            report.outcome.unwrap_err().code,
            PlatformErrorCode::InvalidArgument
        );
        f.idle();
        other.idle();
        fence.release();
    }
}
