mod fixture;
mod owners;
mod worker;

use std::future::Future;
use std::sync::{atomic::Ordering, Arc};
use std::task::{Context, Waker};
use std::time::Duration;

use latent_artifacts::ArtifactRepository;
use latent_executor::ExecutionBackend;

use fixture::{Fence, Fixture, Timer};

#[tokio::test(flavor = "current_thread", start_paused = true)]
async fn real_fence_warm_readiness_waits_without_fetching_or_starting_another_job() {
    let f = Fixture::new().await;
    drop(f.ready().await);
    f.idle();
    let activity = f.backend.preparation_activity_snapshot();
    let compiler = f.backend.compiler_snapshot();
    let reads = f.repository.verification_snapshot();
    let fence = Fence::hold(&f.eligibility);
    let mut pending = f.backend.prepare_ready_from_repository_with_wait(
        f.repository.clone(),
        f.key.clone(),
        &Timer,
    );
    assert!(pending
        .as_mut()
        .poll(&mut Context::from_waker(Waker::noop()))
        .is_pending());
    assert_eq!(
        f.backend.compiler_snapshot().jobs_started,
        compiler.jobs_started
    );
    assert_eq!(
        f.backend.preparation_activity_snapshot().repository_fetches,
        activity.repository_fetches
    );
    assert_eq!(f.backend.resource_snapshot().stores_created, 0);
    fence.release();
    let ready = pending.await.unwrap();
    assert_eq!(f.backend.compiler_snapshot().ready_preparations, 1);
    assert_eq!(
        f.backend.compiler_snapshot().jobs_started,
        compiler.jobs_started
    );
    assert_eq!(
        f.backend.preparation_activity_snapshot().authenticated_hits,
        activity.authenticated_hits + 1
    );
    assert_eq!(
        f.backend.preparation_activity_snapshot().repository_fetches,
        activity.repository_fetches
    );
    assert_eq!(f.repository.verification_snapshot(), reads);
    drop(ready);
    f.idle();
}

#[tokio::test(flavor = "current_thread", start_paused = true)]
async fn real_fence_pending_readiness_drops_cleanly_and_original_entry_still_fails_closed() {
    let f = Fixture::new().await;
    drop(f.ready().await);
    let jobs = f.backend.compiler_snapshot().jobs_started;
    let fence = Fence::hold(&f.eligibility);
    let mut original = f
        .backend
        .prepare_ready_from_repository(f.repository.clone(), f.key.clone());
    let std::task::Poll::Ready(Err(error)) = original
        .as_mut()
        .poll(&mut Context::from_waker(Waker::noop()))
    else {
        panic!("original API must remain nonblocking")
    };
    assert!(super::wait::busy(&error));
    drop(original);
    let mut pending = f.backend.prepare_ready_from_repository_with_wait(
        f.repository.clone(),
        f.key.clone(),
        &Timer,
    );
    assert!(pending
        .as_mut()
        .poll(&mut Context::from_waker(Waker::noop()))
        .is_pending());
    drop(pending); // The node's original stage cancellation/deadline drops this owner.
    tokio::time::advance(Duration::from_secs(6)).await;
    assert_eq!(f.backend.compiler_snapshot().jobs_started, jobs);
    f.idle();
    fence.release();
}

#[tokio::test(flavor = "current_thread", start_paused = true)]
async fn later_source_read_wait_cannot_upgrade_original_grant_after_catalog_reverification() {
    let mut f = Fixture::new().await;
    let source = Arc::clone(&f.repository)
        .owned_preparation_source()
        .unwrap();
    let original = source
        .execution_eligibility_selected(&f.key.release, f.key.publication.as_ref())
        .unwrap();
    source
        .identity_selected(&f.key.release, f.key.publication.as_ref())
        .unwrap();
    let window = super::wait::Window::new(Some(&Timer));
    let fence = Fence::hold(&f.eligibility);
    let key = f.key.clone();
    let mut bounds = Box::pin(
        window.check(|| source.read_bounds_selected(&key.release, key.publication.as_ref())),
    );
    assert!(bounds
        .as_mut()
        .poll(&mut Context::from_waker(Waker::noop()))
        .is_pending());
    fence.release();
    f.replace_policy();
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
    bounds.await.unwrap(); // The read may now observe fresh catalog evidence.
    let error = window
        .check(|| {
            f.backend.shared.preparation_context.check_eligibility(
                original.as_ref(),
                &f.key.release,
                f.key.publication.as_ref(),
            )
        })
        .await
        .unwrap_err();
    assert!(!super::wait::busy(&error));
    assert!(f.eligibility.check_current().is_err());
    f.idle();
    assert_eq!(f.backend.compiler_snapshot().jobs_started, 0);
}

#[tokio::test(flavor = "current_thread", start_paused = true)]
async fn expiry_during_real_fence_wait_is_not_retried_or_renewed() {
    let f = Fixture::new().await;
    let fence = Fence::hold(&f.eligibility);
    let mut pending = f.backend.prepare_ready_from_repository_with_wait(
        f.repository.clone(),
        f.key.clone(),
        &Timer,
    );
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
    assert_eq!(f.backend.compiler_snapshot().jobs_started, 0);
}
