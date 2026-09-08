use std::time::Duration;

use super::support::*;
use crate::compiler::Acquisition;

#[test]
fn workers_queue_and_waiter_limit_leave_existing_warm_entries_available() {
    let mut configuration = config();
    configuration.maximum_preparation_waiters = 4;
    configuration.maximum_waiters_per_preparation = 4;
    let pool = pool(&configuration);
    cached(&pool, "warm");
    let mut waits = Vec::new();
    let mut releases = Vec::new();
    for index in 0..4 {
        let (future, owner) = waiting(&pool, &format!("cold-{index}"), None);
        assert!(owner);
        let (started, release) = blocked(&pool, &future);
        if index < 2 {
            started.recv_timeout(Duration::from_secs(5)).unwrap();
        }
        waits.push(future);
        releases.push(release);
    }
    let snapshot = pool.observer().snapshot();
    assert_eq!(
        (
            snapshot.running_jobs,
            snapshot.queued_jobs,
            snapshot.waiting_callers
        ),
        (2, 2, 4)
    );
    assert!(pool.acquire(input("overflow", None)).is_err());
    let warm = ready(pool.acquire(input("warm", None)).unwrap());
    assert_eq!(*warm.runtime, 3);
    drop(warm);
    for release in releases {
        release.send(()).unwrap();
    }
    for wait in waits {
        drop(complete(wait).unwrap());
    }
    idle(&pool);
    assert_eq!(pool.observer().snapshot().ready_preparations, 0);
    assert_eq!(pool.core.cache.snapshot().preparing, 0);
}

#[test]
fn same_key_waiters_share_one_owned_compilation_and_survive_creator_cancellation_after_start() {
    let (_directory, _repository, identity) = source();
    let pool = pool(&config());
    let (first, owner) = waiting(&pool, "shared", Some(identity.clone()));
    assert!(owner);
    let (started, release) = blocked(&pool, &first);
    started.recv_timeout(Duration::from_secs(5)).unwrap();
    let mut remaining = Vec::new();
    for _ in 0..7 {
        let (future, owner) = waiting(&pool, "shared", Some(identity.clone()));
        assert!(!owner);
        remaining.push(future);
    }
    drop(first);
    assert_eq!(pool.core.cache.snapshot().preparing, 1);
    release.send(()).unwrap();
    for waiter in remaining {
        drop(complete(waiter).unwrap());
    }
    idle(&pool);
    let snapshot = pool.observer().snapshot();
    assert_eq!(snapshot.jobs_started, 1);
    assert_eq!(snapshot.coalesced_waiters, 7);
    assert_eq!(snapshot.cancelled_waiters, 1);
    assert_eq!(
        (snapshot.ready_preparations, snapshot.waiting_callers),
        (0, 0)
    );
}

#[test]
fn failed_creator_setup_promptly_fails_followers_without_starting_a_worker() {
    let (_directory, _repository, identity) = source();
    let pool = pool(&config());
    let (creator, _) = waiting(&pool, "setup", Some(identity.clone()));
    let (mut follower, owner) = waiting(&pool, "setup", Some(identity));
    assert!(!owner);
    pending(&mut follower);
    assert!(creator.reserve_documents(1025).is_err());
    drop(creator);
    assert!(complete(follower).is_err());
    idle(&pool);
    assert_eq!(pool.core.cache.snapshot().preparing, 0);
    let snapshot = pool.observer().snapshot();
    assert_eq!(
        (
            snapshot.jobs_started,
            snapshot.ready_preparations,
            snapshot.reserved_document_bytes
        ),
        (0, 0, 0)
    );
}

#[test]
fn coalesced_results_respect_ready_image_bytes_even_after_cache_eviction() {
    let (_directory, _repository, identity) = source();
    let mut configuration = config();
    configuration.prepared_cache_maximum_compiled_image_bytes = 16;
    let pool = pool(&configuration);
    let (first, _) = waiting(&pool, "shared", Some(identity.clone()));
    let (started, release) = blocked(&pool, &first);
    started.recv_timeout(Duration::from_secs(5)).unwrap();
    let (second, _) = waiting(&pool, "shared", Some(identity));
    release.send(()).unwrap();
    let first = complete(first);
    let second = complete(second);
    assert_ne!(first.is_ok(), second.is_ok());
    let pin = first.or(second).unwrap();
    assert!(pool.core.cache.remove_matching("shared", |_| true));
    assert_eq!(pool.observer().snapshot().ready_compiled_image_bytes, 16);
    drop(pin);
    idle(&pool);
    assert_eq!(pool.observer().snapshot().ready_compiled_image_bytes, 0);
    assert_eq!(pool.observer().snapshot().ready_metadata_bytes, 0);
    assert!(matches!(
        pool.acquire(input("new", None)).unwrap(),
        Acquisition::Waiting { owner: true, .. }
    ));
}

#[test]
fn ordinary_job_errors_and_panics_fan_out_then_unrelated_work_recovers() {
    use latent_core::PlatformErrorCode;
    use std::sync::mpsc;
    let (_directory, _repository, identity) = source();
    let pool = pool(&config());
    for panic_job in [false, true] {
        let (first, _) = waiting(&pool, "failure", Some(identity.clone()));
        let (started_send, started) = mpsc::channel();
        let (release, released) = mpsc::channel();
        first
            .start(move |reservation| {
                Box::new(move |_queue| {
                    let _owned_reservation = reservation;
                    started_send.send(()).unwrap();
                    released.recv_timeout(Duration::from_secs(5)).unwrap();
                    assert!(!panic_job, "controlled ordinary task panic");
                    Err(crate::containment::platform_error(
                        PlatformErrorCode::CorruptArtifact,
                        "controlled-task-error",
                        false,
                    ))
                })
            })
            .unwrap();
        started.recv_timeout(Duration::from_secs(5)).unwrap();
        let mut followers = vec![first];
        for _ in 0..7 {
            let (follower, owner) = waiting(&pool, "failure", Some(identity.clone()));
            assert!(!owner);
            followers.push(follower);
        }
        release.send(()).unwrap();
        for follower in followers {
            let error = complete(follower)
                .err()
                .expect("every follower sees the failure");
            assert_eq!(
                error.code,
                if panic_job {
                    PlatformErrorCode::Unavailable
                } else {
                    PlatformErrorCode::CorruptArtifact
                }
            );
        }
        idle(&pool);
        assert_eq!(pool.core.cache.snapshot().preparing, 0);
        assert_eq!(pool.observer().snapshot().ready_preparations, 0);
        assert!(pool.observer().snapshot().accepting);
        assert!(!pool.observer().snapshot().failed);
        let (healthy, _) = waiting(
            &pool,
            if panic_job {
                "after-panic"
            } else {
                "after-error"
            },
            None,
        );
        let (started, release) = blocked(&pool, &healthy);
        started.recv_timeout(Duration::from_secs(5)).unwrap();
        release.send(()).unwrap();
        let recovered = complete(healthy).unwrap();
        assert_eq!(*recovered.runtime, 7);
        drop(recovered);
        idle(&pool);
    }
    let snapshot = pool.observer().snapshot();
    assert_eq!((snapshot.jobs_failed, snapshot.jobs_completed), (2, 2));
    assert_eq!(snapshot.coalesced_waiters, 14);
}
