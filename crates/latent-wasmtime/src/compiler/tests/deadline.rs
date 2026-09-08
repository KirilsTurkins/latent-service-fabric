use std::time::{Duration, Instant};

use super::support::*;

#[test]
fn idle_retirement_after_cutoff_does_not_claim_late_native_work() {
    for register_unstarted in [false, true] {
        let mut pool = pool(&config());
        let observer = pool.observer();
        let cutoff = Instant::now();
        let unstarted = register_unstarted.then(|| waiting(&pool, "unstarted", None).0);
        complete(pool.quiesce()).unwrap();
        if let Some(future) = unstarted {
            assert!(complete(future).is_err());
        }
        assert!(Instant::now() >= cutoff);
        assert!(observer.last_work_completed_at().is_none());
        assert_eq!(observer.snapshot().jobs_started, 0);
        assert_eq!(pool.core.cache.snapshot().preparing, 0);
        pool.stop_and_join().unwrap();
        assert!(observer.last_work_completed_at().is_none());
        assert_eq!(observer.snapshot().workers_joined, 2);
    }
}

#[test]
fn abandoned_native_job_finishing_after_cutoff_remains_late_when_observed_later() {
    let mut pool = pool(&config());
    let observer = pool.observer();
    let (future, _) = waiting(&pool, "late", None);
    let (started, release) = blocked(&pool, &future);
    started.recv_timeout(Duration::from_secs(5)).unwrap();
    let cutoff = Instant::now();
    let quiescence = pool.quiesce();
    assert!(complete(future).is_err());
    assert_eq!(pool.core.cache.snapshot().preparing, 1);
    release.send(()).unwrap();
    complete(quiescence).unwrap();
    // Read after completion, as transport/sampler cleanup can do in the node.
    assert_eq!(observer.snapshot().running_jobs, 0);
    assert_eq!(pool.core.cache.snapshot().preparing, 0);
    let completed = observer.last_work_completed_at().unwrap();
    assert!(completed > cutoff);
    assert!(completed <= Instant::now());
    assert_eq!(observer.snapshot().jobs_abandoned, 1);
    pool.stop_and_join().unwrap();
    assert_eq!(observer.last_work_completed_at(), Some(completed));
}

#[test]
fn native_work_within_original_grace_stays_timely_through_idle_retirement() {
    let mut pool = pool(&config());
    let observer = pool.observer();
    let (future, _) = waiting(&pool, "timely", None);
    let (started, release) = blocked(&pool, &future);
    started.recv_timeout(Duration::from_secs(5)).unwrap();
    let deadline = Instant::now() + Duration::from_secs(5);
    release.send(()).unwrap();
    drop(complete(future).unwrap());
    complete(pool.quiesce()).unwrap();
    let completed = observer.last_work_completed_at().unwrap();
    assert!(completed <= deadline);
    assert_eq!(observer.snapshot().jobs_completed, 1);
    pool.stop_and_join().unwrap();
    assert_eq!(observer.last_work_completed_at(), Some(completed));
}

#[test]
fn completion_observation_uses_the_latest_job_time_even_if_updates_reorder() {
    let observer = crate::CompilerObserver::disabled();
    let earlier = Instant::now();
    let later = earlier + Duration::from_millis(1);
    observer.record_work_completed_at(later);
    observer.record_work_completed_at(earlier);
    assert_eq!(observer.last_work_completed_at(), Some(later));
}
