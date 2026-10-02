//! Actual engine and physically retired abort schedules. Offline history rows
//! are controlled test inputs, not production restore/checkpoint approval.
use super::*;
use latent_state::{
    embedded::{ExpectedRow, StoreError},
    namespace::history::{history_key, HistoryEpochs, HistoryStatus, NamespaceHistory},
    recovery::{guard_key, RecoveryGuard},
};
use std::sync::atomic::{AtomicBool, Ordering};

fn abort(
    store: &EmbeddedStore,
    effects: &EffectAuthorityOwner,
    original: AdmissionInput,
) -> CommandRecord {
    let admitted = claim(store, original);
    let retirement = admitted.retirement();
    let physical = admitted.physical_work().unwrap();
    drop(admitted);
    assert!(matches!(
        retirement.proven_noncommit(),
        Err(AtomicError::RecoveryRequired)
    ));
    physical.retire();
    confirm(
        CompleteEnvelope::technical_abort(
            &store.snapshot().unwrap(),
            retirement.proven_noncommit().unwrap(),
            "original-physically-retired".into(),
            time(101),
        )
        .unwrap(),
        store,
        effects,
    )
}

fn retry(record: &CommandRecord, request_id: &str) -> RetryRequest {
    RetryRequest {
        request_id: request_id.into(),
        expected_abort: record.abort_proof().unwrap(),
    }
}

fn history(store: &EmbeddedStore, epochs: HistoryEpochs, status: HistoryStatus) {
    let view = store.snapshot().unwrap();
    let namespace = NamespaceRecord::decode(&view.get(&namespace_key()).unwrap().unwrap()).unwrap();
    let key = history_key(&namespace.tenant, &namespace.id, 1).unwrap();
    let previous = view.get(&key).unwrap();
    let mut actual = NamespaceHistory::initial(&namespace);
    actual.epochs = epochs;
    actual.status = status;
    drop(view);
    store
        .apply(AtomicBatch {
            expectations: vec![ExpectedRow {
                key: key.clone(),
                value: previous,
            }],
            mutations: vec![RowMutation {
                key,
                value: Some(actual.encode().unwrap()),
            }],
        })
        .unwrap();
}

fn reviewed_guard(store: &EmbeddedStore) {
    let staging = RecoveryGuard::staging([31; 32], [32; 32], [33; 32]).unwrap();
    store.apply(staging.prepare_staging().unwrap()).unwrap();
    store.apply(staging.prepare_completed().unwrap()).unwrap();
    let view = store.snapshot().unwrap();
    let paused = RecoveryGuard::capture(&view).unwrap().unwrap();
    let reviewed = paused
        .prepare_reviewed(&view, [34; 32], |_, _, _| Ok(()))
        .unwrap();
    drop(view);
    store.apply(reviewed).unwrap();
}

fn assert_original(store: &EmbeddedStore, original: &CommandRecord) {
    let view = store.snapshot().unwrap();
    assert_eq!(
        CommandRecord::decode(&view.get(&command_row_key(original.id())).unwrap().unwrap())
            .unwrap(),
        *original
    );
    assert!(view
        .get(&attempt_row_key(original.id(), original.attempt() + 1))
        .unwrap()
        .is_none());
    assert!(view
        .get(&result_row_key(original.id(), original.attempt() + 1))
        .unwrap()
        .is_none());
}

#[test]
fn same_history_generation_advance_preserves_original_explicit_retry_and_fingerprint() {
    let (_directory, store, effects) = setup();
    let request = input("same-history-retry");
    let original = abort(&store, &effects, input("same-history-retry"));
    let later = claim(&store, input("unrelated-generation"));
    confirm(
        CompleteEnvelope::success_without_intents(
            &store.snapshot().unwrap(),
            later,
            None,
            value(b"later business state"),
            time(102),
        )
        .unwrap(),
        &store,
        &effects,
    );
    let view = store.snapshot().unwrap();
    let current = NamespaceRecord::decode(&view.get(&namespace_key()).unwrap().unwrap()).unwrap();
    assert!(current.version.generation > original.committed_version().unwrap().generation);
    let AdmissionDecision::New(prepared) = PreparedAdmission::retry(
        &view,
        &request,
        &retry(&original, "original-retry-operation"),
        time(103),
        permission,
    )
    .unwrap() else {
        panic!("original same-history retry must prepare")
    };
    drop(view);
    let admitted = prepared.publish(&store, || Ok(())).unwrap();
    assert_eq!(admitted.record().fingerprint(), original.fingerprint());
    assert_eq!(admitted.record().key(), original.key());
    assert_eq!(admitted.record().source(), original.source());
    assert_eq!(admitted.record().attempt(), 2);
    drop(admitted);
}

#[test]
fn restored_or_schema_changed_abort_refuses_new_attempt_without_rewriting_historical_result() {
    for epochs in [
        HistoryEpochs {
            schema: 1,
            recovery: 2,
        },
        HistoryEpochs {
            schema: 2,
            recovery: 1,
        },
    ] {
        let (directory, store, effects) = setup();
        let request = input("older-abort-history");
        let original = abort(&store, &effects, input("older-abort-history"));
        let view = store.snapshot().unwrap();
        let original_result = view
            .get(&result_row_key(original.id(), original.attempt()))
            .unwrap()
            .unwrap();
        drop(view);
        reviewed_guard(&store);
        history(&store, epochs, HistoryStatus::Ready);
        drop(store);
        let store = open(&directory.path().join("state.redb"));
        let view = store.snapshot().unwrap();
        assert!(matches!(
            PreparedAdmission::retry(
                &view,
                &request,
                &retry(&original, "unsafe-after-older-history"),
                time(102),
                permission
            ),
            Err(AtomicError::RecoveryRequired)
        ));
        let (record, result) = inspect(&view, original.key(), time(102), permission).unwrap();
        assert_eq!(record, original);
        assert_eq!(result.unwrap().outcome(), Outcome::Aborted);
        assert_eq!(
            view.get(&result_row_key(original.id(), original.attempt()))
                .unwrap()
                .unwrap(),
            original_result
        );
        drop(view);
        assert_original(&store, &original);
    }
}

#[test]
fn positively_aborted_fresh_work_in_reviewed_current_history_can_retry() {
    let (_directory, store, effects) = setup();
    reviewed_guard(&store);
    history(
        &store,
        HistoryEpochs {
            schema: 7,
            recovery: 9,
        },
        HistoryStatus::Ready,
    );
    let original = abort(&store, &effects, input("new-after-review"));
    let view = store.snapshot().unwrap();
    let AdmissionDecision::New(prepared) = PreparedAdmission::retry(
        &view,
        &input("new-after-review"),
        &retry(&original, "fresh-original-proof"),
        time(102),
        permission,
    )
    .unwrap() else {
        panic!("current-history physical proof must remain usable")
    };
    drop(view);
    let admitted = prepared.publish(&store, || Ok(())).unwrap();
    assert_eq!(admitted.record().attempt(), 2);
    drop(admitted);
}

#[test]
fn concurrent_history_publication_refuses_retry_before_acceptance_with_absent_or_present_row() {
    for present in [false, true] {
        let (_directory, store, effects) = setup();
        if present {
            history(&store, HistoryEpochs::default(), HistoryStatus::Ready);
        }
        let original = abort(&store, &effects, input("history-racing-retry"));
        let view = store.snapshot().unwrap();
        let AdmissionDecision::New(prepared) = PreparedAdmission::retry(
            &view,
            &input("history-racing-retry"),
            &retry(&original, "original-racing-retry"),
            time(102),
            permission,
        )
        .unwrap() else {
            panic!("original view must prepare")
        };
        drop(view);
        history(
            &store,
            if present {
                HistoryEpochs {
                    schema: 1,
                    recovery: 2,
                }
            } else {
                // Publishing even the supported default epoch1 must respect
                // the originally captured absent-row expectation.
                HistoryEpochs::default()
            },
            HistoryStatus::Ready,
        );
        let accepted = AtomicBool::new(false);
        assert!(matches!(
            prepared.publish(&store, || {
                accepted.store(true, Ordering::Release);
                Ok(())
            }),
            Err(AtomicError::Conflict)
        ));
        assert!(!accepted.load(Ordering::Acquire));
        assert_original(&store, &original);
    }
}

#[test]
fn paused_or_changed_recovery_guard_blocks_new_retry_and_accepted_write_race() {
    for present in [false, true] {
        let (_directory, store, effects) = setup();
        if present {
            reviewed_guard(&store);
        }
        let original = abort(&store, &effects, input("guard-racing-retry"));
        let view = store.snapshot().unwrap();
        let AdmissionDecision::New(prepared) = PreparedAdmission::retry(
            &view,
            &input("guard-racing-retry"),
            &retry(&original, "original-guard-retry"),
            time(102),
            permission,
        )
        .unwrap() else {
            panic!("ready original guard must prepare")
        };
        let previous = view.get(&guard_key()).unwrap();
        drop(view);
        let replacement = RecoveryGuard::staging([41; 32], [42; 32], [43; 32]).unwrap();
        store
            .apply(AtomicBatch {
                expectations: vec![ExpectedRow {
                    key: guard_key(),
                    value: previous,
                }],
                mutations: vec![RowMutation {
                    key: guard_key(),
                    value: Some(replacement.encode().unwrap()),
                }],
            })
            .unwrap();
        let accepted = AtomicBool::new(false);
        assert!(matches!(
            prepared.publish(&store, || {
                accepted.store(true, Ordering::Release);
                Ok(())
            }),
            Err(AtomicError::Conflict)
        ));
        assert!(!accepted.load(Ordering::Acquire));
        assert!(matches!(
            PreparedAdmission::retry(
                &store.snapshot().unwrap(),
                &input("guard-racing-retry"),
                &retry(&original, "another-unsafe-retry"),
                time(103),
                permission
            ),
            Err(AtomicError::RecoveryRequired)
        ));
        assert_original(&store, &original);
        assert_eq!(
            latent_state::recovery::require_ready(&store.snapshot().unwrap()),
            Err(StoreError::Unavailable)
        );
    }
}

#[test]
fn historical_retry_receipt_survives_restore_with_current_access_and_no_new_attempt() {
    let (_directory, store, effects) = setup();
    let original = abort(&store, &effects, input("receipt-after-restore"));
    let request = retry(&original, "accepted-original-retry");
    let view = store.snapshot().unwrap();
    let AdmissionDecision::New(prepared) = PreparedAdmission::retry(
        &view,
        &input("receipt-after-restore"),
        &request,
        time(102),
        permission,
    )
    .unwrap() else {
        panic!("original retry must prepare")
    };
    drop(view);
    let admitted = prepared.publish(&store, || Ok(())).unwrap();
    let terminal = confirm(
        CompleteEnvelope::success_without_intents(
            &store.snapshot().unwrap(),
            admitted,
            None,
            value(b"actual original completion"),
            time(103),
        )
        .unwrap(),
        &store,
        &effects,
    );
    reviewed_guard(&store);
    history(
        &store,
        HistoryEpochs {
            schema: 1,
            recovery: 2,
        },
        HistoryStatus::Ready,
    );
    let view = store.snapshot().unwrap();
    let AdmissionDecision::Existing(replayed) = PreparedAdmission::retry(
        &view,
        &input("receipt-after-restore"),
        &request,
        time(104),
        permission,
    )
    .unwrap() else {
        panic!("historical receipt must remain a read only result")
    };
    assert_eq!(replayed, terminal);
    assert!(matches!(
        PreparedAdmission::retry(
            &view,
            &input("receipt-after-restore"),
            &request,
            time(104),
            |_, _| Err(AtomicError::PermissionDenied)
        ),
        Err(AtomicError::PermissionDenied)
    ));
    assert!(view
        .get(&attempt_row_key(terminal.id(), 3))
        .unwrap()
        .is_none());
}
