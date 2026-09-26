use std::sync::mpsc;
use std::task::{Context, Waker};
use std::time::Duration;

use latent_artifacts::ArtifactRepository;
use latent_core::PlatformErrorCode;
use latent_executor::ExecutionBackend;

use super::fixture::{Fence, Fixture, Timer};
use crate::compiler::{Acquisition, Admission};

#[tokio::test(flavor = "current_thread")]
async fn busy_compiler_worker_fails_once_without_replaying_owned_preparation() {
    let f = Fixture::new().await;
    let pool = f.backend.shared.compiler.as_ref().unwrap();
    let Acquisition::Waiting {
        future: blocker,
        owner: true,
    } = pool
        .acquire(Admission {
            identity: None,
            handle: "readiness-fence-test-blocker".into(),
            source_bytes: 1,
            metadata_bytes: 1,
            document_bytes: 0,
        })
        .unwrap()
    else {
        panic!("fresh blocker")
    };
    let (entered_send, entered) = mpsc::sync_channel(1);
    let (release, released) = mpsc::sync_channel(1);
    blocker
        .start(move |reservation| {
            Box::new(move |_| {
                let _reservation = reservation;
                entered_send.send(()).unwrap();
                let _ = released.recv_timeout(Duration::from_secs(5));
                Err(crate::containment::platform_error(
                    PlatformErrorCode::Unavailable,
                    "test-blocker-complete",
                    false,
                ))
            })
        })
        .unwrap();
    entered.recv_timeout(Duration::from_secs(5)).unwrap();
    let mut pending = f
        .backend
        .prepare_ready_from_repository(f.repository.clone(), f.key.clone());
    assert!(pending
        .as_mut()
        .poll(&mut Context::from_waker(Waker::noop()))
        .is_pending());
    assert_eq!(f.backend.compiler_snapshot().queued_jobs, 1);
    let fence = Fence::hold(&f.eligibility);
    release.send(()).unwrap();
    let error = tokio::time::timeout(Duration::from_secs(2), pending)
        .await
        .unwrap()
        .unwrap_err();
    assert!(super::super::wait::busy(&error));
    assert!(blocker.await.is_err());
    f.factory.quiesce_compiler().await.unwrap();
    let compiler = f.backend.compiler_snapshot();
    assert_eq!(compiler.jobs_started, 2);
    assert_eq!(compiler.jobs_failed, 2);
    assert_eq!(
        f.backend.preparation_activity_snapshot().repository_fetches,
        1
    );
    assert_eq!(
        f.backend.preparation_activity_snapshot().component_hashes,
        0
    );
    f.idle();
    fence.release();
}

#[tokio::test(flavor = "current_thread")]
async fn real_fence_opt_in_worker_waits_then_compiles_and_fetches_exactly_once() {
    let f = Fixture::new().await;
    f.backend.preparation_observer().enable();
    let pool = f.backend.shared.compiler.as_ref().unwrap();
    let (blocker, release) = block_worker(pool);
    let before = f.repository.verification_snapshot();
    let mut pending = f.backend.prepare_ready_from_repository_with_wait(
        f.repository.clone(),
        f.key.clone(),
        &Timer,
    );
    assert!(pending
        .as_mut()
        .poll(&mut Context::from_waker(Waker::noop()))
        .is_pending());
    assert_eq!(f.backend.compiler_snapshot().queued_jobs, 1);
    let fence = Fence::hold(&f.eligibility);
    release.send(()).unwrap();
    assert!(blocker.await.is_err());
    // The actual compiler worker must reach the failing real grant read.
    wait_running(&f).await;
    assert!(pending
        .as_mut()
        .poll(&mut Context::from_waker(Waker::noop()))
        .is_pending());
    assert_eq!(f.repository.verification_snapshot(), before);
    fence.release();
    let ready = tokio::time::timeout(Duration::from_secs(5), pending)
        .await
        .unwrap()
        .unwrap();
    drop(ready);
    f.factory.quiesce_compiler().await.unwrap();
    let compiler = f.backend.compiler_snapshot();
    assert_eq!(
        (
            compiler.jobs_started,
            compiler.jobs_completed,
            compiler.jobs_failed
        ),
        (2, 1, 1)
    );
    let after = f.repository.verification_snapshot();
    assert_eq!(after.full_fetch_attempts - before.full_fetch_attempts, 1);
    assert_eq!(
        after.component_verification_attempts - before.component_verification_attempts,
        1
    );
    assert_eq!(
        f.backend
            .preparation_activity_snapshot()
            .metadata_fingerprints,
        1
    );
    let observation = f.backend.preparation_observer().snapshot();
    for stage in [
        crate::PreparationStage::ComponentNew,
        crate::PreparationStage::SurfaceLink,
    ] {
        let total = observation
            .stages
            .iter()
            .find(|value| value.stage == stage)
            .unwrap();
        assert_eq!((total.started, total.completed, total.failed), (1, 1, 0));
    }
    f.idle();
}

#[tokio::test(flavor = "current_thread")]
async fn worker_real_fence_wait_rejects_expiry_without_fetch() {
    let f = Fixture::new().await;
    let (blocker, release) = block_worker(f.backend.shared.compiler.as_ref().unwrap());
    let mut pending = f.backend.prepare_ready_from_repository_with_wait(
        f.repository.clone(),
        f.key.clone(),
        &Timer,
    );
    assert!(pending
        .as_mut()
        .poll(&mut Context::from_waker(Waker::noop()))
        .is_pending());
    let fence = Fence::hold(&f.eligibility);
    release.send(()).unwrap();
    assert!(blocker.await.is_err());
    wait_running(&f).await;
    f.clock.0.fetch_add(5, std::sync::atomic::Ordering::SeqCst);
    fence.release();
    let error = tokio::time::timeout(Duration::from_secs(2), pending)
        .await
        .unwrap()
        .unwrap_err();
    assert_eq!(
        error.details[0].fields.get("reason").map(String::as_str),
        Some("admission-clock-lease-uncovered")
    );
    f.factory.quiesce_compiler().await.unwrap();
    assert_eq!(f.repository.verification_snapshot().full_fetch_attempts, 0);
    f.idle();
}

#[tokio::test(flavor = "current_thread")]
async fn queued_worker_cannot_upgrade_original_grant_after_catalog_reverification() {
    let f = Fixture::new().await;
    let (blocker, release) = block_worker(f.backend.shared.compiler.as_ref().unwrap());
    let mut pending = f.backend.prepare_ready_from_repository_with_wait(
        f.repository.clone(),
        f.key.clone(),
        &Timer,
    );
    assert!(pending
        .as_mut()
        .poll(&mut Context::from_waker(Waker::noop()))
        .is_pending());
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
            &latent_core::TenantId("tests".into()),
            &f.key.release,
            f.key.publication.as_ref(),
        )
        .unwrap()
        .unwrap();
    f.repository.reverify_publication(&publication).unwrap();
    let before = f.repository.verification_snapshot();
    release.send(()).unwrap();
    assert!(blocker.await.is_err());
    let error = tokio::time::timeout(Duration::from_secs(2), pending)
        .await
        .unwrap()
        .unwrap_err();
    assert!(!super::super::wait::busy(&error));
    assert!(f.eligibility.check_current().is_err());
    f.factory.quiesce_compiler().await.unwrap();
    assert_eq!(f.repository.verification_snapshot(), before);
    f.idle();
}

fn block_worker(
    pool: &crate::compiler::CompilerPool<crate::backend::PreparedRuntime>,
) -> (
    crate::compiler::PreparationWait<crate::backend::PreparedRuntime>,
    mpsc::SyncSender<()>,
) {
    let Acquisition::Waiting {
        future,
        owner: true,
    } = pool
        .acquire(Admission {
            identity: None,
            handle: "worker-currentness-blocker".into(),
            source_bytes: 1,
            metadata_bytes: 1,
            document_bytes: 0,
        })
        .unwrap()
    else {
        panic!("fresh blocker")
    };
    let (entered_send, entered) = mpsc::sync_channel(1);
    let (release, released) = mpsc::sync_channel(1);
    future
        .start(move |reservation| {
            Box::new(move |_| {
                let _reservation = reservation;
                entered_send.send(()).unwrap();
                released.recv_timeout(Duration::from_secs(10)).unwrap();
                Err(crate::containment::platform_error(
                    PlatformErrorCode::Unavailable,
                    "test-blocker-complete",
                    false,
                ))
            })
        })
        .unwrap();
    entered.recv_timeout(Duration::from_secs(5)).unwrap();
    (future, release)
}

async fn wait_running(f: &Fixture) {
    tokio::time::timeout(Duration::from_secs(2), async {
        while f
            .backend
            .shared
            .compiler
            .as_ref()
            .unwrap()
            .currentness_waits()
            == 0
        {
            tokio::time::sleep(Duration::from_millis(1)).await;
        }
    })
    .await
    .unwrap();
    // Test-only observation proves the worker actually saw the real busy read.
    assert_eq!(f.backend.compiler_snapshot().running_jobs, 1);
}

#[tokio::test(flavor = "current_thread")]
async fn dropping_fenced_worker_wait_retires_job_and_source_before_fence_release() {
    let f = Fixture::new().await;
    let (blocker, release) = block_worker(f.backend.shared.compiler.as_ref().unwrap());
    let mut pending = f.backend.prepare_ready_from_repository_with_wait(
        f.repository.clone(),
        f.key.clone(),
        &Timer,
    );
    assert!(pending
        .as_mut()
        .poll(&mut Context::from_waker(Waker::noop()))
        .is_pending());
    let fence = Fence::hold(&f.eligibility);
    release.send(()).unwrap();
    assert!(blocker.await.is_err());
    wait_running(&f).await;
    drop(pending); // Same owner-drop boundary as the original node stage.
    tokio::time::timeout(Duration::from_secs(2), f.factory.quiesce_compiler())
        .await
        .unwrap()
        .unwrap();
    assert_eq!(f.backend.compiler_snapshot().jobs_started, 2);
    assert_eq!(f.repository.verification_snapshot().full_fetch_attempts, 0);
    f.idle();
    fence.release();
}

#[tokio::test(flavor = "current_thread")]
async fn worker_window_consumed_in_queue_does_not_restart_at_first_busy_read() {
    let f = Fixture::new().await;
    let (blocker, release) = block_worker(f.backend.shared.compiler.as_ref().unwrap());
    let mut pending = f.backend.prepare_ready_from_repository_with_wait(
        f.repository.clone(),
        f.key.clone(),
        &Timer,
    );
    assert!(pending
        .as_mut()
        .poll(&mut Context::from_waker(Waker::noop()))
        .is_pending());
    // Real elapsed time, not the caller timer's paused/virtual domain.
    tokio::time::sleep(Duration::from_millis(5_020)).await;
    let fence = Fence::hold(&f.eligibility);
    release.send(()).unwrap();
    assert!(blocker.await.is_err());
    let error = tokio::time::timeout(Duration::from_secs(1), pending)
        .await
        .unwrap()
        .unwrap_err();
    assert!(super::super::wait::busy(&error));
    f.factory.quiesce_compiler().await.unwrap();
    assert_eq!(f.backend.compiler_snapshot().jobs_started, 2);
    assert_eq!(f.repository.verification_snapshot().full_fetch_attempts, 0);
    f.idle();
    fence.release();
}
