//! Actual protected startup/coverage, distinct from maintenance permission.
use super::*;
use crate::standalone::state::{kernel::tests::Fixture, AdapterClock, StateKernel};
use std::time::Duration;

#[tokio::test]
async fn maintenance_uses_original_protected_sample_and_shared_process_identity() {
    let fixture = Fixture::new();
    let (kernel, mut effects) = StateKernel::start(
        fixture.bootstrap(),
        &fixture.settings,
        fixture.authority.clone(),
        Vec::new(),
        &AdapterClock::default(),
        tokio::runtime::Handle::current(),
    )
    .await
    .unwrap();
    // Other test kernels can establish the real process origin concurrently.
    // Move this retained fixture's trusted original source coherently to now.
    fixture.clock.advance_to(Instant::now());
    let first = ProtectedMaintenanceClock::new(Arc::clone(&kernel.clock)).unwrap();
    let second = ProtectedMaintenanceClock::new(Arc::clone(&kernel.clock)).unwrap();
    fixture.clock.advance_to(Instant::now());
    let original = kernel.clock.sample().unwrap();
    let before = first.sample().unwrap();
    assert_eq!(before.time.unix_millis, original.unix_millis());
    assert!(before.time.continuity_proven);
    assert_ne!(before.boot, [0; 32]);
    assert_eq!(second.sample().unwrap().boot, before.boot);
    fixture
        .clock
        .advance_to(original.monotonic() + Duration::from_millis(17));
    let after = first.sample().unwrap();
    assert_eq!(after.time.unix_millis, before.time.unix_millis + 17);
    assert_eq!(after.monotonic_millis, before.monotonic_millis + 17);
    assert_eq!(after.boot, before.boot);
    drop(first);
    drop(second);
    let deadline = Instant::now() + Duration::from_secs(20);
    assert!(effects.shutdown(deadline).await.unwrap().clean);
    drop(effects);
    assert!(kernel.shutdown(deadline).await.unwrap().clean);
}

#[tokio::test]
async fn maintenance_cannot_synthesize_continuity_after_actual_covered_lease_loss() {
    let fixture = Fixture::new();
    let (kernel, mut effects) = StateKernel::start(
        fixture.bootstrap(),
        &fixture.settings,
        fixture.authority.clone(),
        Vec::new(),
        &AdapterClock::default(),
        tokio::runtime::Handle::current(),
    )
    .await
    .unwrap();
    fixture.clock.advance_to(Instant::now());
    let maintenance = ProtectedMaintenanceClock::new(Arc::clone(&kernel.clock)).unwrap();
    fixture.clock.advance_to(Instant::now());
    let original = kernel.clock.sample().unwrap();
    assert!(maintenance.sample().is_ok());
    fixture
        .clock
        .advance_to(original.monotonic() + Duration::from_secs(6));
    assert!(kernel.clock.sample().is_err());
    assert!(maintenance.sample().is_err());
    assert!(maintenance.sample().is_err());
    assert!(ProtectedMaintenanceClock::new(Arc::clone(&kernel.clock)).is_err());
    drop(maintenance);
    let deadline = Instant::now() + Duration::from_secs(20);
    assert!(effects.shutdown(deadline).await.unwrap().clean);
    drop(effects);
    assert!(kernel.shutdown(deadline).await.unwrap().clean);
}
