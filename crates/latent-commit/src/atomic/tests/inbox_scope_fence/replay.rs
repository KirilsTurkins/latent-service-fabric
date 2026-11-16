//! Source custody applies to duplicate reads, not only pending/final writers.
use super::*;

fn fenced_claim(store: &EmbeddedStore, scope: &InboxScope) -> AdmittedCommand {
    let view = store.snapshot().unwrap();
    let AdmissionDecision::New(prepared) =
        PreparedAdmission::prepare(&view, request(scope), time(100), permission).unwrap()
    else {
        panic!("expected a new inbox command")
    };
    let prepared = prepared.fence_inbox_scope(&view, scope).unwrap();
    drop(view);
    prepared.publish(store, || Ok(())).unwrap()
}

fn terminal(
    store: &EmbeddedStore,
    effects: &EffectAuthorityOwner,
    scope: &InboxScope,
    rejected: bool,
) -> CommandRecord {
    let claim = fenced_claim(store, scope);
    let view = store.snapshot().unwrap();
    let envelope = if rejected {
        CompleteEnvelope::rejection(
            &view,
            claim,
            "rejected".into(),
            value(b"original"),
            time(101),
        )
    } else {
        CompleteEnvelope::success(
            &view,
            claim,
            Some(stage(&view)),
            vec![intent()],
            value(b"original"),
            effects,
            time(101),
        )
    }
    .unwrap();
    drop(view);
    confirm(envelope, store, effects)
}

#[test]
fn scoped_replay_preserves_success_and_rejection_after_reopen_and_body_expiry() {
    for rejected in [false, true] {
        let (dir, store, effects) = accounted::setup(8);
        let scope = scope();
        install(&store, &scope);
        let original = terminal(&store, &effects, &scope, rejected);
        let input = request(&scope);
        let inbox = input.inbox.as_ref().unwrap();
        let inbox_key = inbox.row_key(&input.key).unwrap();
        let original_inbox = store.snapshot().unwrap().get(&inbox_key).unwrap();
        assert!(original_inbox.is_some());
        drop(store);
        let store = open(&dir.path().join("state.redb"));
        for now in [102, original.result_expires()] {
            let view = store.snapshot().unwrap();
            let (record, result) =
                inspect_inbox(&view, &input.key, inbox, &scope, time(now), permission).unwrap();
            assert_eq!(record.encode().unwrap(), original.encode().unwrap());
            assert_eq!(record.inbox_identity(), Some(inbox));
            if now < original.result_expires() {
                assert_eq!(result.unwrap().value().unwrap().bytes, b"original");
            } else {
                assert!(result.is_none());
            }
            assert_eq!(view.get(&inbox_key).unwrap(), original_inbox);
            assert_eq!(
                view.get(&command_row_key(record.id())).unwrap(),
                Some(original.encode().unwrap())
            );
            for family in [Family::State, Family::Outbox] {
                assert_eq!(
                    view.scan_after(family, b"", None, 128, 1024 * 1024)
                        .unwrap()
                        .rows
                        .len(),
                    usize::from(!rejected)
                );
            }
        }
    }
}

#[test]
fn scoped_replay_refuses_missing_damaged_and_recreated_source_without_changing_history() {
    for variant in 0..3 {
        let (_dir, store, effects) = accounted::setup(8);
        let scope = scope();
        let source = install(&store, &scope);
        let original = terminal(&store, &effects, &scope, true);
        let input = request(&scope);
        let replacement = match variant {
            0 => None,
            1 => Some(b"damaged".to_vec()),
            _ => {
                // Use another actual writer to produce a valid different
                // origin at the same logical-source key, not malformed JSON.
                let (_other_dir, other, _effects) = accounted::setup(8);
                let mut changed = scope.clone();
                changed.stream_created = "2026-02-01T00:00:00Z".into();
                let changed = install(&other, &changed);
                assert_eq!(changed.key, source.key);
                changed.value
            }
        };
        store
            .apply(AtomicBatch {
                expectations: vec![source.clone()],
                mutations: vec![RowMutation {
                    key: source.key.clone(),
                    value: replacement.clone(),
                }],
            })
            .unwrap();
        let view = store.snapshot().unwrap();
        let failure = inspect_inbox(
            &view,
            &input.key,
            input.inbox.as_ref().unwrap(),
            &scope,
            time(102),
            permission,
        )
        .err()
        .unwrap();
        assert_eq!(
            failure,
            if variant == 1 {
                AtomicError::Corrupt
            } else {
                AtomicError::Conflict
            }
        );
        assert_eq!(view.get(&source.key).unwrap(), replacement);
        assert_eq!(
            view.get(&command_row_key(original.id())).unwrap(),
            Some(original.encode().unwrap())
        );
        // The unchanged generic reader is not the trusted trigger reader.
        assert_eq!(
            inspect(&view, &input.key, time(102), permission)
                .unwrap()
                .0
                .encode()
                .unwrap(),
            original.encode().unwrap()
        );
    }
}

#[test]
fn scoped_replay_rejects_source_and_authenticated_input_substitution() {
    let (_dir, store, effects) = accounted::setup(8);
    let scope = scope();
    install(&store, &scope);
    terminal(&store, &effects, &scope, true);
    let input = request(&scope);
    let inbox = input.inbox.as_ref().unwrap();
    let view = store.snapshot().unwrap();
    for field in 0..7 {
        let mut changed = scope.clone();
        match field {
            0 => changed.tenant = "other".into(),
            1 => changed.namespace = "other".into(),
            2 => changed.incarnation = 2,
            3 => changed.processing_scope = "fork".into(),
            4 => changed.provider = "other".into(),
            5 => changed.stream = "other".into(),
            _ => changed.stream_created = "2026-02-01T00:00:00Z".into(),
        }
        assert!(matches!(
            inspect_inbox(&view, &input.key, inbox, &changed, time(102), permission),
            Err(AtomicError::Conflict)
        ));
    }
    for change_message in [false, true] {
        let mut changed = inbox.clone();
        if change_message {
            changed.message = "2".into();
        } else {
            changed.payload_digest = Identity::derive(b"different", &[b"payload"]);
        }
        assert!(matches!(
            inspect_inbox(&view, &input.key, &changed, &scope, time(102), permission),
            Err(AtomicError::Conflict)
        ));
    }
}

#[test]
fn scoped_absence_requires_existing_source_and_authorization_before_observation() {
    let (_dir, store, _effects) = accounted::setup(8);
    let scope = scope();
    let input = request(&scope);
    let inbox = input.inbox.as_ref().unwrap();
    let view = store.snapshot().unwrap();
    let mut calls = 0;
    assert!(matches!(
        inspect_inbox(&view, &input.key, inbox, &scope, time(100), |_, _| {
            calls += 1;
            Err(AtomicError::PermissionDenied)
        }),
        Err(AtomicError::PermissionDenied)
    ));
    assert_eq!(calls, 1);
    assert!(matches!(
        inspect_inbox(&view, &input.key, inbox, &scope, time(100), permission),
        Err(AtomicError::Conflict)
    ));
    drop(view);
    install(&store, &scope);
    let view = store.snapshot().unwrap();
    assert!(matches!(
        inspect_inbox(&view, &input.key, inbox, &scope, time(100), permission),
        Err(AtomicError::NotFound)
    ));
    assert!(view
        .get(&command_row_key(command_identity(&input.key).unwrap()))
        .unwrap()
        .is_none());
}

#[test]
fn existing_source_does_not_replace_current_result_permission_or_clock_continuity() {
    let (_dir, store, effects) = accounted::setup(8);
    let scope = scope();
    install(&store, &scope);
    terminal(&store, &effects, &scope, true);
    let input = request(&scope);
    let inbox = input.inbox.as_ref().unwrap();
    let view = store.snapshot().unwrap();
    let mut calls = 0;
    assert!(matches!(
        inspect_inbox(
            &view,
            &input.key,
            inbox,
            &scope,
            time(102),
            |access, record| {
                calls += 1;
                permission(access, record)?;
                if record.is_some() {
                    Err(AtomicError::PermissionDenied)
                } else {
                    Ok(())
                }
            }
        ),
        Err(AtomicError::PermissionDenied)
    ));
    assert_eq!(calls, 2);
    for observed in [
        time(100),
        CommandTime {
            unix_millis: 102,
            continuity_proven: false,
        },
    ] {
        assert!(matches!(
            inspect_inbox(&view, &input.key, inbox, &scope, observed, permission),
            Err(AtomicError::RecoveryRequired)
        ));
    }
}

#[test]
fn scoped_pending_and_expired_body_replay_refuse_view_expiry_during_authorization() {
    for pending in [false, true] {
        let (dir, store, effects) = accounted::setup(8);
        drop(store);
        let store = open_limited(
            &dir.path().join("state.redb"),
            StoreLimits {
                maximum_view_age: std::time::Duration::from_secs(1),
                ..StoreLimits::default()
            },
        );
        let scope = scope();
        install(&store, &scope);
        let claim = if pending {
            Some(fenced_claim(&store, &scope))
        } else {
            terminal(&store, &effects, &scope, true);
            None
        };
        let input = request(&scope);
        let view = store.snapshot().unwrap();
        assert!(matches!(
            inspect_inbox(
                &view,
                &input.key,
                input.inbox.as_ref().unwrap(),
                &scope,
                time(1100),
                |access, record| {
                    if record.is_some() {
                        std::thread::sleep(std::time::Duration::from_millis(1100));
                    }
                    permission(access, record)
                },
            ),
            Err(AtomicError::Expired)
        ));
        drop(view);
        drop(claim);
    }
}
