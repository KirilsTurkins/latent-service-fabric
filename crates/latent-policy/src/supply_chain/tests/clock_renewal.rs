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
