use super::support::*;
use crate::compiler::{CompilationResult, CompilerPool, JobControl, PreparationWait};
use latent_artifacts::{ArtifactRepository, OwnedArtifactPreparationSource};
use std::sync::{mpsc, Arc};
use std::time::Duration;

fn blocked_controlled(
    pool: &CompilerPool<u8>,
    waiter: &PreparationWait<u8>,
    source: OwnedArtifactPreparationSource,
) -> (JobControl, mpsc::Sender<()>) {
    waiter.reserve_documents(64).unwrap();
    let control = waiter.control().unwrap();
    let worker_control = control.clone();
    let observer = pool.core.observer.clone();
    let (entered_send, entered) = mpsc::channel();
    let (release, released) = mpsc::channel();
    waiter
        .start(move |reservation| {
            Box::new(move |_| {
                let _source = source; // Retain the actual catalog/root owner until work retires.
                let observation = observer.begin(&latent_core::ReleaseDigest(format!(
                    "sha256:{}",
                    "a".repeat(64)
                )));
                entered_send.send(()).unwrap();
                released.recv_timeout(Duration::from_secs(5)).unwrap();
                if worker_control.is_stopped() {
                    return Err(crate::compiler::capacity_error("compiler-job-abandoned"));
                }
                Ok(CompilationResult {
                    runtime: Arc::new(7),
                    reservation: Some(reservation),
                    observation,
                })
            })
        })
        .unwrap();
    entered.recv_timeout(Duration::from_secs(5)).unwrap();
    (control, release)
}

fn held(pool: &CompilerPool<u8>) {
    assert_eq!(pool.observer().snapshot().running_jobs, 1);
    assert_eq!(pool.observer().snapshot().reserved_document_bytes, 64);
    assert_eq!(pool.core.cache.snapshot().preparing, 1);
}

fn retired(pool: &CompilerPool<u8>) {
    // Quiescence is after the worker's final Job/control drop, unlike a
    // transient zero-gauge snapshot observed just before that final drop.
    complete(pool.quiesce()).unwrap();
    idle(pool);
    let snapshot = pool.observer().snapshot();
    assert_eq!(snapshot.running_jobs, 0);
    assert_eq!(snapshot.reserved_document_bytes, 0);
    assert_eq!(snapshot.waiting_callers, 0);
    assert_eq!(snapshot.ready_preparations, 0);
    assert_eq!(snapshot.ready_metadata_bytes, 0);
    assert_eq!(snapshot.ready_compiled_image_bytes, 0);
    assert_eq!(pool.core.cache.snapshot().preparing, 0);
    assert_eq!(pool.core.cache.snapshot().preparing_source_bytes, 0);
    assert_eq!(pool.core.cache.snapshot().preparing_metadata_bytes, 0);
}

#[test]
fn one_cancelled_waiter_keeps_shared_worker_control_and_original_window_live() {
    let (_directory, repository, identity) = source();
    let pool = pool(&config());
    let (first, _) = waiting(&pool, "controlled", Some(identity.clone()));
    let (control, release) = blocked_controlled(
        &pool,
        &first,
        repository.owned_preparation_source().unwrap(),
    );
    let (second, owner) = waiting(&pool, "controlled", Some(identity));
    assert!(!owner);
    let joined = second.control().unwrap();
    assert_eq!(control.created(), joined.created());
    drop(first);
    assert!(!control.is_stopped());
    assert!(!joined.is_stopped());
    held(&pool);
    release.send(()).unwrap();
    drop(complete(second).unwrap());
    retired(&pool);
    assert_eq!(pool.observer().snapshot().jobs_started, 1);
    assert_eq!(pool.observer().snapshot().jobs_completed, 1);
}

#[test]
fn last_waiter_stop_retains_worker_source_and_all_reservations_until_retirement() {
    let (directory, repository, identity) = source();
    let pool = pool(&config());
    let (first, _) = waiting(&pool, "cancel-controlled", Some(identity.clone()));
    let (control, release) = blocked_controlled(
        &pool,
        &first,
        repository.owned_preparation_source().unwrap(),
    );
    let (second, _) = waiting(&pool, "cancel-controlled", Some(identity));
    drop(first);
    assert!(!control.is_stopped());
    drop(second);
    assert!(control.is_stopped());
    held(&pool);
    assert!(
        latent_artifacts::DirectoryArtifactRepository::open(&directory.0, Default::default())
            .is_err()
    );
    release.send(()).unwrap();
    retired(&pool);
    drop(directory.open());
    assert_eq!(control.owners(), 1);
    assert_eq!(pool.core.cache.snapshot().entries, 0);
}

#[test]
fn pool_shutdown_signals_worker_before_releasing_owned_source_and_capacity() {
    let (directory, repository, identity) = source();
    let pool = pool(&config());
    let (waiter, _) = waiting(&pool, "stop-controlled", Some(identity));
    let (control, release) = blocked_controlled(
        &pool,
        &waiter,
        repository.owned_preparation_source().unwrap(),
    );
    let shutdown = pool.quiesce();
    assert!(control.is_stopped());
    assert!(complete(waiter).is_err());
    held(&pool);
    assert!(
        latent_artifacts::DirectoryArtifactRepository::open(&directory.0, Default::default())
            .is_err()
    );
    release.send(()).unwrap();
    complete(shutdown).unwrap();
    retired(&pool);
    drop(directory.open());
    assert_eq!(control.owners(), 1);
    assert_eq!(pool.core.cache.snapshot().entries, 0);
}

#[test]
fn worker_control_population_is_bounded_by_jobs_and_reclaimed_on_unstarted_drop() {
    let mut configuration = config();
    configuration.compiler_workers = Some(1);
    configuration.maximum_concurrent_preparations = 2;
    let pool = pool(&configuration);
    let (first, _) = waiting(&pool, "first-control", None);
    let (second, _) = waiting(&pool, "second-control", None);
    let first_control = first.control().unwrap();
    let second_control = second.control().unwrap();
    assert_eq!((first_control.owners(), second_control.owners()), (2, 2));
    assert!(pool.acquire(input("over-job-limit", None)).is_err());
    assert_eq!(pool.core.lock().jobs.len(), 2);
    drop(first);
    drop(second);
    assert!(first_control.is_stopped());
    assert!(second_control.is_stopped());
    assert_eq!((first_control.owners(), second_control.owners()), (1, 1));
    retired(&pool);
}
