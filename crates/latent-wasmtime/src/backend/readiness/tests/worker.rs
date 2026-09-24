use std::sync::mpsc;
use std::task::{Context, Waker};
use std::time::Duration;

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
