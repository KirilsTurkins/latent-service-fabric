use std::time::{Duration, Instant};

use latent_core::ActivationClock;
use latent_testkit::coordination::{PollProbe, Stage};

#[test]
fn clock_and_rendezvous_reexports_preserve_type_and_state_identity() {
    let clock: latent_core::test_support::TestClock =
        latent_testkit::TestClock::new(433, Instant::now(), 1);
    let alias: latent_testkit::clocks::TestClock = clock.clone();
    let deadline = clock.monotonic_now() + Duration::from_nanos(1);
    let mut timer = Box::pin(alias.sleep_until(deadline));
    let probe = PollProbe::default();
    probe.pending(timer.as_mut());
    clock.advance(Duration::from_nanos(1));
    probe.ready(timer.as_mut());
    assert_eq!(alias.pending_waiters(), 0);
    let gate: latent_core::test_support::coordination::Rendezvous =
        latent_testkit::coordination::Rendezvous::new(1);
    let (id, mut owner) = gate.track(()).unwrap();
    owner.commit(Stage::Entered).unwrap();
    drop(owner);
    gate.require_retired(id).unwrap();
}

#[test]
fn deterministic_module_and_root_reexports_remain_compatible() {
    let mut ids: latent_core::test_support::DeterministicIds =
        latent_testkit::deterministic::DeterministicIds::new("compatible");
    assert_eq!(ids.next_id(), "compatible-0000000000000000");
    assert_eq!(latent_testkit::block_on(async { 433 }), 433);
    let clock: latent_core::test_support::ManualClock = latent_testkit::ManualClock::default();
    assert_eq!(clock.advance_nanos(1), 1);
    let parent = tempfile::tempdir().unwrap();
    let workspace: latent_core::test_support::TempWorkspace =
        latent_testkit::TempWorkspace::create_under(parent.path(), "compatibility").unwrap();
    assert!(workspace.path().is_dir());
}
