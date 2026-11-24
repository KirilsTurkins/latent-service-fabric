use super::*;

#[test]
fn reviewed_result_pass_resumes_after_reopen_and_refuses_stale_generation() {
    let (directory, store, effects) = setup();
    let first = completed(&store, &effects, "reviewed-body-first");
    let second = completed(&store, &effects, "reviewed-body-second");
    let due = first.result_expires().max(second.result_expires()) + 1;
    let owner = ResultMaintenanceOwner::default();
    let reader = store.snapshot().unwrap();
    assert_eq!(
        owner.reviewed_step(&store, observation(due, 0), None, maintenance),
        Err(AtomicError::Limit)
    );
    assert_eq!(MaintenanceProgress::inspect(&reader).unwrap(), None);
    drop(reader);

    let progress = owner
        .reviewed_step(&store, observation(due, 0), None, maintenance)
        .unwrap();
    assert_eq!(progress.generation, 1);
    assert_eq!(progress.retired, 1);
    assert!(progress.cursor.is_some());
    drop(store);

    let store = open(&directory.path().join("state.redb"));
    let rebooted = MaintenanceClock {
        boot: [8; 32],
        ..observation(due + 1, 0)
    };
    assert_eq!(
        owner.reviewed_step(&store, rebooted, None, maintenance),
        Err(AtomicError::Conflict)
    );
    let progress = owner
        .reviewed_step(&store, rebooted, Some(progress.generation), maintenance)
        .unwrap();
    assert_eq!(progress.generation, 2);
    assert_eq!(progress.visited, 2);
    assert_eq!(progress.retired, 2);
    assert!(progress.cursor.is_none());
    let view = store.snapshot().unwrap();
    for command in [first, second] {
        let key = command_row_key(command.id);
        let original = view.get(&key).unwrap().unwrap();
        assert!(result_bytes(&store, &command).starts_with(b"LCE\0\x01"));
        validate_linked_row(&view, &key, &original).unwrap();
    }
}

#[test]
fn reviewed_point_expiry_is_namespace_scoped_and_does_not_advance_the_sweep_cursor() {
    use crate::atomic::retention::ScopedResultBody;
    use latent_state::recovery::namespace_resume::NamespaceRecoveryView;

    let (_directory, store, effects) = setup();
    let first = completed(&store, &effects, "point-expiry-first");
    let second = completed(&store, &effects, "point-expiry-second");
    let (swept, targeted) = if first.id.hex() < second.id.hex() {
        (first, second)
    } else {
        (second, first)
    };
    let view = store.snapshot().unwrap();
    let selected = NamespaceRecoveryView::capture(
        &view,
        &TenantId("tenant".into()),
        &StateNamespaceId("aggregate".into()),
    )
    .unwrap();
    let mut foreign = selected.namespace.clone();
    foreign.id = StateNamespaceId("other-namespace".into());
    drop(view);
    store
        .apply(AtomicBatch {
            expectations: vec![],
            mutations: vec![RowMutation {
                key: RowKey {
                    family: Family::Namespace,
                    key: namespace_record_key(&foreign.tenant, &foreign.id).unwrap(),
                },
                value: Some(foreign.encode().unwrap()),
            }],
        })
        .unwrap();
    let view = store.snapshot().unwrap();
    let other = NamespaceRecoveryView::capture(&view, &foreign.tenant, &foreign.id).unwrap();
    let effect_key =
        latent_effects::dispatch_store::effect_row_key(&targeted.effects[0].hex()).unwrap();
    let linked_effect = view.get(&effect_key).unwrap().unwrap();
    drop(view);
    let owner = ResultMaintenanceOwner::default();
    let due = targeted.result_expires().max(swept.result_expires()) + 1;
    let first_page = owner
        .reviewed_step(&store, observation(due, 0), None, maintenance)
        .unwrap();
    assert!(result_bytes(&store, &swept).starts_with(b"LCE\0\x01"));
    let original = result_bytes(&store, &targeted);
    let select = |scope: &NamespaceRecoveryView, expected_generation| {
        let expected_view = scope.view_token().unwrap();
        owner.expire_reviewed_body(
            &store,
            observation(due + 1, 1),
            ScopedResultBody {
                command: targeted.id,
                namespace: &scope.namespace,
                expected_view: &expected_view,
                expected_generation,
            },
            maintenance,
        )
    };
    assert_eq!(
        select(&other, Some(first_page.generation)),
        Err(AtomicError::NotFound)
    );
    assert_eq!(select(&selected, None), Err(AtomicError::Conflict));
    assert_eq!(result_bytes(&store, &targeted), original);
    let (generation, reclaimed) = select(&selected, Some(first_page.generation)).unwrap();
    let marker = result_bytes(&store, &targeted);
    assert!(marker.starts_with(b"LCE\0\x01"));
    assert_eq!(reclaimed, (original.len() - marker.len()) as u64);
    let view = store.snapshot().unwrap();
    let progress = MaintenanceProgress::inspect(&view).unwrap().unwrap();
    assert_eq!(progress.generation, generation);
    assert_eq!(progress.cursor, first_page.cursor);
    assert_eq!(view.get(&effect_key).unwrap().unwrap(), linked_effect);
    let key = command_row_key(targeted.id);
    validate_linked_row(&view, &key, &view.get(&key).unwrap().unwrap()).unwrap();
}

#[test]
fn quota_read_bounds_corrupt_rows_and_preserves_small_legacy_stores() {
    let root = tempfile::tempdir().unwrap();
    let row = RowKey {
        family: Family::Maintenance,
        key: b"quota-bound-test".to_vec(),
    };
    let open = |name: &str, limits| {
        EmbeddedStore::open_file(
            OpenOptions::new()
                .read(true)
                .write(true)
                .create_new(true)
                .open(root.path().join(name))
                .unwrap(),
            limits,
        )
        .unwrap()
    };
    let small = open(
        "legacy.redb",
        StoreLimits {
            maximum_value_bytes: 128,
            ..StoreLimits::default()
        },
    );
    let mut legacy = b"LCU\0\x01".to_vec();
    legacy.extend_from_slice(&[0; 56]);
    small
        .apply(AtomicBatch {
            expectations: vec![],
            mutations: vec![RowMutation {
                key: row.clone(),
                value: Some(legacy.clone()),
            }],
        })
        .unwrap();
    let view = small.snapshot().unwrap();
    let (usage, _, original) = writer::Usage::read_row(&view, row.clone()).unwrap();
    assert!(!usage.accounted);
    assert_eq!(original, Some(legacy));

    let large = open("corrupt.redb", StoreLimits::default());
    large
        .apply(AtomicBatch {
            expectations: vec![],
            mutations: vec![RowMutation {
                key: row.clone(),
                value: Some(vec![0; latent_state::reservation::QUOTA_BYTES + 1]),
            }],
        })
        .unwrap();
    let view = large.snapshot().unwrap();
    assert!(matches!(
        writer::Usage::read_row(&view, row),
        Err(AtomicError::Corrupt)
    ));
}

#[test]
fn repeated_small_wall_only_jumps_hold_response_expiry_across_progress_reopen() {
    let (dir, store, effects) = setup();
    let record = completed(&store, &effects, "cumulative-clock-drift");
    let owner = ResultMaintenanceOwner::default();
    owner
        .anchor(&store, None, observation(100, 0), maintenance)
        .unwrap();
    let body = result_bytes(&store, &record);
    let progress = owner
        .step(&store, observation(1000, 0), maintenance)
        .unwrap();
    assert_eq!(progress.retired, 0);
    assert_eq!(result_bytes(&store, &record), body);
    drop(store);

    let reopened = open(&dir.path().join("state.redb"));
    let owner = ResultMaintenanceOwner::default();
    assert_eq!(
        owner.step(&reopened, observation(1900, 0), maintenance),
        Err(AtomicError::RecoveryRequired)
    );
    assert_eq!(result_bytes(&reopened, &record), body);
    let checkpoint = reopened
        .snapshot()
        .unwrap()
        .get(&MaintenanceProgress::key())
        .unwrap()
        .unwrap();
    assert_eq!(MaintenanceProgress::decode(&checkpoint).unwrap(), progress);
    owner
        .step(&reopened, observation(1900, 1800), maintenance)
        .unwrap();
    assert!(result_bytes(&reopened, &record).starts_with(b"LCE\0\x01"));
}

#[test]
fn uncertain_boot_regression_forward_jump_and_overflow_hold_all_retained_responses() {
    let (_dir, store, effects) = setup();
    let record = completed(&store, &effects, "clock-hold");
    let owner = ResultMaintenanceOwner::default();
    owner
        .anchor(&store, None, observation(1000, 10), maintenance)
        .unwrap();
    let body = result_bytes(&store, &record);
    let samples = [
        observation(999, 11),
        observation(10_000, 11),
        observation(1100, 9),
        observation(u64::MAX, u64::MAX),
        MaintenanceClock {
            boot: [8; 32],
            ..observation(1100, 110)
        },
        MaintenanceClock {
            time: CommandTime {
                unix_millis: 1100,
                continuity_proven: false,
            },
            ..observation(1100, 110)
        },
    ];
    for sample in samples {
        assert_eq!(
            owner.step(&store, sample, maintenance),
            Err(AtomicError::RecoveryRequired)
        );
        assert_eq!(result_bytes(&store, &record), body);
    }
    let progress = owner
        .step(&store, observation(1100, 110), maintenance)
        .unwrap();
    assert_eq!(progress.retired, 1);
    assert!(matches!(
        inspect(
            &store.snapshot().unwrap(),
            &record.key,
            time(1099),
            permission
        ),
        Err(AtomicError::RecoveryRequired)
    ));
}

#[test]
fn boot_recovery_requires_exact_authorized_anchor_and_does_not_extend_original_horizons() {
    let (_dir, store, effects) = setup();
    let record = completed(&store, &effects, "boot-anchor");
    let owner = ResultMaintenanceOwner::default();
    let initial = owner
        .anchor(&store, None, observation(1000, 0), maintenance)
        .unwrap();
    let body = result_bytes(&store, &record);
    let boot = MaintenanceClock {
        boot: [8; 32],
        ..observation(1100, 0)
    };
    assert_eq!(
        owner.anchor(&store, Some(initial.generation), boot, |_| Err(
            AtomicError::PermissionDenied
        )),
        Err(AtomicError::PermissionDenied)
    );
    assert_eq!(
        owner.anchor(&store, Some(initial.generation + 1), boot, maintenance),
        Err(AtomicError::Conflict)
    );
    let reanchored = owner
        .anchor(&store, Some(initial.generation), boot, maintenance)
        .unwrap();
    assert_eq!(result_bytes(&store, &record), body);
    assert_eq!(reanchored.retired, 0);
    owner
        .step(
            &store,
            MaintenanceClock {
                monotonic_millis: 1,
                time: time(1101),
                ..boot
            },
            maintenance,
        )
        .unwrap();
    let (protected, response) = inspect(
        &store.snapshot().unwrap(),
        &record.key,
        time(1101),
        permission,
    )
    .unwrap();
    assert!(response.is_none());
    assert_eq!(protected.result_expires, 1100);
    assert_eq!(protected.identity_expires, 2100);
}

#[test]
fn same_boot_reanchor_cannot_renew_cumulative_drift_tolerance() {
    let (_dir, store, effects) = setup();
    let record = completed(&store, &effects, "reanchor-clock-drift");
    let owner = ResultMaintenanceOwner::default();
    owner
        .anchor(&store, None, observation(100, 0), maintenance)
        .unwrap();
    let body = result_bytes(&store, &record);
    let first = owner
        .step(&store, observation(1000, 0), maintenance)
        .unwrap();
    let reanchored = owner
        .anchor(
            &store,
            Some(first.generation),
            observation(1000, 0),
            maintenance,
        )
        .unwrap();
    assert_eq!(
        owner.step(&store, observation(1900, 0), maintenance),
        Err(AtomicError::RecoveryRequired)
    );
    assert_eq!(
        owner.anchor(
            &store,
            Some(reanchored.generation),
            observation(1900, 0),
            maintenance
        ),
        Err(AtomicError::RecoveryRequired)
    );
    assert_eq!(result_bytes(&store, &record), body);
    assert_eq!(reanchored.anchor_unix_millis, 100);
    assert_eq!(reanchored.anchor_monotonic_millis, 0);
    let resumed = owner
        .anchor(
            &store,
            Some(reanchored.generation),
            observation(70_100, 70_000),
            maintenance,
        )
        .unwrap();
    assert_eq!(resumed.anchor_unix_millis, 100);
    assert_eq!(
        owner.anchor(
            &store,
            Some(resumed.generation),
            observation(70_099, 70_001),
            maintenance
        ),
        Err(AtomicError::RecoveryRequired)
    );
    assert_eq!(
        owner.anchor(
            &store,
            Some(resumed.generation),
            observation(70_101, 69_999),
            maintenance
        ),
        Err(AtomicError::RecoveryRequired)
    );
    let persisted = store
        .snapshot()
        .unwrap()
        .get(&MaintenanceProgress::key())
        .unwrap()
        .unwrap();
    assert_eq!(MaintenanceProgress::decode(&persisted).unwrap(), resumed);
    owner
        .step(&store, observation(70_101, 70_001), maintenance)
        .unwrap();
    assert!(result_bytes(&store, &record).starts_with(b"LCE\0\x01"));
}
