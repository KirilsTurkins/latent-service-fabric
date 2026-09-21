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
    authority.inner.state.lock().unwrap().ledger.checkpoint_hook = Some(Arc::new(move |point| {
        if point == 1 {
            entered.send(()).unwrap();
            resume.lock().unwrap().recv_timeout(Duration::from_secs(10)).unwrap();
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
    assert!(fenced.is_ok(), "live fenced operation during renewal: {fenced:?}");
    admitted.grant.check_current().unwrap();
}
