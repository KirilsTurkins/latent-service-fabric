use super::*;
use crate::capability::{MutationRequest, PolicyStoreLimits, RecordKind};
use latent_artifacts::{DirectoryArtifactRepository, DirectoryArtifactRepositoryConfig};
use std::{sync::mpsc, time::Duration};

#[test]
fn cancelled_waiter_keeps_queued_or_running_work_charged_until_actual_completion() {
    let root = tempfile::TempDir::new().unwrap();
    let catalog = DirectoryArtifactRepository::open(
        root.path().join("catalog"),
        DirectoryArtifactRepositoryConfig::default(),
    )
    .unwrap();
    let store = Arc::new(
        PolicyStore::open(
            &root.path().join("policies"),
            PolicyStoreLimits::default(),
            catalog.lifecycle_authority(),
        )
        .unwrap(),
    );
    let runtime = tokio::runtime::Builder::new_current_thread()
        .enable_all()
        .max_blocking_threads(1)
        .build()
        .unwrap();
    let handle = PolicyControlHandle::new(store.clone(), runtime.handle().clone(), 1).unwrap();
    let (entered, entry) = mpsc::channel();
    let (release, resume) = mpsc::channel();
    let bytes = serde_json::to_vec(&crate::capability::tests::policy()).unwrap();
    let future = handle.reserve().unwrap().run(move |store| {
        entered.send(()).unwrap();
        resume.recv_timeout(Duration::from_secs(5)).unwrap();
        store.mutate(
            MutationRequest {
                tenant: "a",
                actor: "operator",
                id: "p",
                kind: RecordKind::Policy,
                operation_id: "late",
                expected_revision: 0,
                document: Some(&bytes),
            },
            Instant::now() + Duration::from_secs(5),
            |_| Ok(()),
        )
    });
    entry.recv_timeout(Duration::from_secs(5)).unwrap();
    drop(future);
    assert_eq!(handle.active_jobs(), 1);
    assert!(handle.reserve().is_err());
    release.send(()).unwrap();
    runtime.block_on(async {
        tokio::time::timeout(Duration::from_secs(5), async {
            while handle.active_jobs() != 0 {
                tokio::task::yield_now().await;
            }
        })
        .await
        .unwrap();
    });
    assert!(store
        .outcome("a", "late", Instant::now() + Duration::from_secs(5))
        .unwrap()
        .value()
        .is_some());
    assert!(runtime.block_on(handle.shutdown(Instant::now() + Duration::from_secs(5))));
    assert!(handle.reserve().is_err());
    assert_eq!(handle.active_jobs(), 0);
    runtime.shutdown_timeout(Duration::from_secs(5));
}

#[test]
fn shutdown_timeout_reports_owned_work_and_rejects_new_submissions() {
    let root = tempfile::TempDir::new().unwrap();
    let catalog = DirectoryArtifactRepository::open(
        root.path().join("catalog"),
        DirectoryArtifactRepositoryConfig::default(),
    )
    .unwrap();
    let store = Arc::new(
        PolicyStore::open(
            &root.path().join("policies"),
            PolicyStoreLimits::default(),
            catalog.lifecycle_authority(),
        )
        .unwrap(),
    );
    let runtime = tokio::runtime::Builder::new_current_thread()
        .enable_all()
        .max_blocking_threads(1)
        .build()
        .unwrap();
    let handle = PolicyControlHandle::new(store, runtime.handle().clone(), 1).unwrap();
    let (entered, entry) = mpsc::channel();
    let (release, resume) = mpsc::channel();
    let future = handle.reserve().unwrap().run(move |_| {
        entered.send(()).unwrap();
        resume.recv_timeout(Duration::from_secs(5)).unwrap();
        Ok(())
    });
    entry.recv_timeout(Duration::from_secs(5)).unwrap();
    assert!(!runtime.block_on(handle.shutdown(Instant::now())));
    assert_eq!(handle.active_jobs(), 1);
    assert!(handle.reserve().is_err());
    release.send(()).unwrap();
    runtime.block_on(future).unwrap();
    assert!(runtime.block_on(handle.shutdown(Instant::now() + Duration::from_secs(5))));
    runtime.shutdown_timeout(Duration::from_secs(5));
}
