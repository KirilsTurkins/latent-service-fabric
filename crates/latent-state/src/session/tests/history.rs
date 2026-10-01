use super::*;
use crate::namespace::{
    catalog::NamespaceCatalog,
    history::{history_key, HistoryEpochs, HistoryStatus, NamespaceHistory},
    NamespaceError,
};
use crate::session::version::{
    capture_view, capture_view_identity, ViewIdentity, VIEW_TOKEN_BYTES,
};

fn change_history(fixture: &Fixture, epochs: HistoryEpochs, status: HistoryStatus) {
    let view = fixture.store.snapshot().unwrap();
    let namespace = NamespaceRecord::decode(
        &view
            .get(&namespace_key(&fixture.scope).unwrap())
            .unwrap()
            .unwrap(),
    )
    .unwrap();
    let key = history_key(
        &namespace.tenant,
        &namespace.id,
        namespace.version.incarnation,
    )
    .unwrap();
    let old = view.get(&key).unwrap();
    let mut history = NamespaceHistory::initial(&namespace);
    history.epochs = epochs;
    history.status = status;
    drop(view);
    fixture
        .store
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
fn opaque_minimum_view_binds_scope_schema_recovery_and_exact_unsigned_versions() {
    let fixture = Fixture::new();
    let (_, session) = fixture.session();
    let identity = session.view_identity();
    let token = session.view_token().unwrap();
    assert_eq!(token.len(), VIEW_TOKEN_BYTES);
    identity.require_minimum(&fixture.scope, &token).unwrap();
    let future = ViewIdentity {
        namespace: NamespaceVersion {
            generation: u64::MAX,
            ..identity.namespace
        },
        ..identity
    };
    assert_eq!(
        identity.require_minimum(&fixture.scope, &future.token(&fixture.scope).unwrap()),
        Err(StateError::Conflict)
    );
    for epochs in [
        HistoryEpochs {
            schema: 2,
            recovery: 1,
        },
        HistoryEpochs {
            schema: 1,
            recovery: 2,
        },
    ] {
        assert_eq!(
            ViewIdentity { epochs, ..future }.require_minimum(&fixture.scope, &token),
            Err(StateError::RecoveryRequired)
        );
    }
    let mut wrong = fixture.scope.clone();
    wrong.tenant = TenantId("other".into());
    assert_eq!(
        identity.require_minimum(&wrong, &token),
        Err(StateError::Invalid)
    );
    wrong = fixture.scope.clone();
    wrong.entity = Some("other-entity".into());
    assert_eq!(
        ViewIdentity::from_token(&wrong, &token),
        Err(StateError::Invalid)
    );
    for length in 0..token.len() {
        assert!(ViewIdentity::from_token(&fixture.scope, &token[..length]).is_err());
    }
    let mut malformed = token;
    malformed.push(0);
    assert_eq!(
        ViewIdentity::from_token(&fixture.scope, &malformed),
        Err(StateError::Invalid)
    );
}

#[test]
fn ordinary_engine_restart_preserves_the_original_history_view_token() {
    let fixture = Fixture::new();
    fixture.write(&[(b"counter", Some(b"1"))]);
    change_history(
        &fixture,
        HistoryEpochs {
            schema: 9,
            recovery: 17,
        },
        HistoryStatus::Ready,
    );
    let token = {
        let (_, session) = fixture.session();
        session.view_token().unwrap()
    };
    let Fixture {
        store,
        scope,
        _directory: directory,
    } = fixture;
    drop(store);
    let file = OpenOptions::new()
        .read(true)
        .write(true)
        .open(directory.path().join("session.redb"))
        .unwrap();
    let store = EmbeddedStore::open_file(
        file,
        StoreLimits {
            cache_bytes: 1024 * 1024,
            ..StoreLimits::default()
        },
    )
    .unwrap();
    let view = store.snapshot().unwrap();
    let restored = capture_view_identity(&view, &scope).unwrap();
    assert_eq!(restored.token(&scope).unwrap(), token);
    restored.require_minimum(&scope, &token).unwrap();
}

#[test]
fn changed_history_invalidates_old_record_preconditions_without_changing_business_cells() {
    let fixture = Fixture::new();
    fixture.write(&[(b"counter", Some(b"1"))]);
    let original = fixture.read(b"counter").unwrap();
    change_history(
        &fixture,
        HistoryEpochs {
            schema: 1,
            recovery: 2,
        },
        HistoryStatus::Ready,
    );
    let current = fixture.read(b"counter").unwrap();
    assert_eq!(original.value, current.value);
    assert_ne!(original.version, current.version);
    assert_eq!(current.version.len(), VIEW_TOKEN_BYTES);
    let (view, mut session) = fixture.session();
    assert_eq!(
        session.check_preconditions(
            &view,
            &[Precondition {
                key: b"counter".to_vec(),
                expected: ExpectedVersion::Present(original.version)
            }],
            allow
        ),
        Err(StateError::Conflict)
    );
}

#[test]
fn live_command_plan_cannot_commit_when_an_absent_or_present_history_row_changes() {
    for present in [false, true] {
        let fixture = Fixture::new();
        if present {
            change_history(&fixture, HistoryEpochs::default(), HistoryStatus::Ready);
        }
        let (view, mut session) = fixture.session();
        session
            .put(&view, b"staged".to_vec(), value(b"must-not-commit"), allow)
            .unwrap();
        let plan = session.seal(&view, allow).unwrap();
        let token = plan.view_token().unwrap();
        assert_eq!(
            ViewIdentity::from_token(&fixture.scope, &token)
                .unwrap()
                .namespace,
            plan.version()
        );
        change_history(
            &fixture,
            HistoryEpochs {
                schema: 1,
                recovery: 2,
            },
            HistoryStatus::Ready,
        );
        let mut batch = AtomicBatch::default();
        let pins = plan.pins();
        plan.append_to(&mut batch, pins).unwrap();
        assert_eq!(fixture.store.apply(batch), Err(StoreError::Conflict));
        assert!(fixture.read(b"staged").is_none());
    }
}

#[test]
fn no_state_disposition_captures_the_same_exact_history_fence() {
    let fixture = Fixture::new();
    let view = fixture.store.snapshot().unwrap();
    let captured = capture_view(&view, &fixture.scope).unwrap();
    let original = capture_view_identity(&view, &fixture.scope).unwrap();
    assert_eq!(captured.identity(), original);
    let expectation = captured.history_expectation();
    assert!(expectation.value.is_none());
    change_history(
        &fixture,
        HistoryEpochs {
            schema: 2,
            recovery: 1,
        },
        HistoryStatus::Ready,
    );
    assert_eq!(
        fixture.store.apply(AtomicBatch {
            expectations: vec![expectation],
            mutations: vec![]
        }),
        Err(StoreError::Conflict)
    );
}

#[test]
fn restored_history_preserves_namespace_receipt_bytes_and_stays_paused() {
    let fixture = Fixture::new();
    let view = fixture.store.snapshot().unwrap();
    let bytes = view
        .get(&namespace_key(&fixture.scope).unwrap())
        .unwrap()
        .unwrap();
    let namespace = NamespaceRecord::decode(&bytes).unwrap();
    let source = NamespaceHistory::initial(&namespace);
    let mut current = source.clone();
    current.epochs.recovery = 42;
    let restored = source.restored_after(&current).unwrap();
    assert_eq!(restored.incarnation, namespace.version.incarnation);
    assert_eq!(restored.epochs.recovery, 43);
    assert_eq!(restored.status, HistoryStatus::ReconciliationRequired);
    assert_eq!(namespace.encode().unwrap(), bytes);
    drop(view);
    change_history(&fixture, restored.epochs, restored.status);
    let view = fixture.store.snapshot().unwrap();
    assert!(matches!(
        StateSession::open(
            &view,
            fixture.scope.clone(),
            SessionLimits::default(),
            allow
        ),
        Err(StateError::RecoveryRequired)
    ));
    current.epochs.recovery = u64::MAX;
    assert_eq!(
        source.restored_after(&current),
        Err(NamespaceError::Capacity)
    );
}

#[test]
fn history_decoder_refuses_corruption_unknown_fields_wrong_scope_and_zero_epochs() {
    let fixture = Fixture::new();
    let view = fixture.store.snapshot().unwrap();
    let namespace = NamespaceRecord::decode(
        &view
            .get(&namespace_key(&fixture.scope).unwrap())
            .unwrap()
            .unwrap(),
    )
    .unwrap();
    let history = NamespaceHistory::initial(&namespace);
    let bytes = history.encode().unwrap();
    let key = history_key(
        &namespace.tenant,
        &namespace.id,
        namespace.version.incarnation,
    )
    .unwrap();
    NamespaceCatalog::validate_row(&key, &bytes).unwrap();
    for length in 0..bytes.len() {
        assert!(NamespaceHistory::decode(&bytes[..length]).is_err());
    }
    let mut extra = bytes.clone();
    extra.push(0);
    assert_eq!(
        NamespaceHistory::decode(&extra),
        Err(NamespaceError::Corrupt)
    );
    let mut unknown = bytes.clone();
    *unknown.last_mut().unwrap() = 99;
    assert_eq!(
        NamespaceHistory::decode(&unknown),
        Err(NamespaceError::Corrupt)
    );
    let mut wrong = key;
    wrong.key.push(0);
    assert_eq!(
        NamespaceCatalog::validate_row(&wrong, &bytes),
        Err(NamespaceError::Corrupt)
    );
    let mut zero = history;
    zero.epochs.schema = 0;
    assert_eq!(zero.encode(), Err(NamespaceError::Invalid));
}
