use super::*;
use latent_artifacts::AdmissionAuthority;
use latent_core::TenantId;
use std::sync::atomic::{AtomicU64, AtomicUsize};
use std::sync::{mpsc, Arc, Mutex};
use std::time::{Duration, Instant};

const WATCHDOG: Duration = Duration::from_secs(10);

struct Pause {
    entered: mpsc::SyncSender<()>,
    resume: mpsc::Receiver<()>,
}

struct ControlledClock {
    now: AtomicU64,
    calls: AtomicUsize,
    pause: Mutex<Option<Pause>>,
}

impl ControlledClock {
    fn new() -> Arc<Self> {
        Arc::new(Self {
            now: AtomicU64::new(NOW),
            calls: AtomicUsize::new(0),
            pause: Mutex::new(None),
        })
    }

    fn pause_next(&self) -> (mpsc::Receiver<()>, mpsc::SyncSender<()>) {
        let (entered, observed) = mpsc::sync_channel(1);
        let (release, resume) = mpsc::sync_channel(1);
        assert!(self.pause.lock().unwrap().is_none());
        *self.pause.lock().unwrap() = Some(Pause { entered, resume });
        (observed, release)
    }
}

impl SupplyChainClock for ControlledClock {
    fn now(&self) -> Result<u64, PlatformError> {
        self.calls.fetch_add(1, Ordering::SeqCst);
        let now = self.now.load(Ordering::SeqCst);
        let pause = self.pause.lock().unwrap().take();
        if let Some(pause) = pause {
            pause.entered.send(()).unwrap();
            pause.resume.recv_timeout(WATCHDOG).unwrap();
        }
        Ok(now)
    }
}

fn open(fixture: &Fixture, root: &std::path::Path) -> Arc<SupplyChainAuthority> {
    Arc::new(
        SupplyChainAuthority::open(root, fixture.approved(), fixture.clock.clone(), 5).unwrap(),
    )
}

fn pause_persistence(
    authority: &SupplyChainAuthority,
    fault: u8,
) -> (mpsc::Receiver<()>, mpsc::SyncSender<()>) {
    let (entered, observed) = mpsc::sync_channel(1);
    let (release, resume) = mpsc::sync_channel(1);
    let resume = Mutex::new(resume);
    let mut ledger = authority.inner.ledger.lock().unwrap();
    ledger.fault.store(fault, Ordering::SeqCst);
    ledger.checkpoint_hook = Some(Arc::new(move |point| {
        if point == 1 {
            entered.send(()).unwrap();
            resume.lock().unwrap().recv_timeout(WATCHDOG).unwrap();
        }
    }));
    (observed, release)
}

#[test]
fn original_admission_fence_can_read_source_with_exact_single_clock_observation() {
    let fixture = Fixture::new();
    let directory = tempfile::tempdir().unwrap();
    let clock = ControlledClock::new();
    let authority =
        SupplyChainAuthority::open(directory.path(), fixture.approved(), clock.clone(), 5).unwrap();
    let grant = authority
        .verify(&TenantId("tests".into()), fixture.upload())
        .unwrap()
        .grant;
    let source = authority.covered_clock_source();
    assert!(source.is_from_authority(&authority));
    let floor = std::fs::read(directory.path().join("floor.json")).unwrap();
    clock.calls.store(0, Ordering::SeqCst);
    grant
        .with_current(&mut |checker| {
            assert_eq!(
                authority.covered_clock().unwrap_err().message,
                "admission-authority-busy"
            );
            let before = clock.calls.load(Ordering::SeqCst);
            let covered = source.sample()?;
            assert_eq!(clock.calls.load(Ordering::SeqCst), before + 1);
            assert_eq!(covered.now_seconds, NOW);
            assert_eq!(covered.authority_epoch, 1);
            assert_eq!(covered.covered_until_seconds, NOW + 5);
            checker.check()
        })
        .unwrap();
    // One entry check, one source sample and one explicit original recheck.
    assert_eq!(clock.calls.load(Ordering::SeqCst), 3);
    assert_eq!(
        std::fs::read(directory.path().join("floor.json")).unwrap(),
        floor
    );
}

#[test]
fn source_does_not_publish_pending_renewal_until_actual_durable_floor_acceptance() {
    let fixture = Fixture::new();
    let directory = tempfile::tempdir().unwrap();
    let authority = open(&fixture, directory.path());
    let grant = authority
        .verify(&TenantId("tests".into()), fixture.upload())
        .unwrap()
        .grant;
    let source = authority.covered_clock_source();
    let (observed, release) = pause_persistence(&authority, 0);
    fixture.clock.set(NOW + 3);
    let renewing = Arc::clone(&authority);
    let worker = std::thread::spawn(move || renewing.renew_clock_lease());
    observed.recv_timeout(WATCHDOG).unwrap();
    grant
        .with_current(&mut |checker| {
            checker.check()?;
            assert_eq!(source.sample()?.covered_until_seconds, NOW + 5);
            fixture.clock.set(NOW + 5);
            assert_eq!(
                source.sample().unwrap_err().message,
                "admission-clock-lease-uncovered"
            );
            release.send(()).unwrap();
            Ok(())
        })
        .unwrap();
    worker.join().unwrap().unwrap();
    let accepted = source.sample().unwrap();
    assert_eq!(accepted.authority_epoch, 1);
    assert_eq!(accepted.covered_until_seconds, NOW + 8);
    grant.check_current().unwrap();
}

#[test]
fn every_uncertain_durable_renewal_cut_is_visible_inside_original_admission_fence() {
    for fault in 1..=4 {
        let fixture = Fixture::new();
        let directory = tempfile::tempdir().unwrap();
        let authority = open(&fixture, directory.path());
        let grant = authority
            .verify(&TenantId("tests".into()), fixture.upload())
            .unwrap()
            .grant;
        let source = authority.covered_clock_source();
        let (observed, release) = pause_persistence(&authority, fault);
        fixture.clock.set(NOW + 3);
        let renewing = Arc::clone(&authority);
        let (finished, completed) = mpsc::sync_channel(1);
        let worker = std::thread::spawn(move || {
            finished.send(renewing.renew_clock_lease()).unwrap();
        });
        observed.recv_timeout(WATCHDOG).unwrap();
        grant
            .with_current(&mut |checker| {
                source.sample()?;
                release.send(()).unwrap();
                assert_eq!(
                    completed
                        .recv_timeout(WATCHDOG)
                        .unwrap()
                        .unwrap_err()
                        .message,
                    "admission-durability-uncertain"
                );
                assert_eq!(
                    source.sample().unwrap_err().message,
                    "admission-durability-uncertain"
                );
                assert_eq!(
                    checker.check().unwrap_err().message,
                    "admission-durability-uncertain"
                );
                Ok(())
            })
            .unwrap();
        worker.join().unwrap();
        authority.retire();
        fixture.clock.set(NOW + 8);
        let restored = open(&fixture, directory.path());
        assert!(!source.is_from_authority(&restored));
        assert_eq!(
            source.sample().unwrap_err().message,
            "admission-owner-retired"
        );
        assert!(restored.covered_clock_source().sample().is_ok());
    }
}

#[test]
fn source_and_original_owner_share_regression_high_water_without_extra_clock_reads() {
    let fixture = Fixture::new();
    let directory = tempfile::tempdir().unwrap();
    let clock = ControlledClock::new();
    let authority =
        SupplyChainAuthority::open(directory.path(), fixture.approved(), clock.clone(), 5).unwrap();
    let source = authority.covered_clock_source();
    clock.now.store(NOW + 2, Ordering::SeqCst);
    source.sample().unwrap();
    clock.now.store(NOW + 1, Ordering::SeqCst);
    let before = clock.calls.load(Ordering::SeqCst);
    assert_eq!(
        authority.covered_clock().unwrap_err().message,
        "admission-clock-regression"
    );
    assert_eq!(clock.calls.load(Ordering::SeqCst), before + 1);
    assert_eq!(
        source.sample().unwrap_err().message,
        "admission-clock-regression"
    );
    clock.now.store(NOW + 2, Ordering::SeqCst);
    authority.covered_clock().unwrap();
    clock.now.store(NOW + 1, Ordering::SeqCst);
    assert_eq!(
        source.sample().unwrap_err().message,
        "admission-clock-regression"
    );
}

#[test]
fn retirement_closes_source_inside_a_held_original_grant_before_releasing_ledger() {
    let fixture = Fixture::new();
    let directory = tempfile::tempdir().unwrap();
    let authority = open(&fixture, directory.path());
    let grant = authority
        .verify(&TenantId("tests".into()), fixture.upload())
        .unwrap()
        .grant;
    let source = authority.covered_clock_source();
    let mut retirement = None;
    grant
        .with_current(&mut |checker| {
            let retiring = Arc::clone(&authority);
            retirement = Some(std::thread::spawn(move || retiring.retire()));
            let deadline = Instant::now() + WATCHDOG;
            while !authority.inner.retired.load(Ordering::Acquire) {
                assert!(Instant::now() < deadline, "actual retirement flag");
                std::thread::yield_now();
            }
            assert_eq!(
                source.sample().unwrap_err().message,
                "admission-owner-retired"
            );
            assert_eq!(
                checker.check().unwrap_err().message,
                "admission-owner-retired"
            );
            Ok(())
        })
        .unwrap();
    retirement.unwrap().join().unwrap();
    assert!(source.sample().is_err());
}

#[test]
fn weak_source_cannot_keep_a_retired_original_owner_or_new_owner_identity_alive() {
    let fixture = Fixture::new();
    let directory = tempfile::tempdir().unwrap();
    let authority = open(&fixture, directory.path());
    let source = authority.covered_clock_source();
    let original = Arc::downgrade(&authority.inner);
    drop(authority);
    assert!(original.upgrade().is_none());
    assert_eq!(
        source.sample().unwrap_err().message,
        "admission-owner-retired"
    );
    fixture.clock.set(NOW + 5);
    let replacement = open(&fixture, directory.path());
    assert!(!source.is_from_authority(&replacement));
    assert_eq!(
        replacement
            .covered_clock_source()
            .sample()
            .unwrap()
            .authority_epoch,
        2
    );
    assert!(source.sample().is_err());
}

#[test]
fn accepted_policy_epoch_and_window_replace_metadata_without_reauthorizing_old_grants() {
    let mut fixture = Fixture::new();
    let directory = tempfile::tempdir().unwrap();
    let authority = open(&fixture, directory.path());
    let grant = authority
        .verify(&TenantId("tests".into()), fixture.upload())
        .unwrap()
        .grant;
    let source = authority.covered_clock_source();
    fixture.policy["generation"] = serde_json::json!(2);
    fixture.policy["validUntil"] = serde_json::json!(NOW + 4);
    authority.replace_policy(fixture.approved()).unwrap();
    let accepted = source.sample().unwrap();
    assert_eq!(accepted.authority_epoch, 2);
    assert_eq!(accepted.covered_until_seconds, NOW + 5);
    assert_eq!(
        grant.check_current().unwrap_err().message,
        "admission-grant-stale"
    );
    fixture.clock.set(NOW + 4);
    assert_eq!(
        source.sample().unwrap_err().message,
        "admission-policy-expired"
    );
}

#[test]
fn overlapping_accepted_policy_publication_is_transient_and_never_returns_mixed_metadata() {
    let mut fixture = Fixture::new();
    let directory = tempfile::tempdir().unwrap();
    let clock = ControlledClock::new();
    let authority = Arc::new(
        SupplyChainAuthority::open(directory.path(), fixture.approved(), clock.clone(), 5).unwrap(),
    );
    let source = authority.covered_clock_source();
    let (observed, release) = clock.pause_next();
    let reading = source.clone();
    let worker = std::thread::spawn(move || reading.sample());
    observed.recv_timeout(WATCHDOG).unwrap();
    fixture.policy["generation"] = serde_json::json!(2);
    fixture.policy["validUntil"] = serde_json::json!(NOW + 4);
    authority.replace_policy(fixture.approved()).unwrap();
    release.send(()).unwrap();
    assert_eq!(
        worker.join().unwrap().unwrap_err().message,
        "admission-authority-busy"
    );
    let accepted = source.sample().unwrap();
    assert_eq!(accepted.authority_epoch, 2);
    assert_eq!(accepted.covered_until_seconds, NOW + 5);
}

#[test]
fn overlapping_durable_renewal_does_not_misreport_the_replaced_expired_ceiling() {
    let fixture = Fixture::new();
    let directory = tempfile::tempdir().unwrap();
    let clock = ControlledClock::new();
    let authority =
        SupplyChainAuthority::open(directory.path(), fixture.approved(), clock.clone(), 5).unwrap();
    let source = authority.covered_clock_source();
    clock.now.store(NOW + 5, Ordering::SeqCst);
    let (observed, release) = clock.pause_next();
    let reading = source.clone();
    let worker = std::thread::spawn(move || reading.sample());
    observed.recv_timeout(WATCHDOG).unwrap();
    authority.renew_clock_lease().unwrap();
    release.send(()).unwrap();
    assert_eq!(
        worker.join().unwrap().unwrap_err().message,
        "admission-authority-busy"
    );
    let covered = source.sample().unwrap();
    assert_eq!(covered.now_seconds, NOW + 5);
    assert_eq!(covered.covered_until_seconds, NOW + 10);
}

#[test]
fn completed_concurrent_observation_is_transient_but_poisoned_original_owner_is_rejected() {
    let fixture = Fixture::new();
    let directory = tempfile::tempdir().unwrap();
    let clock = ControlledClock::new();
    let authority = Arc::new(
        SupplyChainAuthority::open(directory.path(), fixture.approved(), clock.clone(), 5).unwrap(),
    );
    let source = authority.covered_clock_source();
    let (observed, release) = clock.pause_next();
    let reading = source.clone();
    let worker = std::thread::spawn(move || reading.sample());
    observed.recv_timeout(WATCHDOG).unwrap();
    clock.now.store(NOW + 1, Ordering::SeqCst);
    authority.covered_clock().unwrap();
    release.send(()).unwrap();
    assert_eq!(
        worker.join().unwrap().unwrap_err().message,
        "admission-authority-busy"
    );
    source.sample().unwrap();
    let inner = Arc::clone(&authority.inner);
    assert!(std::thread::spawn(move || {
        let _state = inner.state.lock().unwrap();
        panic!("intentional original owner poison");
    })
    .join()
    .is_err());
    assert_eq!(
        source.sample().unwrap_err().message,
        "admission-authority-poisoned"
    );
}
