use super::*;
use latent_artifacts::AdmissionAuthority;
use latent_core::TenantId;
use std::sync::{mpsc, Arc, Mutex};
use std::time::Duration;

#[test]
fn current_grants_remain_available_during_clock_floor_persistence() {
    let fixture = Fixture::new();
    let directory = tempfile::tempdir().unwrap();
    let authority = Arc::new(
        SupplyChainAuthority::open(
            directory.path(),
            fixture.approved(),
            fixture.clock.clone(),
            5,
        )
        .unwrap(),
    );
    let admitted = authority
        .verify(&TenantId("tests".into()), fixture.upload())
        .unwrap();
    let (entered, observed) = mpsc::sync_channel(1);
    let (release, resume) = mpsc::sync_channel(1);
    let resume = Mutex::new(resume);
    authority.inner.ledger.lock().unwrap().checkpoint_hook = Some(Arc::new(move |point| {
        if point == 1 {
            entered.send(()).unwrap();
            resume
                .lock()
                .unwrap()
                .recv_timeout(Duration::from_secs(10))
                .unwrap();
        }
    }));
    fixture.clock.set(NOW + 3);
    let renewing = Arc::clone(&authority);
    let worker = std::thread::spawn(move || renewing.renew_clock_lease());
    observed.recv_timeout(Duration::from_secs(10)).unwrap();
    // The original durable lease still covers NOW + 3. A background append
    // must not make an unrelated current guest or provider checkpoint fail.
    let checked = admitted.grant.check_current();
    let fenced = admitted.grant.with_current(&mut |checker| checker.check());
    release.send(()).unwrap();
    worker.join().unwrap().unwrap();
    assert!(checked.is_ok(), "live grant during renewal: {checked:?}");
    assert!(
        fenced.is_ok(),
        "live fenced operation during renewal: {fenced:?}"
    );
    admitted.grant.check_current().unwrap();
}

fn paused_authority(
    fixture: &Fixture,
    root: &std::path::Path,
    fault: u8,
) -> (
    Arc<SupplyChainAuthority>,
    mpsc::Receiver<()>,
    mpsc::SyncSender<()>,
) {
    let authority = Arc::new(
        SupplyChainAuthority::open(root, fixture.approved(), fixture.clock.clone(), 5).unwrap(),
    );
    let (entered, observed) = mpsc::sync_channel(1);
    let (release, resume) = mpsc::sync_channel(1);
    let resume = Mutex::new(resume);
    let mut ledger = authority.inner.ledger.lock().unwrap();
    ledger.fault.store(fault, Ordering::SeqCst);
    ledger.checkpoint_hook = Some(Arc::new(move |point| {
        if point == 1 {
            entered.send(()).unwrap();
            resume
                .lock()
                .unwrap()
                .recv_timeout(Duration::from_secs(10))
                .unwrap();
        }
    }));
    drop(ledger);
    (authority, observed, release)
}

#[test]
fn pending_clock_floor_never_extends_a_grant_before_durable_publication() {
    let fixture = Fixture::new();
    let directory = tempfile::tempdir().unwrap();
    let (authority, observed, release) = paused_authority(&fixture, directory.path(), 0);
    let admitted = authority
        .verify(&TenantId("tests".into()), fixture.upload())
        .unwrap();
    fixture.clock.set(NOW + 3);
    let renewing = Arc::clone(&authority);
    let worker = std::thread::spawn(move || renewing.renew_clock_lease());
    observed.recv_timeout(Duration::from_secs(10)).unwrap();
    fixture.clock.set(NOW + 5);
    let expired = admitted.grant.check_current();
    release.send(()).unwrap();
    worker.join().unwrap().unwrap();
    assert_eq!(
        expired.unwrap_err().message,
        "admission-clock-lease-uncovered"
    );
    admitted.grant.check_current().unwrap();
}

#[test]
fn failed_clock_persistence_halts_grants_without_restoring_the_old_floor() {
    let fixture = Fixture::new();
    let directory = tempfile::tempdir().unwrap();
    let (authority, observed, release) = paused_authority(&fixture, directory.path(), 2);
    let admitted = authority
        .verify(&TenantId("tests".into()), fixture.upload())
        .unwrap();
    fixture.clock.set(NOW + 3);
    let renewing = Arc::clone(&authority);
    let (finished, completion) = mpsc::sync_channel(1);
    let worker = std::thread::spawn(move || {
        finished.send(renewing.renew_clock_lease()).unwrap();
    });
    observed.recv_timeout(Duration::from_secs(10)).unwrap();
    let mut persistence = None;
    let fenced = admitted.grant.with_current(&mut |checker| {
        checker.check()?;
        release.send(()).unwrap();
        // Retain the currentness fence until the write reports failure. The
        // existing checker must see uncertainty without releasing this fence.
        persistence = Some(completion.recv_timeout(Duration::from_secs(10)).unwrap());
        checker.check()
    });
    worker.join().unwrap();
    assert_eq!(
        persistence.unwrap().unwrap_err().message,
        "admission-durability-uncertain"
    );
    assert_eq!(
        fenced.unwrap_err().message,
        "admission-durability-uncertain"
    );
    assert_eq!(
        admitted.grant.check_current().unwrap_err().message,
        "admission-durability-uncertain"
    );
    assert!(authority.renew_clock_lease().is_err());
}

#[test]
fn policy_replacement_cannot_overtake_a_pending_clock_floor_write() {
    let mut fixture = Fixture::new();
    let directory = tempfile::tempdir().unwrap();
    let (authority, observed, release) = paused_authority(&fixture, directory.path(), 0);
    let admitted = authority
        .verify(&TenantId("tests".into()), fixture.upload())
        .unwrap();
    fixture.clock.set(NOW + 3);
    let renewing = Arc::clone(&authority);
    let worker = std::thread::spawn(move || renewing.renew_clock_lease());
    observed.recv_timeout(Duration::from_secs(10)).unwrap();
    fixture.policy["generation"] = serde_json::json!(2);
    let blocked = authority.replace_policy(fixture.approved());
    release.send(()).unwrap();
    worker.join().unwrap().unwrap();
    assert_eq!(blocked.unwrap_err().message, "admission-control-busy");
    authority.inner.ledger.lock().unwrap().checkpoint_hook = None;
    authority.replace_policy(fixture.approved()).unwrap();
    assert_eq!(
        admitted.grant.check_current().unwrap_err().message,
        "admission-grant-stale"
    );
    authority
        .verify(&TenantId("tests".into()), fixture.upload())
        .unwrap();
}

#[test]
fn retirement_waits_for_the_pending_floor_and_never_revives_held_grants() {
    let fixture = Fixture::new();
    let directory = tempfile::tempdir().unwrap();
    let (authority, observed, release) = paused_authority(&fixture, directory.path(), 0);
    let admitted = authority
        .verify(&TenantId("tests".into()), fixture.upload())
        .unwrap();
    fixture.clock.set(NOW + 3);
    let renewing = Arc::clone(&authority);
    let worker = std::thread::spawn(move || renewing.renew_clock_lease());
    observed.recv_timeout(Duration::from_secs(10)).unwrap();
    let retiring = Arc::clone(&authority);
    let retired = std::thread::spawn(move || retiring.retire());
    let deadline = std::time::Instant::now() + Duration::from_secs(10);
    while !authority.inner.retired.load(Ordering::Acquire) && std::time::Instant::now() < deadline {
        std::thread::yield_now();
    }
    let denied = admitted.grant.check_current();
    release.send(()).unwrap();
    let renewal = worker.join().unwrap();
    retired.join().unwrap();
    assert_eq!(denied.unwrap_err().message, "admission-owner-retired");
    assert_eq!(renewal.unwrap_err().message, "admission-owner-retired");
    assert!(admitted.grant.check_current().is_err());
    fixture.clock.set(NOW + 8);
    SupplyChainAuthority::open(
        directory.path(),
        fixture.approved(),
        fixture.clock.clone(),
        5,
    )
    .unwrap();
}

struct PausedClock {
    value: Arc<Clock>,
    pause_next: std::sync::atomic::AtomicBool,
    entered: mpsc::SyncSender<()>,
    resume: Mutex<mpsc::Receiver<()>>,
}

impl SupplyChainClock for PausedClock {
    fn now(&self) -> Result<u64, PlatformError> {
        let sampled = self.value.now()?;
        if self.pause_next.swap(false, Ordering::SeqCst) {
            self.entered.send(()).unwrap();
            self.resume
                .lock()
                .unwrap()
                .recv_timeout(Duration::from_secs(10))
                .unwrap();
        }
        Ok(sampled)
    }
}

fn concurrent_current_grant_checkpoint(renewal: bool, fenced: bool) {
    let fixture = Fixture::new();
    let directory = tempfile::tempdir().unwrap();
    let (entered, observed) = mpsc::sync_channel(1);
    let (release, resume) = mpsc::sync_channel(1);
    let clock = Arc::new(PausedClock {
        value: fixture.clock.clone(),
        pause_next: std::sync::atomic::AtomicBool::new(false),
        entered,
        resume: Mutex::new(resume),
    });
    let authority = Arc::new(
        SupplyChainAuthority::open(directory.path(), fixture.approved(), clock.clone(), 5).unwrap(),
    );
    let admitted = authority
        .verify(&TenantId("tests".into()), fixture.upload())
        .unwrap();
    fixture.clock.set(NOW + 1);
    clock.pause_next.store(true, Ordering::SeqCst);
    let owner = Arc::clone(&authority);
    let grant = Arc::clone(&admitted.grant);
    let worker = std::thread::spawn(move || {
        if renewal {
            owner.renew_clock_lease()
        } else {
            grant.check_current()
        }
    });
    observed.recv_timeout(Duration::from_secs(10)).unwrap();
    // No policy, publication, route or durable floor changes in this interval.
    // A trusted clock sample by another reader is not authority revocation.
    let checked = if fenced {
        admitted.grant.with_current(&mut |checker| {
            checker.check()?;
            assert_eq!(
                admitted.grant.check_current().unwrap_err().message,
                "admission-authority-busy"
            );
            assert_eq!(
                admitted
                    .grant
                    .with_current(&mut |check| check.check())
                    .unwrap_err()
                    .message,
                "admission-authority-busy"
            );
            assert!(authority.renew_clock_lease().is_err());
            checker.check()
        })
    } else {
        admitted.grant.check_current()
    };
    release.send(()).unwrap();
    worker.join().unwrap().unwrap();
    assert!(
        checked.is_ok(),
        "current publication during read-only clock sample (renewal={renewal}, fenced={fenced}): {checked:?}"
    );
    admitted.grant.check_current().unwrap();
}

#[test]
fn current_grants_remain_available_during_trusted_clock_renewal_sample() {
    concurrent_current_grant_checkpoint(true, false);
}

#[test]
fn current_grant_checkpoints_share_a_read_only_authority_epoch() {
    concurrent_current_grant_checkpoint(false, false);
}

#[test]
fn final_publication_remains_available_during_trusted_clock_renewal_sample() {
    concurrent_current_grant_checkpoint(true, true);
}

#[test]
fn final_publication_remains_available_during_read_only_grant_clock_sample() {
    concurrent_current_grant_checkpoint(false, true);
}

#[test]
fn out_of_order_readers_preserve_the_clock_high_water_mark_and_detect_later_rollback() {
    let fixture = Fixture::new();
    let directory = tempfile::tempdir().unwrap();
    let (entered, observed) = mpsc::sync_channel(1);
    let (release, resume) = mpsc::sync_channel(1);
    let clock = Arc::new(PausedClock {
        value: fixture.clock.clone(),
        pause_next: std::sync::atomic::AtomicBool::new(false),
        entered,
        resume: Mutex::new(resume),
    });
    let authority =
        SupplyChainAuthority::open(directory.path(), fixture.approved(), clock.clone(), 5).unwrap();
    let admitted = authority
        .verify(&TenantId("tests".into()), fixture.upload())
        .unwrap();
    fixture.clock.set(NOW + 1);
    clock.pause_next.store(true, Ordering::SeqCst);
    let grant = Arc::clone(&admitted.grant);
    let worker = std::thread::spawn(move || grant.check_current());
    observed.recv_timeout(Duration::from_secs(10)).unwrap();
    fixture.clock.set(NOW + 2);
    let later = admitted.grant.check_current();
    release.send(()).unwrap();
    worker.join().unwrap().unwrap();
    later.unwrap();
    assert_eq!(
        authority
            .inner
            .read()
            .unwrap()
            .observed_at
            .load(Ordering::Acquire),
        NOW + 2
    );
    fixture.clock.set(NOW + 1);
    assert_eq!(
        admitted.grant.check_current().unwrap_err().message,
        "admission-clock-regression"
    );
}

#[test]
fn failed_durable_renewal_invalidates_a_reader_paused_in_the_trusted_clock() {
    let fixture = Fixture::new();
    let directory = tempfile::tempdir().unwrap();
    let (entered, observed) = mpsc::sync_channel(1);
    let (release, resume) = mpsc::sync_channel(1);
    let clock = Arc::new(PausedClock {
        value: fixture.clock.clone(),
        pause_next: std::sync::atomic::AtomicBool::new(false),
        entered,
        resume: Mutex::new(resume),
    });
    let authority =
        SupplyChainAuthority::open(directory.path(), fixture.approved(), clock.clone(), 5).unwrap();
    let admitted = authority
        .verify(&TenantId("tests".into()), fixture.upload())
        .unwrap();
    fixture.clock.set(NOW + 1);
    clock.pause_next.store(true, Ordering::SeqCst);
    let grant = Arc::clone(&admitted.grant);
    let worker = std::thread::spawn(move || grant.check_current());
    observed.recv_timeout(Duration::from_secs(10)).unwrap();
    authority
        .inner
        .ledger
        .lock()
        .unwrap()
        .fault
        .store(2, Ordering::SeqCst);
    fixture.clock.set(NOW + 3);
    let renewal = authority.renew_clock_lease();
    release.send(()).unwrap();
    let checked = worker.join().unwrap();
    assert_eq!(
        renewal.unwrap_err().message,
        "admission-durability-uncertain"
    );
    assert_eq!(
        checked.unwrap_err().message,
        "admission-durability-uncertain"
    );
    assert_eq!(
        admitted.grant.check_current().unwrap_err().message,
        "admission-durability-uncertain"
    );
}

#[test]
fn retiring_the_owner_invalidates_a_reader_paused_in_the_trusted_clock() {
    let fixture = Fixture::new();
    let directory = tempfile::tempdir().unwrap();
    let (entered, observed) = mpsc::sync_channel(1);
    let (release, resume) = mpsc::sync_channel(1);
    let clock = Arc::new(PausedClock {
        value: fixture.clock.clone(),
        pause_next: std::sync::atomic::AtomicBool::new(false),
        entered,
        resume: Mutex::new(resume),
    });
    let authority = Arc::new(
        SupplyChainAuthority::open(directory.path(), fixture.approved(), clock.clone(), 5).unwrap(),
    );
    let admitted = authority
        .verify(&TenantId("tests".into()), fixture.upload())
        .unwrap();
    fixture.clock.set(NOW + 1);
    clock.pause_next.store(true, Ordering::SeqCst);
    let grant = Arc::clone(&admitted.grant);
    let worker = std::thread::spawn(move || grant.check_current());
    observed.recv_timeout(Duration::from_secs(10)).unwrap();
    let retiring = Arc::clone(&authority);
    let retirement = std::thread::spawn(move || retiring.retire());
    let deadline = std::time::Instant::now() + Duration::from_secs(3);
    while !authority.inner.retired.load(Ordering::Acquire) {
        assert!(
            std::time::Instant::now() < deadline,
            "retirement must start"
        );
        std::thread::yield_now();
    }
    release.send(()).unwrap();
    let checked = worker.join().unwrap();
    retirement.join().unwrap();
    assert_eq!(checked.unwrap_err().message, "admission-owner-retired");
    assert_eq!(
        admitted.grant.check_current().unwrap_err().message,
        "admission-owner-retired"
    );
}
