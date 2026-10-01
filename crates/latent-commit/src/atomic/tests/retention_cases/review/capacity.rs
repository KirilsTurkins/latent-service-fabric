use super::*;

fn clock_permission(key: &CommandKey) -> Result<(), AtomicError> {
    if key.tenant == "tenant" && key.namespace == "aggregate" && key.incarnation == "1" {
        Ok(())
    } else {
        Err(AtomicError::PermissionDenied)
    }
}

#[test]
fn reserved_inline_review_completes_at_original_six_row_capacity_without_global_progress_row() {
    let (dir, store, effects) = setup();
    drop(store);
    let store = open_limited(
        &dir.path().join("state.redb"),
        StoreLimits {
            maximum_rows: 6,
            ..StoreLimits::default()
        },
    );
    let mut admitted = input("full-review");
    admitted.inbox = Some(InboxIdentity {
        provider: "events".into(),
        binding: "source".into(),
        message: "full-review".into(),
        payload_digest: Identity::derive(b"input", &[b"full-review"]),
    });
    let owner = claim(&store, admitted);
    let record = confirm(
        CompleteEnvelope::rejection(
            &store.snapshot().unwrap(),
            owner,
            "rejected".into(),
            value(b"original retained rejection"),
            time(101),
        )
        .unwrap(),
        &store,
        &effects,
    );
    let maintenance = ResultMaintenanceOwner::default();
    let view = store.snapshot().unwrap();
    let AdmissionDecision::New(next) =
        PreparedAdmission::prepare(&view, input("refused"), time(102), permission).unwrap()
    else {
        panic!("new command must need rows");
    };
    assert!(matches!(
        next.publish(&store, || panic!("quota must precede acceptance")),
        Err(AtomicError::Limit)
    ));
    assert!(view.get(&MaintenanceProgress::key()).unwrap().is_none());
    drop(view);
    let quota = writer::usage_row_key(&record.key.tenant, &record.key.namespace, 1).unwrap();
    let before = store.snapshot().unwrap().get(&quota).unwrap().unwrap();
    maintenance
        .anchor_review(
            &store,
            &record.key,
            None,
            observation(2100, 0),
            clock_permission,
        )
        .unwrap();
    assert!(
        maintenance
            .terminalize(&store, &request(&record), observation(2200, 100), authorize)
            .unwrap()
            .complete
    );
    let view = store.snapshot().unwrap();
    let (usage, _, bytes) = writer::Usage::read(&view, &record.key).unwrap();
    assert_eq!(bytes.unwrap().len(), before.len());
    assert_eq!(before.len(), latent_state::reservation::QUOTA_BYTES);
    assert_eq!((usage.reserved, usage.recovery_reserved), (0, 0));
    assert!(view.get(&MaintenanceProgress::key()).unwrap().is_none());
    validate_view(&view, foreign_codec).unwrap();
    drop(view);
    assert!(
        maintenance
            .purge(&store, &request(&record), observation(2300, 200), authorize)
            .unwrap()
            .complete
    );
    drop(store);
    let store = open_limited(
        &dir.path().join("state.redb"),
        StoreLimits {
            maximum_rows: 6,
            ..StoreLimits::default()
        },
    );
    let view = store.snapshot().unwrap();
    validate_view(&view, foreign_codec).unwrap();
    assert!(matches!(
        inspect(&view, &record.key, time(2301), permission),
        Err(AtomicError::Expired)
    ));
    let (usage, _, _) = writer::Usage::read(&view, &record.key).unwrap();
    assert_eq!((usage.results, usage.effects, usage.reserved), (1, 0, 0));
}

#[test]
fn namespace_review_reanchor_requires_current_policy_exact_generation_and_original_horizons() {
    let (_dir, store, effects) = setup();
    let record = completed(&store, &effects, "review-boot");
    let owner = ResultMaintenanceOwner::default();
    owner
        .anchor_review(
            &store,
            &record.key,
            None,
            observation(2100, 0),
            clock_permission,
        )
        .unwrap();
    let request = request(&record);
    owner
        .terminalize(&store, &request, observation(2200, 100), authorize)
        .unwrap();
    let before = super::adversarial::checkpoint(&store, &record);
    let mut new_boot = observation(2201, 0);
    new_boot.boot = [8; 32];
    assert_eq!(
        owner.purge(&store, &request, new_boot, authorize),
        Err(AtomicError::RecoveryRequired)
    );
    assert_eq!(
        owner.anchor_review(&store, &record.key, Some(1), new_boot, clock_permission),
        Err(AtomicError::Conflict)
    );
    let mut calls = 0;
    assert_eq!(
        owner.anchor_review(&store, &record.key, Some(2), new_boot, |key| {
            calls += 1;
            if calls == 2 {
                Err(AtomicError::PermissionDenied)
            } else {
                clock_permission(key)
            }
        }),
        Err(AtomicError::PermissionDenied)
    );
    assert_eq!(calls, 2);
    assert_eq!(super::adversarial::checkpoint(&store, &record), before);
    let anchor = owner
        .anchor_review(&store, &record.key, Some(2), new_boot, clock_permission)
        .unwrap();
    assert_eq!(
        (anchor.generation, anchor.visited, anchor.retired),
        (3, 1, 0)
    );
    let mut early = observation(2299, 98);
    early.boot = [8; 32];
    assert_eq!(
        owner.purge(&store, &request, early, authorize),
        Err(AtomicError::Expired)
    );
    let mut eligible = observation(2300, 99);
    eligible.boot = [8; 32];
    assert_eq!(
        owner
            .purge(&store, &request, eligible, authorize)
            .unwrap()
            .purged_effects,
        1
    );
    let view = store.snapshot().unwrap();
    let stored = CommandRecord::decode(
        &view
            .get(&record::command_row_key(record.id))
            .unwrap()
            .unwrap(),
    )
    .unwrap();
    assert_eq!(
        (
            stored.result_expires,
            stored.identity_expires,
            stored.source
        ),
        (
            record.result_expires,
            record.identity_expires,
            record.source
        )
    );
}

#[test]
fn legacy_accounting_remains_readable_without_granting_an_implicit_destructive_upgrade() {
    let (_dir, store, effects) = setup();
    let owner = claim(&store, input("legacy-review"));
    let mut record = confirm(
        CompleteEnvelope::rejection(
            &store.snapshot().unwrap(),
            owner,
            "legacy".into(),
            value(b"legacy result"),
            time(101),
        )
        .unwrap(),
        &store,
        &effects,
    );
    record.accounted = false;
    let view = store.snapshot().unwrap();
    let (mut usage, quota, _) = writer::Usage::read(&view, &record.key).unwrap();
    usage.accounted = false;
    usage.result_bytes = result_bytes(&store, &record).len() as u64;
    usage.reserved = 0;
    usage.recovery_reserved = 0;
    drop(view);
    store
        .apply(AtomicBatch {
            expectations: vec![],
            mutations: vec![
                RowMutation {
                    key: record::command_row_key(record.id),
                    value: Some(record.encode().unwrap()),
                },
                RowMutation {
                    key: record::attempt_row_key(record.id, record.attempt),
                    value: Some(record.encode().unwrap()),
                },
                RowMutation {
                    key: quota,
                    value: Some(usage.encode().unwrap()),
                },
            ],
        })
        .unwrap();
    validate_view(&store.snapshot().unwrap(), foreign_codec).unwrap();
    let maintenance = ResultMaintenanceOwner::default();
    let before = super::adversarial::checkpoint(&store, &record);
    assert_eq!(
        maintenance.anchor_review(
            &store,
            &record.key,
            None,
            observation(2100, 0),
            clock_permission
        ),
        Err(AtomicError::UnsupportedFormat)
    );
    assert_eq!(
        maintenance.terminalize(&store, &request(&record), observation(2200, 100), authorize),
        Err(AtomicError::UnsupportedFormat)
    );
    assert_eq!(super::adversarial::checkpoint(&store, &record), before);
    let (_, original) = inspect(
        &store.snapshot().unwrap(),
        &record.key,
        time(102),
        permission,
    )
    .unwrap();
    assert_eq!(original.unwrap().value(), Some(&value(b"legacy result")));
}

#[test]
fn forged_quota_padding_and_mixed_reservation_formats_fail_coherent_startup() {
    let (_dir, store, _) = setup();
    let owner = claim(&store, input("mixed-pending"));
    let view = store.snapshot().unwrap();
    let key = latent_state::reservation::reservation_key(&owner.record().id.bytes()).unwrap();
    let bytes = view.get(&key).unwrap().unwrap();
    let amount = latent_state::reservation::LogicalReservation::decode(&bytes).unwrap();
    drop(view);
    store
        .apply(AtomicBatch {
            expectations: vec![],
            mutations: vec![RowMutation {
                key: key.clone(),
                value: Some(amount.encode().unwrap()),
            }],
        })
        .unwrap();
    assert_eq!(
        validate_view(&store.snapshot().unwrap(), foreign_codec),
        Err(latent_state::embedded::StoreError::Corrupt)
    );
    store
        .apply(AtomicBatch {
            expectations: vec![],
            mutations: vec![RowMutation {
                key,
                value: Some(bytes),
            }],
        })
        .unwrap();
    let view = store.snapshot().unwrap();
    let (_, quota, old) = writer::Usage::read(&view, owner.record().key()).unwrap();
    let mut forged = old.unwrap();
    *forged.last_mut().unwrap() = 1;
    drop(view);
    store
        .apply(AtomicBatch {
            expectations: vec![],
            mutations: vec![RowMutation {
                key: quota,
                value: Some(forged),
            }],
        })
        .unwrap();
    assert_eq!(
        validate_view(&store.snapshot().unwrap(), foreign_codec),
        Err(latent_state::embedded::StoreError::Corrupt)
    );
}
