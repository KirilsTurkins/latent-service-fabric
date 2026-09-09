use latent_core::ActivationId;

use super::{InvocationInputDropReason, InvocationInputObserver, InvocationInputPhase};

fn enabled(ids: &[&str]) -> InvocationInputObserver {
    let observer = InvocationInputObserver::new();
    observer
        .enable(
            &ids.iter()
                .map(|id| ActivationId((*id).to_owned()))
                .collect::<Vec<_>>(),
        )
        .expect("bounded session");
    observer
}

#[test]
fn disabled_begin_does_not_lock_clone_identity_or_record() {
    let observer = InvocationInputObserver::new();
    let state = observer.inner.lock();
    // A disabled invocation must return without trying to reacquire this mutex.
    assert!(observer
        .begin(&ActivationId("disabled".to_owned()))
        .is_none());
    assert!(state.identities.is_empty());
    assert!(state.records.is_empty());
    drop(state);
    let snapshot = observer.snapshot();
    assert!(!snapshot.enabled);
    assert!(!snapshot.overflowed);
    assert_eq!(snapshot.started_invocations, 0);
}

#[test]
fn registration_is_atomic_bounded_and_cannot_reset_a_live_session() {
    let observer = InvocationInputObserver::new();
    for ids in [
        Vec::new(),
        vec![ActivationId(String::new())],
        vec![ActivationId("x".repeat(513))],
        vec![ActivationId("same".to_owned()); 2],
        (0..9)
            .map(|index| ActivationId(index.to_string()))
            .collect(),
    ] {
        assert!(observer.enable(&ids).is_err());
        assert!(!observer.snapshot().enabled);
    }
    let ids: Vec<_> = (0..8)
        .map(|index| ActivationId(format!("{index}{}", "x".repeat(511))))
        .collect();
    observer.enable(&ids).expect("exact identity bounds");
    let owner = observer.begin(&ids[7]).expect("last registered ID");
    assert!(observer.enable(&ids).is_err());
    assert_eq!(observer.snapshot().live_invocations, 1);
    drop(owner);
    let snapshot = observer.snapshot();
    assert_eq!(snapshot.identities.len(), 8);
    assert_eq!(snapshot.records[0].token, 7);
    assert_eq!(snapshot.dropped_invocations, 1);
    assert!(!snapshot.overflowed);
}

#[test]
fn reused_unknown_and_duplicate_stage_fail_coverage_without_stealing_owners() {
    let observer = enabled(&["known"]);
    let owner = observer.begin(&ActivationId("known".to_owned())).unwrap();
    assert!(observer
        .begin(&ActivationId("unknown".to_owned()))
        .is_none());
    assert!(observer.begin(&ActivationId("known".to_owned())).is_none());
    let trace = owner.trace();
    let raw = trace.raw_owner(4, 8).unwrap();
    trace.stage(InvocationInputPhase::BeforeCallExport);
    trace.stage(InvocationInputPhase::BeforeCallExport);
    trace.stage(InvocationInputPhase::GuestCallStart);
    drop(raw);
    drop(owner);
    let snapshot = observer.snapshot();
    assert!(snapshot.overflowed);
    assert_eq!(snapshot.started_invocations, 1);
    assert_eq!(
        (
            snapshot.live_invocations,
            snapshot.live_raw_owners,
            snapshot.live_raw_capacity_bytes
        ),
        (0, 0, 0)
    );
    assert_eq!(snapshot.records.len(), 5);
    assert_eq!(
        snapshot.records[3].drop_reason,
        Some(InvocationInputDropReason::OwnerScopeExit)
    );
}

#[test]
fn raw_counts_preserve_capacity_and_zero_length_owner_until_its_drop() {
    let observer = enabled(&["first", "empty"]);
    let mut first = observer.begin(&ActivationId("first".to_owned())).unwrap();
    let mut second = observer.begin(&ActivationId("empty".to_owned())).unwrap();
    let raw = first.trace().raw_owner(3, 32).unwrap();
    let empty = second.trace().raw_owner(0, 0).unwrap();
    assert_eq!(observer.snapshot().live_raw_owners, 2);
    drop(raw);
    let during = observer.snapshot();
    assert_eq!(
        (during.live_raw_owners, during.live_raw_capacity_bytes),
        (1, 0)
    );
    assert_eq!(during.maximum_live_raw_capacity_bytes, 32);
    drop(empty);
    first.completed();
    second.completed();
    drop(first);
    drop(second);
    let snapshot = observer.snapshot();
    assert_eq!(
        (snapshot.finished_invocations, snapshot.live_invocations),
        (2, 0)
    );
    assert_eq!(snapshot.maximum_live_raw_owners, 2);
    assert!(!snapshot.overflowed);
    for (index, record) in snapshot.records.iter().enumerate() {
        assert_eq!(record.sequence, u64::try_from(index).unwrap());
        assert!(record.observed_nanos <= snapshot.observed_nanos);
    }
    assert!(snapshot
        .records
        .windows(2)
        .all(|pair| pair[0].observed_nanos <= pair[1].observed_nanos));
}

#[test]
fn invalid_stage_order_marks_coverage_and_retirement_still_refunds() {
    let observer = enabled(&["failure"]);
    let owner = observer.begin(&ActivationId("failure".to_owned())).unwrap();
    owner.trace().stage(InvocationInputPhase::GuestCallStart);
    drop(owner);
    let snapshot = observer.snapshot();
    assert!(snapshot.overflowed);
    assert_eq!(snapshot.records.len(), 1);
    assert_eq!(
        snapshot.records[0].phase,
        InvocationInputPhase::InvocationDropped
    );
    assert_eq!(snapshot.records[0].raw_capacity_bytes, None);
    assert_eq!(snapshot.live_invocations, 0);
}

#[test]
fn records_are_never_overwritten_when_diagnostic_storage_is_exhausted() {
    let observer = enabled(&["first", "second"]);
    drop(observer.begin(&ActivationId("first".to_owned())).unwrap());
    let retained = observer.snapshot().records[0].clone();
    // A valid session needs fewer than 64 records. Force its bounded storage
    // seam full to prove later retirement still refunds and cannot overwrite it.
    observer
        .inner
        .lock()
        .records
        .resize(super::MAXIMUM_RECORDS, retained.clone());
    drop(observer.begin(&ActivationId("second".to_owned())).unwrap());
    let snapshot = observer.snapshot();
    assert!(snapshot.overflowed);
    assert_eq!(snapshot.records.len(), 64);
    assert_eq!(snapshot.records[0], retained);
    assert_eq!(snapshot.dropped_invocations, 2);
    assert_eq!(snapshot.live_invocations, 0);
}
