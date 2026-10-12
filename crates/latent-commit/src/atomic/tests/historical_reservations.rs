//! Real linked rows keep each reservation attached to its current generation.
use super::*;
use latent_state::{embedded::StoreError, reservation::LogicalReservation};

#[derive(Clone, Copy, Debug)]
enum Corruption {
    MissingReservation,
    WrongGeneration,
    WrongBytes,
    WrongAccounting,
    ChangedSource,
    ChangedCurrentAttempt,
}

fn aborted(store: &EmbeddedStore, effects: &EffectAuthorityOwner) -> CommandRecord {
    let owner = claim(store, input("historical-reservation"));
    let retirement = owner.retirement();
    let physical = owner.physical_work().unwrap();
    drop(owner);
    assert!(matches!(
        retirement.proven_noncommit(),
        Err(AtomicError::RecoveryRequired)
    ));
    physical.retire();
    confirm(
        CompleteEnvelope::technical_abort(
            &store.snapshot().unwrap(),
            retirement.proven_noncommit().unwrap(),
            "state-conflict".into(),
            time(101),
        )
        .unwrap(),
        store,
        effects,
    )
}

fn retry(store: &EmbeddedStore, aborted: &CommandRecord) -> AdmittedCommand {
    let AdmissionDecision::New(prepared) = PreparedAdmission::retry(
        &store.snapshot().unwrap(),
        &input("historical-reservation"),
        &RetryRequest {
            request_id: "explicit-second-attempt".into(),
            expected_abort: aborted.abort_proof().unwrap(),
        },
        time(102),
        permission,
    )
    .unwrap() else {
        panic!("the actual retired abort must admit exactly one new generation")
    };
    prepared.publish(store, || Ok(())).unwrap()
}

fn replace(store: &EmbeddedStore, key: RowKey, value: Option<Vec<u8>>) {
    store
        .apply(AtomicBatch {
            expectations: vec![],
            mutations: vec![RowMutation { key, value }],
        })
        .unwrap();
}

fn historical(store: &EmbeddedStore, aborted: &CommandRecord) -> Result<(), StoreError> {
    let view = store.snapshot().unwrap();
    let key = attempt_row_key(aborted.id(), aborted.attempt());
    let bytes = view.get(&key).unwrap().unwrap();
    assert_eq!(CommandRecord::decode(&bytes).unwrap(), *aborted);
    validate_linked_row(&view, &key, &bytes)
}

#[test]
fn historical_abort_preserves_exact_links_during_pending_and_terminal_retry() {
    let (_directory, store, effects) = setup();
    let aborted = aborted(&store, &effects);
    let owner = retry(&store, &aborted);
    let current = owner.record().clone();
    assert_eq!(current.attempt(), 2);
    assert_eq!(current.outcome(), Outcome::Pending);
    let key = latent_state::reservation::reservation_key(&current.id().0).unwrap();
    let bytes = store.snapshot().unwrap().get(&key).unwrap().unwrap();
    let reservation = LogicalReservation::decode(&bytes).unwrap();
    assert_eq!(reservation.generation, current.attempt());
    assert_eq!(
        reservation.bytes,
        current
            .result_policy
            .reservation_for(current.accounted)
            .unwrap()
    );
    historical(&store, &aborted).unwrap();
    validate_view(&store.snapshot().unwrap(), foreign_codec).unwrap();
    let terminal = confirm(
        CompleteEnvelope::success(
            &store.snapshot().unwrap(),
            owner,
            None,
            vec![],
            value(b"exact second-attempt response"),
            &effects,
            time(102),
        )
        .unwrap(),
        &store,
        &effects,
    );
    assert_eq!(terminal.attempt(), 2);
    assert_eq!(terminal.outcome(), Outcome::Committed);
    assert!(store.snapshot().unwrap().get(&key).unwrap().is_none());
    historical(&store, &aborted).unwrap();
    validate_view(&store.snapshot().unwrap(), foreign_codec).unwrap();
}

#[test]
fn historical_abort_rejects_missing_or_misbound_current_pending_reservations() {
    for corruption in [
        Corruption::MissingReservation,
        Corruption::WrongGeneration,
        Corruption::WrongBytes,
        Corruption::WrongAccounting,
        Corruption::ChangedSource,
        Corruption::ChangedCurrentAttempt,
    ] {
        let (_directory, store, effects) = setup();
        let aborted = aborted(&store, &effects);
        let owner = retry(&store, &aborted);
        let current = owner.record().clone();
        historical(&store, &aborted).unwrap();
        let key = latent_state::reservation::reservation_key(&current.id().0).unwrap();
        let original = store.snapshot().unwrap().get(&key).unwrap().unwrap();
        let reservation = LogicalReservation::decode(&original).unwrap();
        match corruption {
            Corruption::MissingReservation => replace(&store, key, None),
            Corruption::WrongGeneration | Corruption::WrongBytes | Corruption::WrongAccounting => {
                let changed = LogicalReservation {
                    generation: reservation.generation
                        + u64::from(matches!(corruption, Corruption::WrongGeneration)),
                    bytes: reservation.bytes
                        - u64::from(matches!(corruption, Corruption::WrongBytes)),
                };
                replace(
                    &store,
                    key,
                    Some(
                        changed
                            .encode_for(
                                current.accounted
                                    != matches!(corruption, Corruption::WrongAccounting),
                            )
                            .unwrap(),
                    ),
                );
            }
            Corruption::ChangedSource => {
                let mut changed = current.clone();
                changed.source.component_digest = format!("sha256:{}", "5".repeat(64));
                let changed = changed.encode().unwrap();
                replace(&store, command_row_key(current.id()), Some(changed.clone()));
                replace(
                    &store,
                    attempt_row_key(current.id(), current.attempt()),
                    Some(changed),
                );
            }
            Corruption::ChangedCurrentAttempt => {
                let mut changed = current.clone();
                changed.owner_epoch += 1;
                replace(
                    &store,
                    attempt_row_key(current.id(), current.attempt()),
                    Some(changed.encode().unwrap()),
                );
            }
        }
        assert!(matches!(
            historical(&store, &aborted),
            Err(StoreError::Corrupt)
        ));
        drop(owner);
    }
}

#[test]
fn current_terminal_abort_rejects_an_unowned_newer_reservation() {
    let (_directory, store, effects) = setup();
    let aborted = aborted(&store, &effects);
    historical(&store, &aborted).unwrap();
    let reservation = LogicalReservation {
        generation: 2,
        bytes: 1,
    };
    replace(
        &store,
        latent_state::reservation::reservation_key(&aborted.id().0).unwrap(),
        Some(reservation.encode_for(aborted.accounted).unwrap()),
    );
    assert!(matches!(
        historical(&store, &aborted),
        Err(StoreError::Corrupt)
    ));
}
