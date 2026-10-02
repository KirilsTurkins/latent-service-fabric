use std::sync::atomic::Ordering;
use std::task::{Context, Waker};
use std::time::Duration;

use latent_artifacts::ArtifactRepository;
use latent_core::{BoxFuture, PlatformErrorCode};
use latent_executor::{ExecutionBackend, PreparationReadWait};
use latent_policy::supply_chain::SupplyChainPolicy;

use super::fixture::{Fence, Fixture, Timer};

#[tokio::test(flavor = "current_thread", start_paused = true)]
async fn readiness_inspection_refuses_expired_original_admission_without_refresh() {
    let f = Fixture::new().await;
    let ready = f.ready().await;
    f.clock.0.fetch_add(5, Ordering::SeqCst);
    let error = f.backend.inspect_ready(ready).unwrap_err();
    // The authority's five-second conservative clock lease is now uncovered;
    // policy currentness is unavailable, so the original ready grant is refused.
    assert_eq!(error.code, PlatformErrorCode::Unavailable);
    assert_eq!(error.message, "admission-clock-lease-uncovered");
    assert_eq!(f.backend.resource_snapshot().stores_created, 0);
    assert_eq!(f.backend.active_instance_reservations(), 0);
    f.idle();
}

#[tokio::test(flavor = "current_thread", start_paused = true)]
async fn readiness_inspection_uses_actual_profile_and_retires_without_a_guest_store() {
    let f = Fixture::new().await;
    let ready = f.ready().await;
    let key = ready.descriptor().key.clone();
    let jobs = f.backend.compiler_snapshot().jobs_started;
    let report = f.backend.inspect_ready(ready).unwrap();
    assert_eq!(report.key, key);
    assert_eq!(
        report.profile,
        latent_core::diagnostic::DiagnosticProfile::WasmtimeServiceValuesV1
    );
    assert!(report.function_count > 0);
    assert!(report.hostcall_fuel > 0);
    assert!(report.maximum_lifted_bytes > 0);
    assert_eq!(f.backend.resource_snapshot().stores_created, 0);
    assert_eq!(f.backend.active_instance_reservations(), 0);
    assert_eq!(f.backend.compiler_snapshot().jobs_started, jobs);
    f.idle();
}

#[tokio::test(flavor = "current_thread", start_paused = true)]
async fn readiness_inspection_refuses_another_factory_and_releases_original_pin() {
    let first = Fixture::new().await;
    let other = Fixture::new().await;
    let ready = first.ready().await;
    assert_eq!(
        other.backend.inspect_ready(ready).unwrap_err().code,
        PlatformErrorCode::InvalidArgument
    );
    assert_eq!(first.backend.resource_snapshot().stores_created, 0);
    assert_eq!(other.backend.resource_snapshot().stores_created, 0);
    first.idle();
    other.idle();
}

#[tokio::test(flavor = "current_thread", start_paused = true)]
async fn busy_materialization_retains_exact_readiness_and_materializes_once_after_release() {
    let f = Fixture::new().await;
    let ready = f.ready().await;
    let descriptor = ready.descriptor().clone();
    let imports = ready.imports().to_vec();
    let activity = f.backend.preparation_activity_snapshot();
    let jobs = f.backend.compiler_snapshot().jobs_started;
    let verification = f.repository.verification_snapshot();
    let fence = Fence::hold(&f.eligibility);
    let mut pending = f.backend.materialize_ready_with_wait(ready, &Timer);
    assert!(pending
        .as_mut()
        .poll(&mut Context::from_waker(Waker::noop()))
        .is_pending());
    assert_eq!(f.backend.compiler_snapshot().ready_preparations, 1);
    assert!(f.backend.compiler_snapshot().ready_compiled_image_bytes > 0);
    assert_eq!(f.backend.active_instance_reservations(), 0);
    assert_eq!(f.backend.resource_snapshot().stores_created, 0);
    fence.release();
    let activation = pending.await.unwrap();
    assert_eq!(activation.prepared.descriptor(), &descriptor);
    assert_eq!(activation.imports, imports);
    assert_eq!(f.backend.active_instance_reservations(), 1);
    assert_eq!(f.backend.compiler_snapshot().ready_preparations, 0);
    assert_eq!(f.backend.compiler_snapshot().jobs_started, jobs);
    assert_eq!(f.backend.preparation_activity_snapshot(), activity);
    assert_eq!(f.repository.verification_snapshot(), verification);
    drop(activation);
    f.idle();
}

#[tokio::test(flavor = "current_thread", start_paused = true)]
async fn dropping_unpolled_or_busy_materialization_reclaims_original_ready_pin() {
    for poll_once in [false, true] {
        let f = Fixture::new().await;
        let ready = f.ready().await;
        let jobs = f.backend.compiler_snapshot().jobs_started;
        let fence = Fence::hold(&f.eligibility);
        let mut pending = f.backend.materialize_ready_with_wait(ready, &Timer);
        if poll_once {
            assert!(pending
                .as_mut()
                .poll(&mut Context::from_waker(Waker::noop()))
                .is_pending());
        }
        assert_eq!(f.backend.compiler_snapshot().ready_preparations, 1);
        assert_eq!(f.backend.active_instance_reservations(), 0);
        drop(pending);
        f.idle();
        fence.release();
        tokio::time::advance(Duration::from_secs(6)).await;
        assert_eq!(f.backend.compiler_snapshot().jobs_started, jobs);
        f.idle();
    }
}

#[tokio::test(flavor = "current_thread", start_paused = true)]
async fn synchronous_materialization_remains_immediate_and_fail_closed_on_busy() {
    let f = Fixture::new().await;
    let ready = f.ready().await;
    let fence = Fence::hold(&f.eligibility);
    let error = f.backend.materialize_ready(ready).unwrap_err();
    assert!(super::super::wait::busy(&error));
    f.idle();
    fence.release();
}

#[tokio::test(flavor = "current_thread", start_paused = true)]
async fn materialization_busy_window_expires_without_instances_or_renewal() {
    let f = Fixture::new().await;
    let ready = f.ready().await;
    let original_time = f.clock.0.load(Ordering::SeqCst);
    let fence = Fence::hold(&f.eligibility);
    let mut pending = f.backend.materialize_ready_with_wait(ready, &Timer);
    assert!(pending
        .as_mut()
        .poll(&mut Context::from_waker(Waker::noop()))
        .is_pending());
    tokio::time::advance(Duration::from_secs(5)).await;
    let error = pending.await.unwrap_err();
    assert!(super::super::wait::busy(&error));
    assert_eq!(f.clock.0.load(Ordering::SeqCst), original_time);
    f.idle();
    fence.release();
}

#[tokio::test(flavor = "current_thread", start_paused = true)]
async fn materialization_does_not_upgrade_original_grant_after_policy_reverification() {
    let f = Fixture::new().await;
    let ready = f.ready().await;
    let fence = Fence::hold(&f.eligibility);
    let mut pending = f.backend.materialize_ready_with_wait(ready, &Timer);
    assert!(pending
        .as_mut()
        .poll(&mut Context::from_waker(Waker::noop()))
        .is_pending());
    fence.release();
    let mut policy = f.policy.clone();
    policy["generation"] = serde_json::json!(2);
    f.authority
        .replace_policy(
            SupplyChainPolicy::from_json(&serde_json::to_vec(&policy).unwrap()).unwrap(),
        )
        .unwrap();
    let publication = f
        .repository
        .select_execution_publication(
            &latent_core::TenantId("tests".into()),
            &f.key.release,
            f.key.publication.as_ref(),
        )
        .unwrap()
        .unwrap();
    f.repository.reverify_publication(&publication).unwrap();
    let error = pending.await.unwrap_err();
    assert_eq!(error.code, PlatformErrorCode::PermissionDenied);
    assert!(!super::super::wait::busy(&error));
    assert!(f.eligibility.check_current().is_err());
    f.idle();
}

#[tokio::test(flavor = "current_thread", start_paused = true)]
async fn materialization_clock_expiry_is_terminal_without_renewing_or_waiting_again() {
    let f = Fixture::new().await;
    let ready = f.ready().await;
    let fence = Fence::hold(&f.eligibility);
    let mut pending = f.backend.materialize_ready_with_wait(ready, &Timer);
    assert!(pending
        .as_mut()
        .poll(&mut Context::from_waker(Waker::noop()))
        .is_pending());
    f.clock.0.fetch_add(5, Ordering::SeqCst);
    fence.release();
    let before = tokio::time::Instant::now();
    let error = pending.await.unwrap_err();
    assert_eq!(
        error.details[0].fields.get("reason").map(String::as_str),
        Some("admission-clock-lease-uncovered")
    );
    assert_eq!(
        tokio::time::Instant::now() - before,
        Duration::from_millis(10)
    );
    f.idle();
}

struct NeverWait;
impl PreparationReadWait for NeverWait {
    fn now(&self) -> std::time::Instant {
        panic!("foreign ownership cannot enter a read window")
    }
    fn wait_until(&self, _: std::time::Instant) -> BoxFuture<'_, ()> {
        panic!("foreign ownership cannot wait")
    }
}

#[tokio::test(flavor = "current_thread", start_paused = true)]
async fn foreign_readiness_is_rejected_before_any_currentness_wait() {
    let f = Fixture::new().await;
    let other = Fixture::new().await;
    let ready = f.ready().await;
    let error = other
        .backend
        .materialize_ready_with_wait(ready, &NeverWait)
        .await
        .unwrap_err();
    assert_eq!(error.code, PlatformErrorCode::InvalidArgument);
    f.idle();
    other.idle();
}
