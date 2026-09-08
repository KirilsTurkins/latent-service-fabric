use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::{Arc, Weak};
use std::task::{Context, Poll, Wake, Waker};

use latent_core::{PlatformErrorCode, ReleaseDigest};

use super::*;

fn release() -> ReleaseDigest {
    ReleaseDigest(format!("sha256:{}", "ab".repeat(32)))
}

#[test]
fn disabled_observation_records_nothing_even_if_enabled_during_that_job() {
    let observer = PreparationObserver::new(2);
    let job = observer.begin(&release());
    job.stage(PreparationStage::ComponentNew).complete();
    let disabled = observer.snapshot();
    assert!(!disabled.enabled);
    assert_eq!(disabled.revision, 0);
    assert_eq!(disabled.active_jobs, 0);
    assert!(disabled.running.is_empty());
    assert!(disabled.recent_stages.is_empty());
    assert!(disabled.stages.iter().all(|stage| stage.started == 0));
    observer.enable();
    let enabled_revision = observer.snapshot().revision;
    job.stage(PreparationStage::CacheAdoption).complete();
    job.complete();
    let after = observer.snapshot();
    assert!(after.enabled);
    assert_eq!(after.revision, enabled_revision);
    assert!(after.stages.iter().all(|stage| stage.started == 0));
    assert!(after.recent_stages.is_empty());
}

#[test]
fn success_failure_and_unwind_publish_balanced_stage_and_job_outcomes() {
    let observer = PreparationObserver::new(2);
    observer.enable();
    let success = observer.begin(&release());
    success.stage(PreparationStage::ComponentNew).complete();
    success.complete();
    let failed = observer.begin(&release());
    drop(failed.stage(PreparationStage::MetadataValidation));
    drop(failed);
    let unwind = std::panic::catch_unwind(|| {
        let job = observer.begin(&release());
        let _stage = job.stage(PreparationStage::CacheAdoption);
        panic!("controlled preparation failure");
    });
    assert!(unwind.is_err());
    let snapshot = observer.snapshot();
    assert_eq!(snapshot.active_jobs, 0);
    assert!(snapshot.running.is_empty());
    assert_eq!(snapshot.recent_stages.len(), 6);
    for (kind, started, completed, failed) in [
        (PreparationStage::WholeJob, 3, 1, 2),
        (PreparationStage::ComponentNew, 1, 1, 0),
        (PreparationStage::MetadataValidation, 1, 0, 1),
        (PreparationStage::CacheAdoption, 1, 0, 1),
    ] {
        let total = snapshot
            .stages
            .iter()
            .find(|total| total.stage == kind)
            .unwrap();
        assert_eq!(
            (total.started, total.completed, total.failed),
            (started, completed, failed)
        );
        assert_eq!(
            total.thread_cpu_samples + total.thread_cpu_unavailable,
            completed + failed
        );
    }
    for event in &snapshot.recent_stages {
        assert!(event.finished_nanos >= event.started_nanos);
        assert!(snapshot.observed_nanos >= event.finished_nanos);
        assert_eq!(event.component_digest, Some([0xab; 32]));
    }
}

#[test]
fn stage_ring_evicts_only_old_observations_and_keeps_complete_totals() {
    let observer = PreparationObserver::new(1);
    observer.enable();
    let maximum = observer.snapshot().maximum_stage_observations;
    let original_capacity = observer.inner.lock().observations.capacity();
    let count = maximum + 3;
    let job = observer.begin(&release());
    for _ in 0..count {
        job.stage(PreparationStage::ComponentNew).complete();
    }
    job.complete();
    let snapshot = observer.snapshot();
    assert_eq!(maximum, 256);
    assert_eq!(snapshot.recent_stages.len(), maximum);
    assert_eq!(snapshot.dropped_stage_observations, 4);
    assert_eq!(snapshot.recent_stages[0].sequence, 4);
    assert_eq!(
        snapshot.recent_stages.last().unwrap().sequence,
        count as u64
    );
    assert_eq!(
        snapshot.recent_stages.last().unwrap().stage,
        PreparationStage::WholeJob
    );
    assert!(snapshot
        .recent_stages
        .windows(2)
        .all(|pair| pair[1].sequence == pair[0].sequence + 1));
    let total = snapshot
        .stages
        .iter()
        .find(|total| total.stage == PreparationStage::ComponentNew)
        .unwrap();
    assert_eq!(total.started, count as u64);
    assert_eq!(total.completed, count as u64);
    assert_eq!(total.failed, 0);
    let retained = observer.inner.lock();
    assert_eq!(retained.observations.capacity(), original_capacity);
}

#[test]
fn running_entry_overflow_does_not_hide_live_job_count_or_corrupt_other_entries() {
    let observer = PreparationObserver::new(1);
    observer.enable();
    let first = observer.begin(&release());
    let second = observer.begin(&ReleaseDigest("untrusted-unbounded-label".into()));
    second.stage(PreparationStage::ComponentNew).complete();
    let full = observer.snapshot();
    assert_eq!(full.active_jobs, 2);
    assert_eq!(full.running.len(), 1);
    assert_eq!(full.running[0].component_digest, Some([0xab; 32]));
    assert_eq!(full.dropped_running_entries, 1);
    assert_eq!(full.recent_stages[0].component_digest, None);
    drop(first);
    let remaining = observer.snapshot();
    assert_eq!(remaining.active_jobs, 1);
    assert!(remaining.running.is_empty());
    second.complete();
    assert_eq!(observer.snapshot().active_jobs, 0);
    assert_eq!(
        PreparationObserver::new(0)
            .snapshot()
            .maximum_running_entries,
        1
    );
    assert_eq!(
        PreparationObserver::new(usize::MAX)
            .snapshot()
            .maximum_running_entries,
        1024
    );
}

struct Noop;
impl Wake for Noop {
    fn wake(self: Arc<Self>) {}
}

#[test]
fn only_one_pending_waiter_is_retained_and_drop_releases_its_slot() {
    let observer = PreparationObserver::new(1);
    let waker = Waker::from(Arc::new(Noop));
    let mut context = Context::from_waker(&waker);
    let mut first = observer.wait_for_change(0);
    let mut other = observer.wait_for_change(0);
    assert!(first.as_mut().poll(&mut context).is_pending());
    let Poll::Ready(Err(error)) = other.as_mut().poll(&mut context) else {
        panic!("second waiter must fail without replacing the first");
    };
    assert_eq!(error.code, PlatformErrorCode::Unavailable);
    assert!(error.retryable);
    assert_eq!(error.message, "preparation-observer-waiter-limit");
    drop(other);
    assert!(first.as_mut().poll(&mut context).is_pending());
    drop(first);
    let mut replacement = observer.wait_for_change(0);
    assert!(replacement.as_mut().poll(&mut context).is_pending());
    observer.enable();
    let Poll::Ready(Ok(revision)) = replacement.as_mut().poll(&mut context) else {
        panic!("registered waiter must observe enable");
    };
    assert_eq!(revision, observer.snapshot().revision);
    let mut already_changed = observer.wait_for_change(0);
    assert!(matches!(
        already_changed.as_mut().poll(&mut context),
        Poll::Ready(Ok(_))
    ));
}

#[test]
fn dropping_a_woken_waiter_cannot_remove_a_later_registration() {
    let observer = PreparationObserver::new(1);
    let waker = Waker::from(Arc::new(Noop));
    let mut context = Context::from_waker(&waker);
    let mut old = observer.wait_for_change(0);
    assert!(old.as_mut().poll(&mut context).is_pending());
    observer.enable();
    let revision = observer.snapshot().revision;
    let mut current = observer.wait_for_change(revision);
    assert!(current.as_mut().poll(&mut context).is_pending());
    drop(old);
    let mut competing = observer.wait_for_change(revision);
    assert!(matches!(
        competing.as_mut().poll(&mut context),
        Poll::Ready(Err(_))
    ));
    observer.begin(&release()).complete();
    assert!(matches!(
        current.as_mut().poll(&mut context),
        Poll::Ready(Ok(_))
    ));
}

#[derive(Default)]
struct WakeCounters {
    wakes: AtomicUsize,
    drops: AtomicUsize,
    locked_callbacks: AtomicUsize,
    snapshots: AtomicUsize,
}

struct Reentrant {
    inner: Weak<Inner>,
    counters: Arc<WakeCounters>,
}

impl Reentrant {
    fn inspect(&self) {
        let inner = self.inner.upgrade().unwrap();
        // Detect a held lock without deadlocking the test, then actually reenter
        // the public snapshot API when the callback is safe to execute.
        let unlocked = inner.state.try_lock().is_ok();
        if unlocked {
            let _ = PreparationObserver { inner }.snapshot();
            self.counters.snapshots.fetch_add(1, Ordering::Relaxed);
        } else {
            self.counters
                .locked_callbacks
                .fetch_add(1, Ordering::Relaxed);
        }
    }
}

impl Wake for Reentrant {
    fn wake(self: Arc<Self>) {
        self.counters.wakes.fetch_add(1, Ordering::Relaxed);
        self.inspect();
    }
}

impl Drop for Reentrant {
    fn drop(&mut self) {
        self.counters.drops.fetch_add(1, Ordering::Relaxed);
        self.inspect();
    }
}

fn reentrant_waker(observer: &PreparationObserver, counters: &Arc<WakeCounters>) -> Waker {
    Waker::from(Arc::new(Reentrant {
        inner: Arc::downgrade(&observer.inner),
        counters: Arc::clone(counters),
    }))
}

#[test]
fn replaced_and_deregistered_wakers_drop_outside_the_state_mutex() {
    let observer = PreparationObserver::new(1);
    let counters = Arc::new(WakeCounters::default());
    let mut waiter = observer.wait_for_change(0);
    for _ in 0..2 {
        let waker = reentrant_waker(&observer, &counters);
        assert!(waiter
            .as_mut()
            .poll(&mut Context::from_waker(&waker))
            .is_pending());
        drop(waker);
    }
    assert_eq!(counters.drops.load(Ordering::Relaxed), 1);
    drop(waiter);
    assert_eq!(counters.drops.load(Ordering::Relaxed), 2);
    assert_eq!(counters.wakes.load(Ordering::Relaxed), 0);
    assert_eq!(counters.snapshots.load(Ordering::Relaxed), 2);
    assert_eq!(counters.locked_callbacks.load(Ordering::Relaxed), 0);
}

#[test]
fn observation_notifications_can_reenter_without_holding_the_state_mutex() {
    let observer = PreparationObserver::new(1);
    let counters = Arc::new(WakeCounters::default());
    let waker = reentrant_waker(&observer, &counters);
    let mut waiter = observer.wait_for_change(0);
    assert!(waiter
        .as_mut()
        .poll(&mut Context::from_waker(&waker))
        .is_pending());
    drop(waker);
    observer.enable();
    assert_eq!(counters.wakes.load(Ordering::Relaxed), 1);
    assert_eq!(counters.drops.load(Ordering::Relaxed), 1);
    assert_eq!(counters.snapshots.load(Ordering::Relaxed), 2);
    assert_eq!(counters.locked_callbacks.load(Ordering::Relaxed), 0);
}

struct Panics;
impl Wake for Panics {
    fn wake(self: Arc<Self>) {
        panic!("controlled observer consumer panic");
    }
}

#[test]
fn consumer_wake_panic_cannot_abort_preparation_accounting() {
    let observer = PreparationObserver::new(1);
    observer.enable();
    let revision = observer.snapshot().revision;
    let waker = Waker::from(Arc::new(Panics));
    let mut waiter = observer.wait_for_change(revision);
    assert!(waiter
        .as_mut()
        .poll(&mut Context::from_waker(&waker))
        .is_pending());
    let job = observer.begin(&release());
    job.stage(PreparationStage::ComponentNew).complete();
    job.complete();
    assert!(matches!(
        waiter.as_mut().poll(&mut Context::from_waker(&waker)),
        Poll::Ready(Ok(_))
    ));
    let snapshot = observer.snapshot();
    assert_eq!(snapshot.active_jobs, 0);
    assert_eq!(snapshot.recent_stages.len(), 2);
    assert!(snapshot.recent_stages.iter().all(|stage| stage.succeeded));
}

fn task_stat(comm: &str, user: &str, system: &str, start: &str) -> String {
    // Linux fields 3..23: state, ten fields through cmajflt, utime/stime,
    // cutime/cstime/priority/nice/threads/itrealvalue, starttime, vsize.
    format!("57 ({comm}) S 1 2 3 4 5 6 7 8 9 10 {user} {system} 0 0 0 0 1 0 {start} 4096\n")
}

#[test]
fn linux_task_stat_parser_handles_comm_parentheses_and_exact_cpu_field_positions() {
    for comm in [
        "compiler",
        "worker (0))(",
        "worker ) with space\nand (parentheses)",
    ] {
        let sample = cpu::parse(&task_stat(comm, "123", "456", "789"), 42).unwrap();
        assert_eq!(
            sample.identity,
            PreparationThreadIdentity {
                process_id: 42,
                thread_id: 57,
                start_time_ticks: 789
            }
        );
        assert_eq!((sample.user_ticks, sample.system_ticks), (123, 456));
    }
}

#[test]
fn malformed_truncated_oversized_or_overflowing_cpu_records_are_unavailable() {
    for text in [
        "".to_owned(),
        "57 (missing closing delimiter".into(),
        "57 (short) S 0 0".into(),
        task_stat("negative", "-1", "0", "789"),
        task_stat("overflow", "18446744073709551616", "0", "789"),
        task_stat("overflow", "0", "0", "18446744073709551616"),
        task_stat("zero tid", "0", "0", "789").replacen("57 ", "0 ", 1),
        task_stat("tid overflow", "0", "0", "789").replacen("57 ", "4294967296 ", 1),
        "x".repeat(4097),
    ] {
        assert!(
            cpu::parse(&text, 42).is_none(),
            "accepted malformed fixture"
        );
    }
    assert!(cpu::parse(&task_stat("valid", "0", "0", "789"), 0).is_none());
}

#[test]
fn cpu_intervals_reject_task_migration_reuse_and_regressing_counters() {
    let before = cpu::parse(&task_stat("worker", "123", "456", "789"), 42).unwrap();
    let mut after = before;
    after.user_ticks += 2;
    after.system_ticks += 3;
    let valid = cpu::interval(Some(before), Some(after)).unwrap();
    assert_eq!(valid.before, before);
    assert_eq!(valid.after, after);
    assert!(
        cpu::interval(Some(before), Some(before)).is_some(),
        "zero tick delta is a valid quantized reading"
    );
    for changed in 0..5 {
        let mut invalid = after;
        match changed {
            0 => invalid.identity.process_id += 1,
            1 => invalid.identity.thread_id += 1,
            2 => invalid.identity.start_time_ticks += 1,
            3 => invalid.user_ticks = before.user_ticks - 1,
            4 => invalid.system_ticks = before.system_ticks - 1,
            _ => unreachable!(),
        }
        assert!(cpu::interval(Some(before), Some(invalid)).is_none());
    }
    assert!(cpu::interval(None, Some(after)).is_none());
    assert!(cpu::interval(Some(before), None).is_none());
}
