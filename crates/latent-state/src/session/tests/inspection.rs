use super::*;
use crate::namespace::NamespaceTransition;

fn quiesce(fixture: &Fixture) {
    let view = fixture.store.snapshot().unwrap();
    let key = namespace_key(&fixture.scope).unwrap();
    let bytes = view.get(&key).unwrap().unwrap();
    let namespace = NamespaceRecord::decode(&bytes).unwrap();
    let next = namespace
        .transition(namespace.version, &NamespaceTransition::Quiesce, 0)
        .unwrap();
    drop(view);
    fixture
        .store
        .apply(AtomicBatch {
            expectations: vec![ExpectedRow {
                key: key.clone(),
                value: Some(bytes),
            }],
            mutations: vec![RowMutation {
                key,
                value: Some(next.encode().unwrap()),
            }],
        })
        .unwrap();
}

#[test]
fn native_cell_observation_preserves_real_scope_value_and_tombstone_without_session_access() {
    let fixture = Fixture::new();
    let mut scope = fixture.scope.clone();
    scope.entity = Some("original-entity".into());
    let (view, mut session) = fixture.in_scope(scope.clone(), SessionLimits::default());
    let mut original = value(&u64::MAX.to_le_bytes());
    original.media_type = "application/vnd.lsf.aggregate-v1".into();
    original.metadata = vec![("schema".into(), "original-v1".into())];
    session
        .put(&view, b"aggregate/count".to_vec(), original.clone(), allow)
        .unwrap();
    session.delete(&view, b"deleted".to_vec(), allow).unwrap();
    commit(&fixture.store, &view, session).unwrap();
    drop(view);
    quiesce(&fixture);
    let paused = fixture.store.snapshot().unwrap();
    assert!(StateSession::open(&paused, scope.clone(), SessionLimits::default(), allow).is_err());
    let row = state_key(&scope, b"aggregate/count").unwrap();
    let bytes = paused.get(&row).unwrap().unwrap();
    let actual = inspect_cell(&paused, &row, &bytes).unwrap();
    scope.mode = StateMode::Query;
    assert_eq!(actual.scope, scope);
    assert_eq!(actual.key, b"aggregate/count");
    assert_eq!(actual.generation, 2);
    assert_eq!(actual.value, Some(original));
    let row = state_key(&scope, b"deleted").unwrap();
    let bytes = paused.get(&row).unwrap().unwrap();
    let deleted = inspect_cell(&paused, &row, &bytes).unwrap();
    assert_eq!(deleted.generation, actual.generation);
    assert_eq!(deleted.value, None);
    assert_eq!(validate_row(&paused, &row, &bytes), Ok(()));
}

#[test]
fn native_cell_observation_refuses_foreign_incarnations_future_versions_and_malformed_owned_rows() {
    let fixture = Fixture::new();
    fixture.write(&[(b"original", Some(b"value"))]);
    let view = fixture.store.snapshot().unwrap();
    let row = state_key(&fixture.scope, b"original").unwrap();
    let bytes = view.get(&row).unwrap().unwrap();
    for field in ["tenant", "namespace", "incarnation"] {
        let mut wrong = fixture.scope.clone();
        match field {
            "tenant" => wrong.tenant = TenantId("foreign".into()),
            "namespace" => wrong.namespace = StateNamespaceId("foreign".into()),
            "incarnation" => wrong.incarnation = 2,
            _ => unreachable!(),
        }
        assert_eq!(
            inspect_cell(&view, &state_key(&wrong, b"original").unwrap(), &bytes),
            Err(StoreError::Corrupt)
        );
    }
    let future = Cell {
        generation: u64::MAX,
        value: Some(value(b"value")),
    }
    .encode()
    .unwrap();
    assert_eq!(inspect_cell(&view, &row, &future), Err(StoreError::Corrupt));
    for length in 0..bytes.len() {
        assert!(inspect_cell(&view, &row, &bytes[..length]).is_err());
    }
    let foreign = RowKey {
        family: Family::State,
        key: b"unknown-cell-v1".to_vec(),
    };
    assert_eq!(
        inspect_cell(&view, &foreign, &bytes),
        Err(StoreError::UnsupportedFormat)
    );
    let malformed = RowKey {
        family: Family::State,
        key: b"state-v1\0".to_vec(),
    };
    assert_eq!(
        inspect_cell(&view, &malformed, &bytes),
        Err(StoreError::Corrupt)
    );
}
