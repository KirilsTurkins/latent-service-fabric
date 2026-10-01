use super::*;
use latent_state::namespace::{catalog::NamespaceCatalog, NamespaceError, NamespaceTransition};

fn floor(store: &EmbeddedStore, effects: &EffectAuthorityOwner, key: &str) -> CommandRecord {
    let record = completed(store, effects, key);
    let owner = ResultMaintenanceOwner::default();
    anchor(&owner, store);
    let request = request(&record);
    owner
        .terminalize(store, &request, observation(2200, 100), authorize)
        .unwrap();
    assert!(
        !owner
            .purge(store, &request, observation(2300, 200), authorize)
            .unwrap()
            .complete
    );
    assert!(
        owner
            .purge(store, &request, observation(2301, 201), authorize)
            .unwrap()
            .complete
    );
    record
}
fn retire(store: &EmbeddedStore) -> NamespaceRecord {
    let view = store.snapshot().unwrap();
    let bytes = view.get(&namespace_key()).unwrap().unwrap();
    let record = NamespaceRecord::decode(&bytes).unwrap();
    let quiescing = record
        .transition(record.version, &NamespaceTransition::Quiesce, 0)
        .unwrap();
    let retired = quiescing
        .transition(quiescing.version, &NamespaceTransition::Retire, 0)
        .unwrap();
    drop(view);
    store
        .apply(AtomicBatch {
            expectations: vec![latent_state::embedded::ExpectedRow {
                key: namespace_key(),
                value: Some(bytes),
            }],
            mutations: vec![RowMutation {
                key: namespace_key(),
                value: Some(retired.encode().unwrap()),
            }],
        })
        .unwrap();
    retired
}
fn release_request(namespace: &NamespaceRecord, command: Identity) -> FloorReleaseRequest {
    FloorReleaseRequest {
        tenant: namespace.tenant.clone(),
        namespace: namespace.id.clone(),
        expected: namespace.version,
        command,
    }
}

#[test]
fn expired_command_floor_requires_real_native_reader_and_namespace_handle_retirement() {
    let (_dir, store, effects) = setup();
    let record = floor(&store, &effects, "floor-owner-drain");
    let namespace = retire(&store);
    let request = release_request(&namespace, record.id);
    let maintenance = ResultMaintenanceOwner::default();
    let catalog = NamespaceCatalog::new();
    let view = store.snapshot().unwrap();
    let read = NamespaceCatalog::read_in(&view, &namespace.tenant, &namespace.id)
        .unwrap()
        .unwrap();
    let handle = catalog.lifecycle().pin(&read).unwrap();
    let prepared = maintenance
        .prepare_floor_release(&view, &request, observation(2302, 202))
        .unwrap();
    assert_eq!(
        prepared.publish(&store, |_, _, _| panic!(
            "a live native view precedes host acceptance"
        )),
        Err(AtomicError::Limit)
    );
    assert!(view.get(&command_row_key(record.id)).unwrap().is_some());
    drop(view);
    let view = store.snapshot().unwrap();
    let prepared = maintenance
        .prepare_floor_release(&view, &request, observation(2302, 202))
        .unwrap();
    drop(view);
    assert_eq!(
        prepared.publish(&store, |before, after, _| {
            assert_eq!(before, read.record());
            assert!(matches!(
                catalog.lifecycle().begin_transition(&read, after, true),
                Err(NamespaceError::InUse)
            ));
            Err(AtomicError::InProgress)
        }),
        Err(AtomicError::InProgress)
    );
    assert_eq!(catalog.lifecycle().retained_owners(), 1);
    drop(handle);
    assert_eq!(catalog.lifecycle().retained_owners(), 0);
    let view = store.snapshot().unwrap();
    let prepared = maintenance
        .prepare_floor_release(&view, &request, observation(2302, 202))
        .unwrap();
    drop(view);
    let mut completion = None;
    let after = prepared
        .publish(&store, |before, after, floor| {
            assert_eq!(before, read.record());
            assert_eq!(floor.id(), record.id);
            completion = Some(
                catalog
                    .lifecycle()
                    .begin_transition(&read, after, true)
                    .unwrap(),
            );
            Ok(())
        })
        .unwrap();
    let view = store.snapshot().unwrap();
    let actual = NamespaceCatalog::read_in(&view, &namespace.tenant, &namespace.id)
        .unwrap()
        .unwrap();
    completion.unwrap().resolve(&actual).unwrap();
    assert_eq!(actual.record(), &after);
    assert_eq!(after.version.incarnation, namespace.version.incarnation);
    assert_eq!(after.version.generation, namespace.version.generation + 1);
    assert!(after.pins.is_empty());
    assert!(view.get(&command_row_key(record.id)).unwrap().is_none());
    assert!(view
        .get(&writer::usage_row_key("tenant", "aggregate", 1).unwrap())
        .unwrap()
        .is_none());
    validate_view(&view, foreign_codec).unwrap();
}

#[test]
fn expired_command_floor_final_policy_and_exact_history_cas_prevent_partial_release() {
    for change in 0..3 {
        let (_dir, store, effects) = setup();
        let record = floor(&store, &effects, "floor-final-cas");
        let namespace = retire(&store);
        let request = release_request(&namespace, record.id);
        let owner = ResultMaintenanceOwner::default();
        let view = store.snapshot().unwrap();
        let prepared = owner
            .prepare_floor_release(&view, &request, observation(2302, 202))
            .unwrap();
        let before = view.get(&command_row_key(record.id)).unwrap();
        drop(view);
        if change == 0 {
            assert_eq!(
                prepared.publish(&store, |_, _, _| Err(AtomicError::PermissionDenied)),
                Err(AtomicError::PermissionDenied)
            );
        } else {
            let mutation = if change == 1 {
                let mut history =
                    latent_state::namespace::history::NamespaceHistory::initial(&namespace);
                history.status =
                    latent_state::namespace::history::HistoryStatus::ReconciliationRequired;
                RowMutation {
                    key: latent_state::namespace::history::history_key(
                        &namespace.tenant,
                        &namespace.id,
                        1,
                    )
                    .unwrap(),
                    value: Some(history.encode().unwrap()),
                }
            } else {
                latent_state::recovery::RecoveryGuard::staging([1; 32], [2; 32], [3; 32])
                    .unwrap()
                    .prepare_staging()
                    .unwrap()
                    .mutations
                    .remove(0)
            };
            store
                .apply(AtomicBatch {
                    expectations: vec![],
                    mutations: vec![mutation],
                })
                .unwrap();
            assert_eq!(
                prepared.publish(&store, |_, _, _| panic!("stale history precedes policy")),
                Err(AtomicError::Conflict)
            );
        }
        assert_eq!(
            store
                .snapshot()
                .unwrap()
                .get(&command_row_key(record.id))
                .unwrap(),
            before
        );
    }
}

#[test]
fn expired_command_floor_refuses_unretired_scope_old_generation_dependencies_and_clock() {
    let (_dir, store, effects) = setup();
    let record = floor(&store, &effects, "floor-negative");
    let owner = ResultMaintenanceOwner::default();
    let view = store.snapshot().unwrap();
    let active = NamespaceRecord::decode(&view.get(&namespace_key()).unwrap().unwrap()).unwrap();
    assert!(matches!(
        owner.prepare_floor_release(
            &view,
            &release_request(&active, record.id),
            observation(2302, 202)
        ),
        Err(AtomicError::RecoveryRequired)
    ));
    drop(view);
    let namespace = retire(&store);
    let request = release_request(&namespace, record.id);
    let view = store.snapshot().unwrap();
    for (wall, mono) in [(2300, 200), (5000, 202), (2302, 0)] {
        assert!(matches!(
            owner.prepare_floor_release(&view, &request, observation(wall, mono)),
            Err(AtomicError::RecoveryRequired)
        ));
    }
    let mut stale = request.clone();
    stale.expected.generation -= 1;
    assert!(matches!(
        owner.prepare_floor_release(&view, &stale, observation(2302, 202)),
        Err(AtomicError::Conflict)
    ));
    drop(view);
    store
        .apply(AtomicBatch {
            expectations: vec![],
            mutations: vec![RowMutation {
                key: attempt_row_key(record.id, 16),
                value: Some(b"unexpected retained attempt".to_vec()),
            }],
        })
        .unwrap();
    let view = store.snapshot().unwrap();
    assert!(matches!(
        owner.prepare_floor_release(&view, &request, observation(2302, 202)),
        Err(AtomicError::Corrupt)
    ));
    assert!(view.get(&command_row_key(record.id)).unwrap().is_some());
}

#[test]
fn expired_command_floor_release_composition_is_atomic_and_recreated_namespace_has_no_aba() {
    let (dir, store, effects) = setup();
    let record = floor(&store, &effects, "floor-recreate");
    let namespace = retire(&store);
    let owner = ResultMaintenanceOwner::default();
    let view = store.snapshot().unwrap();
    let mut prepared = owner
        .prepare_floor_release(
            &view,
            &release_request(&namespace, record.id),
            observation(2302, 202),
        )
        .unwrap();
    let original = prepared.batch().clone();
    assert_eq!(
        prepared.append_management_batch(AtomicBatch {
            expectations: vec![latent_state::embedded::ExpectedRow {
                key: MaintenanceProgress::key(),
                value: None,
            }],
            mutations: vec![RowMutation {
                key: namespace_key(),
                value: Some(namespace.encode().unwrap()),
            }],
        }),
        Err(AtomicError::Corrupt)
    );
    assert_eq!(
        prepared.batch().expectations.len(),
        original.expectations.len()
    );
    assert_eq!(prepared.batch().mutations.len(), original.mutations.len());
    drop(view);
    let released = prepared.publish(&store, |_, _, _| Ok(())).unwrap();
    let deleted = released
        .transition(released.version, &NamespaceTransition::Destroy, 0)
        .unwrap();
    assert_eq!(deleted.version.incarnation, 1);
    let recreated = deleted
        .transition(
            deleted.version,
            &NamespaceTransition::Recreate {
                state_schema: schema(),
                quota: deleted.quota,
            },
            0,
        )
        .unwrap();
    assert_eq!(recreated.version.incarnation, 2);
    store
        .apply(AtomicBatch {
            expectations: vec![],
            mutations: vec![RowMutation {
                key: namespace_key(),
                value: Some(recreated.encode().unwrap()),
            }],
        })
        .unwrap();
    drop(store);
    let store = open(&dir.path().join("state.redb"));
    let view = store.snapshot().unwrap();
    validate_view(&view, foreign_codec).unwrap();
    assert!(matches!(
        PreparedAdmission::prepare(&view, input("floor-recreate"), time(2400), permission),
        Err(AtomicError::Conflict)
    ));
    let mut fresh = input("floor-recreate");
    fresh.key.incarnation = "2".into();
    assert_ne!(
        crate::atomic::command_identity(&fresh.key).unwrap(),
        record.id
    );
    assert!(matches!(
        PreparedAdmission::prepare(&view, fresh, time(2400), permission),
        Ok(AdmissionDecision::New(_))
    ));
}
