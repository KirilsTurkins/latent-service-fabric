use super::*;
use crate::session::entities::{inspect_entities, EntityPageRequest};

fn namespace(view: &ReadView, fixture: &Fixture) -> NamespaceRecord {
    NamespaceRecord::decode(
        &view
            .get(&namespace_key(&fixture.scope).unwrap())
            .unwrap()
            .unwrap(),
    )
    .unwrap()
}

fn write_entity(fixture: &Fixture, entity: &str, changes: &[(&[u8], Option<&[u8]>)]) {
    let mut scope = fixture.scope.clone();
    scope.entity = Some(entity.into());
    let (view, mut session) = fixture.in_scope(scope, SessionLimits::default());
    for (key, data) in changes {
        match data {
            Some(bytes) => session
                .put(&view, key.to_vec(), value(bytes), allow)
                .unwrap(),
            None => session.delete(&view, key.to_vec(), allow).unwrap(),
        }
    }
    commit(&fixture.store, &view, session).unwrap();
}

fn request(maximum: usize) -> EntityPageRequest<'static> {
    EntityPageRequest {
        prefix: b"",
        after: None,
        expected_view: None,
        maximum,
    }
}

#[test]
fn entity_discovery_deduplicates_live_cells_keeps_tombstones_and_changes_no_records() {
    let fixture = Fixture::new();
    fixture.write(&[(b"namespace-wide", Some(b"not-an-entity"))]);
    write_entity(
        &fixture,
        "account-z",
        &[(b"a", Some(b"1")), (b"b", Some(b"2"))],
    );
    write_entity(&fixture, "account-a", &[(b"gone", None)]);
    let view = fixture.store.snapshot().unwrap();
    let row = namespace(&view, &fixture);
    let families = [
        Family::Namespace,
        Family::State,
        Family::Maintenance,
        Family::Command,
        Family::Outbox,
    ];
    let before: Vec<_> = families
        .iter()
        .map(|family| view.scan(*family, b"", 256, 2 * 1024 * 1024).unwrap())
        .collect();
    let page = inspect_entities(&view, &row, request(128), || Ok(())).unwrap();
    assert_eq!(
        page.entities
            .iter()
            .map(|value| value.entity.as_str())
            .collect::<Vec<_>>(),
        ["account-a", "account-z"]
    );
    assert_eq!(page.continuation, None);
    assert_eq!(page.view.namespace, row.version);
    for item in &page.entities {
        let mut scope = fixture.scope.clone();
        scope.entity = Some(item.entity.clone());
        assert_eq!(
            version::ViewIdentity::from_token(&scope, &item.version).unwrap(),
            page.view
        );
        assert!(version::ViewIdentity::from_token(&fixture.scope, &item.version).is_err());
    }
    let after = fixture.store.snapshot().unwrap();
    for (family, expected) in families.iter().zip(before) {
        assert_eq!(
            after.scan(*family, b"", 256, 2 * 1024 * 1024).unwrap(),
            expected
        );
    }
}

#[test]
fn entity_pages_resume_lexically_in_one_exact_view_without_a_false_last_page() {
    let fixture = Fixture::new();
    for entity in ["z", "alphabet", "a", "beta"] {
        write_entity(&fixture, entity, &[(b"value", Some(b"data"))]);
    }
    let view = fixture.store.snapshot().unwrap();
    let row = namespace(&view, &fixture);
    let first = inspect_entities(&view, &row, request(2), || Ok(())).unwrap();
    assert_eq!(
        first
            .entities
            .iter()
            .map(|item| item.entity.as_str())
            .collect::<Vec<_>>(),
        ["a", "alphabet"]
    );
    let second = inspect_entities(
        &view,
        &row,
        EntityPageRequest {
            after: first.continuation,
            expected_view: Some(first.view),
            ..request(2)
        },
        || Ok(()),
    )
    .unwrap();
    assert_eq!(
        second
            .entities
            .iter()
            .map(|item| item.entity.as_str())
            .collect::<Vec<_>>(),
        ["beta", "z"]
    );
    assert_eq!(second.continuation, None);
    let prefix = inspect_entities(
        &view,
        &row,
        EntityPageRequest {
            prefix: b"al",
            ..request(1)
        },
        || Ok(()),
    )
    .unwrap();
    assert_eq!(prefix.entities[0].entity, "alphabet");
    assert!(prefix.continuation.is_none());
    assert_eq!(
        inspect_entities(
            &view,
            &row,
            EntityPageRequest {
                after: Some([0; 32]),
                expected_view: Some(first.view),
                ..request(2)
            },
            || Ok(())
        ),
        Err(StateError::InvalidCursor)
    );
}

#[test]
fn entity_continuations_refuse_changed_generation_schema_and_recovery_epochs() {
    let fixture = Fixture::new();
    for entity in ["one", "two"] {
        write_entity(&fixture, entity, &[(b"v", Some(b"x"))]);
    }
    let view = fixture.store.snapshot().unwrap();
    let row = namespace(&view, &fixture);
    let first = inspect_entities(&view, &row, request(1), || Ok(())).unwrap();
    let resumed = || EntityPageRequest {
        after: first.continuation,
        expected_view: Some(first.view),
        ..request(1)
    };
    write_entity(&fixture, "one", &[(b"v", Some(b"changed"))]);
    let fresh = fixture.store.snapshot().unwrap();
    let fresh_row = namespace(&fresh, &fixture);
    assert_eq!(
        inspect_entities(&fresh, &fresh_row, resumed(), || Ok(())),
        Err(StateError::InvalidCursor)
    );
    // Retained old snapshots remain coherent; fresh RPCs cannot substitute them.
    assert_eq!(
        inspect_entities(&view, &row, resumed(), || Ok(()))
            .unwrap()
            .entities[0]
            .entity,
        "two"
    );
    let current = inspect_entities(&fresh, &fresh_row, request(1), || Ok(())).unwrap();
    for epochs in [
        crate::namespace::history::HistoryEpochs {
            schema: 2,
            recovery: 1,
        },
        crate::namespace::history::HistoryEpochs {
            schema: 2,
            recovery: 2,
        },
    ] {
        super::history::change_history(
            &fixture,
            epochs,
            crate::namespace::history::HistoryStatus::Ready,
        );
        let changed = fixture.store.snapshot().unwrap();
        let row = namespace(&changed, &fixture);
        assert_eq!(
            inspect_entities(
                &changed,
                &row,
                EntityPageRequest {
                    after: current.continuation,
                    expected_view: Some(current.view),
                    ..request(1)
                },
                || Ok(())
            ),
            Err(StateError::InvalidCursor)
        );
    }
}

#[test]
fn entity_discovery_uses_canonical_scope_prefix_and_accepts_full_bounded_identity() {
    let fixture = Fixture::new();
    let maximum = "x".repeat(contract::IDENTITY_BYTES);
    write_entity(&fixture, &maximum, &[(b"v", Some(b"own"))]);
    let mut foreign = fixture.scope.clone();
    foreign.tenant = TenantId("tenant-longer".into());
    foreign.entity = Some("foreign".into());
    let mut key = codec::key_prefix(&foreign).unwrap();
    key.extend_from_slice(b"v");
    fixture
        .store
        .apply(AtomicBatch {
            expectations: vec![],
            mutations: vec![RowMutation {
                key: RowKey {
                    family: Family::State,
                    key,
                },
                value: Some(b"unsupported-foreign-cell".to_vec()),
            }],
        })
        .unwrap();
    let view = fixture.store.snapshot().unwrap();
    let page =
        inspect_entities(&view, &namespace(&view, &fixture), request(128), || Ok(())).unwrap();
    assert_eq!(page.entities.len(), 1);
    assert_eq!(page.entities[0].entity, maximum);
}

#[test]
fn filtered_entity_rows_cannot_hide_unsupported_or_corrupt_cells() {
    let fixture = Fixture::new();
    let mut scope = fixture.scope.clone();
    scope.entity = Some("outside-prefix".into());
    let mut key = codec::key_prefix(&scope).unwrap();
    key.extend_from_slice(b"v");
    for (bytes, expected) in [
        (
            b"LSV\x09unsupported".to_vec(),
            StateError::UnsupportedFormat,
        ),
        (
            codec::Cell {
                generation: 2,
                value: None,
            }
            .encode()
            .unwrap(),
            StateError::Corrupt,
        ),
    ] {
        fixture
            .store
            .apply(AtomicBatch {
                expectations: vec![],
                mutations: vec![RowMutation {
                    key: RowKey {
                        family: Family::State,
                        key: key.clone(),
                    },
                    value: Some(bytes),
                }],
            })
            .unwrap();
        let view = fixture.store.snapshot().unwrap();
        assert_eq!(
            inspect_entities(
                &view,
                &namespace(&view, &fixture),
                EntityPageRequest {
                    prefix: b"other",
                    ..request(1)
                },
                || Ok(())
            ),
            Err(expected)
        );
    }
}

#[test]
fn entity_discovery_refuses_partial_capacity_results_and_rechecks_current_access() {
    let fixture = Fixture::new();
    let encoded = codec::Cell {
        generation: 1,
        value: None,
    }
    .encode()
    .unwrap();
    for start in (0..2049).step_by(128) {
        let mut mutations = Vec::new();
        for index in start..(start + 128).min(2049) {
            let mut scope = fixture.scope.clone();
            scope.entity = Some(format!("entity-{index:04}"));
            let mut key = codec::key_prefix(&scope).unwrap();
            key.extend_from_slice(b"v");
            mutations.push(RowMutation {
                key: RowKey {
                    family: Family::State,
                    key,
                },
                value: Some(encoded.clone()),
            });
        }
        fixture
            .store
            .apply(AtomicBatch {
                expectations: vec![],
                mutations,
            })
            .unwrap();
    }
    let view = fixture.store.snapshot().unwrap();
    let row = namespace(&view, &fixture);
    assert_eq!(
        inspect_entities(&view, &row, request(1), || Ok(())),
        Err(StateError::Limit)
    );
    let mut checks = 0;
    assert_eq!(
        inspect_entities(&view, &row, request(1), || {
            checks += 1;
            if checks == 3 {
                Err(StateError::PermissionDenied)
            } else {
                Ok(())
            }
        }),
        Err(StateError::PermissionDenied)
    );
    assert_eq!(checks, 3);
    for maximum in [0, 129] {
        assert_eq!(
            inspect_entities(&view, &row, request(maximum), || panic!(
                "invalid request reached access"
            )),
            Err(StateError::Limit)
        );
    }
}
