use std::sync::{mpsc, Arc};
use std::time::Duration;

use latent_artifacts::{
    ArtifactPreparationReadLimits, ArtifactRepository, DirectoryArtifactRepository,
    DirectoryArtifactRepositoryConfig,
};
use latent_core::ReleaseDigest;

use super::support::*;
use crate::compiler::{Acquisition, CompilationResult, CompilerPool};
use crate::{PreparationObserver, WasmtimeConfig};

#[test]
fn cancelled_running_job_retains_source_lock_and_reservations_then_discards_late_result() {
    let (directory, repository, identity) = source();
    let source = Arc::clone(&repository).owned_preparation_source().unwrap();
    let bounds = source.read_bounds(&identity.key.release).unwrap();
    let pool = pool(&config());
    let mut admission = input("owned", Some(identity.clone()));
    admission.source_bytes = bounds.component_bytes as usize;
    let Acquisition::Waiting {
        future,
        owner: true,
    } = pool.acquire(admission).unwrap()
    else {
        panic!("first owned job")
    };
    future.reserve_documents(64).unwrap();
    let (started_send, started) = mpsc::channel();
    let (release, released) = mpsc::channel();
    let observer = pool.core.observer.clone();
    let digest = identity.key.release.clone();
    future
        .start(move |reservation| {
            Box::new(move |_queue| {
                let observation = observer.begin(&digest);
                let artifact = source
                    .fetch_blocking(
                        &digest,
                        ArtifactPreparationReadLimits {
                            maximum_component_bytes: bounds.component_bytes as usize,
                            maximum_metadata_document_bytes: bounds.maximum_metadata_document_bytes,
                            maximum_manifest_document_bytes: bounds.maximum_manifest_document_bytes,
                        },
                    )
                    .unwrap();
                started_send.send(()).unwrap();
                released.recv_timeout(Duration::from_secs(5)).unwrap();
                drop(artifact);
                drop(source);
                Ok(CompilationResult {
                    runtime: Arc::new(7),
                    reservation: Some(reservation),
                    observation,
                })
            })
        })
        .unwrap();
    started.recv_timeout(Duration::from_secs(5)).unwrap();
    drop(repository);
    drop(future);
    assert!(DirectoryArtifactRepository::open(
        &directory.0,
        DirectoryArtifactRepositoryConfig::default()
    )
    .is_err());
    assert_eq!(pool.core.cache.snapshot().preparing, 1);
    assert_eq!(pool.observer().snapshot().reserved_document_bytes, 64);
    assert!(pool.acquire(input("owned", Some(identity))).is_err());
    release.send(()).unwrap();
    idle(&pool);
    let reopened = directory.open();
    drop(reopened);
    let snapshot = pool.observer().snapshot();
    assert_eq!(
        (
            snapshot.ready_preparations,
            snapshot.reserved_document_bytes,
            snapshot.discarded_results
        ),
        (0, 0, 1)
    );
    assert_eq!(pool.core.cache.snapshot().preparing, 0);
    assert_eq!(pool.core.cache.snapshot().entries, 0);
}

#[test]
fn queued_last_waiter_drop_destroys_input_without_running_it() {
    let mut configuration = config();
    configuration.compiler_workers = Some(1);
    configuration.maximum_concurrent_preparations = 2;
    let pool = pool(&configuration);
    let (running, _) = waiting(&pool, "running", None);
    let (started, release) = blocked(&pool, &running);
    started.recv_timeout(Duration::from_secs(5)).unwrap();
    let (queued, _) = waiting(&pool, "queued", None);
    let (queued_started, _) = blocked(&pool, &queued);
    drop(queued);
    assert!(queued_started
        .recv_timeout(Duration::from_millis(10))
        .is_err());
    assert_eq!(pool.core.cache.snapshot().preparing, 1);
    release.send(()).unwrap();
    drop(complete(running).unwrap());
    idle(&pool);
    assert_eq!(pool.observer().snapshot().jobs_started, 1);
}

#[test]
fn unexpected_finish_panic_fails_waiters_closes_admission_and_releases_dead_worker() {
    fn panic_cost(_: &u8) -> (usize, usize) {
        panic!("test unexpected finishing panic")
    }
    let configuration: WasmtimeConfig = config();
    let cache = Arc::new(crate::cache::PreparedCache::new(configuration.cache_limits()).unwrap());
    let mut pool = CompilerPool::new(
        &configuration,
        cache,
        PreparationObserver::new(4),
        panic_cost,
    )
    .unwrap();
    let (future, _) = waiting(&pool, "panic", None);
    let observer = pool.core.observer.clone();
    future
        .start(move |reservation| {
            Box::new(move |_queue| {
                Ok(CompilationResult {
                    runtime: Arc::new(9),
                    reservation: Some(reservation),
                    observation: observer
                        .begin(&ReleaseDigest(format!("sha256:{}", "c".repeat(64)))),
                })
            })
        })
        .unwrap();
    assert!(complete(future).is_err());
    complete(pool.quiesce()).unwrap();
    let _ = pool.stop_and_join();
    assert!(pool.observer().last_work_completed_at().is_some());
    let snapshot = pool.observer().snapshot();
    assert!(snapshot.failed);
    assert!(!snapshot.accepting);
    assert_eq!(
        (
            snapshot.assigned_jobs,
            snapshot.queued_jobs,
            snapshot.ready_preparations
        ),
        (0, 0, 0)
    );
    assert_eq!(pool.core.cache.snapshot().preparing, 0);
    assert!(pool.acquire(input("later", None)).is_err());
}
