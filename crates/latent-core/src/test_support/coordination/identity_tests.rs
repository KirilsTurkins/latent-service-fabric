use super::*;

#[test]
fn tickets_from_another_fixture_cannot_release_a_live_owner() {
    let first = Rendezvous::new(1);
    let second = Rendezvous::new(1);
    let (first_id, mut first_owner) = first.track(()).unwrap();
    let (second_id, mut second_owner) = second.track(()).unwrap();
    let mut first_pause = Box::pin(first_owner.pause());
    let mut second_pause = Box::pin(second_owner.pause());
    let probe = PollProbe::default();
    probe.pending(first_pause.as_mut());
    probe.pending(second_pause.as_mut());
    let first_ticket = first.blocked(first_id, Stage::Requested).unwrap();
    let second_ticket = second.blocked(second_id, Stage::Requested).unwrap();
    assert_eq!(
        second.release(first_ticket),
        Err(CoordinationError::StaleRegistration)
    );
    assert_eq!(
        first.snapshot(second_id),
        Err(CoordinationError::StaleRegistration)
    );
    second.blocked(second_id, Stage::Requested).unwrap();
    first.release(first_ticket).unwrap();
    second.release(second_ticket).unwrap();
    probe.ready(first_pause.as_mut());
    probe.ready(second_pause.as_mut());
    drop(first_pause);
    drop(second_pause);
    drop(first_owner);
    drop(second_owner);
    first.require_retired(first_id).unwrap();
    second.require_retired(second_id).unwrap();
}

#[test]
fn observer_does_not_retain_the_actual_owner_or_its_buffer() {
    let rendezvous = Rendezvous::new(1);
    let buffer = Arc::new(vec![0_u8; 16]);
    let weak = Arc::downgrade(&buffer);
    let (id, owner) = rendezvous.track(buffer).unwrap();
    assert_eq!(weak.strong_count(), 1);
    assert_eq!(rendezvous.live_owners(), 1);
    drop(owner);
    rendezvous.require_retired(id).unwrap();
    assert!(weak.upgrade().is_none());
    assert_eq!(rendezvous.live_owners(), 0);
}
