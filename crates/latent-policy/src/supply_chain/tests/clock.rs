use super::*;
use latent_artifacts::AdmissionAuthority;
use latent_core::TenantId;
use std::collections::VecDeque;

struct SequenceClock(Mutex<VecDeque<u64>>);
impl SupplyChainClock for SequenceClock {
    fn now(&self) -> Result<u64, PlatformError> {
        Ok(self.0.lock().unwrap().pop_front().expect("clock sample"))
    }
}

#[test]
fn renewal_without_persistence_retains_covered_clock_observation() {
    let fixture = Fixture::new();
    let directory = tempfile::tempdir().unwrap();
    let authority = SupplyChainAuthority::open(
        directory.path(),
        fixture.approved(),
        fixture.clock.clone(),
        5,
    )
    .unwrap();
    let original_floor = std::fs::read(directory.path().join("floor.json")).unwrap();
    fixture.clock.set(NOW + 1);
    authority.renew_clock_lease().unwrap();
    assert_eq!(
        std::fs::read(directory.path().join("floor.json")).unwrap(),
        original_floor
    );
    fixture.clock.set(NOW);
    assert_eq!(
        authority
            .verify(&TenantId("tests".into()), fixture.upload())
            .err()
            .unwrap()
            .message,
        "admission-clock-regression"
    );
}

#[test]
fn renewal_post_sync_regression_cannot_forget_newly_covered_observation() {
    let fixture = Fixture::new();
    let directory = tempfile::tempdir().unwrap();
    let clock = Arc::new(SequenceClock(Mutex::new(VecDeque::from([
        NOW,
        NOW,
        NOW + 5,
        NOW + 4,
        NOW + 4,
    ]))));
    let authority =
        SupplyChainAuthority::open(directory.path(), fixture.approved(), clock, 5).unwrap();
    assert_eq!(
        authority.renew_clock_lease().unwrap_err().message,
        "admission-clock-lease-uncovered"
    );
    assert_eq!(authority.inner.lock().unwrap().observed_at, NOW + 5);
    assert_eq!(
        authority
            .verify(&TenantId("tests".into()), fixture.upload())
            .err()
            .unwrap()
            .message,
        "admission-clock-regression"
    );
}
