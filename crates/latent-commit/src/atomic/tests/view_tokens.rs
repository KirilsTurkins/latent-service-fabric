use super::*;
use latent_state::{
    embedded::ExpectedRow,
    namespace::history::{history_key, HistoryEpochs, NamespaceHistory},
    session::version::ViewIdentity,
};

fn history(store: &EmbeddedStore, epochs: HistoryEpochs) {
    let view = store.snapshot().unwrap();
    let namespace = NamespaceRecord::decode(&view.get(&namespace_key()).unwrap().unwrap()).unwrap();
    let key = history_key(
        &namespace.tenant,
        &namespace.id,
        namespace.version.incarnation,
    )
    .unwrap();
    let old = view.get(&key).unwrap();
    let mut history = NamespaceHistory::initial(&namespace);
    history.epochs = epochs;
    drop(view);
    store
        .apply(AtomicBatch {
            expectations: vec![ExpectedRow {
                key: key.clone(),
                value: old,
            }],
            mutations: vec![RowMutation {
                key,
                value: Some(history.encode().unwrap()),
            }],
        })
        .unwrap();
}

#[test]
fn actual_original_view_token_survives_history_change_later_commit_and_reopen() {
    let (directory, store, effects) = setup();
    history(
        &store,
        HistoryEpochs {
            schema: 7,
            recovery: 9,
        },
    );
    let request = input("original-epochs");
    let key = request.key.clone();
    let first = claim(&store, request);
    let view = store.snapshot().unwrap();
    let plan = stage(&view);
    let scope = plan.scope().clone();
    let original_token = plan.view_token().unwrap();
    let original = confirm(
        CompleteEnvelope::success_without_intents(
            &view,
            first,
            Some(plan),
            value(b"original"),
            time(101),
        )
        .unwrap(),
        &store,
        &effects,
    );
    drop(view);
    assert_eq!(
        original.committed_view_token(),
        Some(original_token.as_slice())
    );

    // These test-controlled rows prove retention/encoding, not authority to
    // approve a restore. Production still requires the sealed history owner.
    history(
        &store,
        HistoryEpochs {
            schema: 7,
            recovery: 10,
        },
    );
    let next = claim(&store, input("later-epochs"));
    let view = store.snapshot().unwrap();
    let plan = stage(&view);
    let later = plan.view_identity();
    assert_eq!(
        later.require_minimum(&scope, &original_token),
        Err(latent_state::session::StateError::RecoveryRequired)
    );
    confirm(
        CompleteEnvelope::success_without_intents(
            &view,
            next,
            Some(plan),
            value(b"later"),
            time(102),
        )
        .unwrap(),
        &store,
        &effects,
    );
    drop(view);
    drop(store);
    let store = open(&directory.path().join("state.redb"));
    let (replayed, result) =
        inspect(&store.snapshot().unwrap(), &key, time(103), permission).unwrap();
    assert_eq!(replayed, original);
    assert_eq!(result.unwrap().committed_view_token(), original_token);
    assert_eq!(
        ViewIdentity::from_token(&scope, &original_token)
            .unwrap()
            .epochs,
        HistoryEpochs {
            schema: 7,
            recovery: 9
        }
    );
}

#[test]
fn no_state_rejection_and_abort_cas_exact_absent_or_present_history() {
    for abort in [false, true] {
        let (_directory, store, _effects) = setup();
        if abort {
            history(
                &store,
                HistoryEpochs {
                    schema: 3,
                    recovery: 4,
                },
            );
        }
        let request = input(if abort {
            "history-abort"
        } else {
            "history-rejection"
        });
        let key = request.key.clone();
        let claim = claim(&store, request);
        let view = store.snapshot().unwrap();
        let envelope = if abort {
            let retirement = claim.retirement();
            drop(claim);
            CompleteEnvelope::technical_abort(
                &view,
                retirement.proven_noncommit().unwrap(),
                "guest-trap".into(),
                time(101),
            )
            .unwrap()
        } else {
            CompleteEnvelope::rejection(
                &view,
                claim,
                "business-rejected".into(),
                value(b"no-state"),
                time(101),
            )
            .unwrap()
        };
        drop(view);
        history(
            &store,
            HistoryEpochs {
                schema: 5,
                recovery: 6,
            },
        );
        let accepted = std::sync::atomic::AtomicBool::new(false);
        match envelope.publish(&store, |_| {
            accepted.store(true, std::sync::atomic::Ordering::Release);
            Ok(())
        }) {
            PreparedDisposition::KnownNotCommitted {
                command,
                reason: AtomicError::Conflict,
            } => drop(command),
            _ => panic!("changed history must refuse before acceptance"),
        }
        assert!(!accepted.load(std::sync::atomic::Ordering::Acquire));
        assert_eq!(
            inspect(&store.snapshot().unwrap(), &key, time(102), permission)
                .unwrap()
                .0
                .outcome(),
            Outcome::Pending
        );
    }
}

#[test]
fn no_state_rejection_and_abort_cas_exact_absent_or_reviewed_recovery_guard() {
    use latent_state::recovery::{guard_key, RecoveryGuard};

    for present in [false, true] {
        for abort in [false, true] {
            let (_directory, store, _effects) = setup();
            if present {
                let staging = RecoveryGuard::staging([1; 32], [2; 32], [3; 32]).unwrap();
                store.apply(staging.prepare_staging().unwrap()).unwrap();
                store.apply(staging.prepare_completed().unwrap()).unwrap();
                let view = store.snapshot().unwrap();
                let paused = RecoveryGuard::capture(&view).unwrap().unwrap();
                let reviewed = paused
                    .prepare_reviewed(&view, [4; 32], |_, _, _| Ok(()))
                    .unwrap();
                drop(view);
                store.apply(reviewed).unwrap();
            }
            let request = input(if abort {
                "guard-abort"
            } else {
                "guard-rejection"
            });
            let key = request.key.clone();
            let admitted = claim(&store, request);
            let view = store.snapshot().unwrap();
            let envelope = if abort {
                let retirement = admitted.retirement();
                drop(admitted);
                CompleteEnvelope::technical_abort(
                    &view,
                    retirement.proven_noncommit().unwrap(),
                    "guest-trap".into(),
                    time(101),
                )
                .unwrap()
            } else {
                CompleteEnvelope::rejection(
                    &view,
                    admitted,
                    "business-rejected".into(),
                    value(b"no-state"),
                    time(101),
                )
                .unwrap()
            };
            let original = view.get(&guard_key()).unwrap();
            drop(view);

            // Controlled offline-row replacement proves exact CAS. It does not
            // authorize an online restore or grant command/result permission.
            let replacement = RecoveryGuard::staging([5; 32], [6; 32], [7; 32]).unwrap();
            store
                .apply(AtomicBatch {
                    expectations: vec![ExpectedRow {
                        key: guard_key(),
                        value: original,
                    }],
                    mutations: vec![RowMutation {
                        key: guard_key(),
                        value: Some(replacement.encode().unwrap()),
                    }],
                })
                .unwrap();
            let accepted = std::sync::atomic::AtomicBool::new(false);
            match envelope.publish(&store, |_| {
                accepted.store(true, std::sync::atomic::Ordering::Release);
                Ok(())
            }) {
                PreparedDisposition::KnownNotCommitted {
                    command,
                    reason: AtomicError::Conflict,
                } => drop(command),
                _ => panic!("changed recovery guard must refuse before acceptance"),
            }
            assert!(!accepted.load(std::sync::atomic::Ordering::Acquire));
            assert_eq!(
                inspect(&store.snapshot().unwrap(), &key, time(102), permission)
                    .unwrap()
                    .0
                    .outcome(),
                Outcome::Pending
            );
        }
    }
}
