use super::*;
use crate::embedded::{EmbeddedStore, StoreLimits};
use crate::namespace::{NamespaceQuota, NamespaceStatus};
use crate::session::{SessionLimits, StateAccess, StateError, StateMode, StateScope, StateSession};

struct Fixture {
    store: EmbeddedStore,
    scope: StateScope,
    _directory: tempfile::TempDir,
}

fn fixture() -> Fixture {
    let directory = tempfile::tempdir().unwrap();
    let file = std::fs::OpenOptions::new()
        .read(true)
        .write(true)
        .create_new(true)
        .open(directory.path().join("history.redb"))
        .unwrap();
    let store = EmbeddedStore::open_file(
        file,
        StoreLimits {
            cache_bytes: 1024 * 1024,
            ..StoreLimits::default()
        },
    )
    .unwrap();
    let scope = StateScope {
        tenant: TenantId("tenant".into()),
        namespace: StateNamespaceId("business".into()),
        incarnation: 1,
        state_schema: format!("sha256:{}", "1".repeat(64)),
        entity: None,
        mode: StateMode::Command,
    };
    let record = NamespaceRecord::create(
        scope.tenant.clone(),
        scope.namespace.clone(),
        scope.state_schema.clone(),
        NamespaceQuota::default(),
    )
    .unwrap();
    store
        .apply(AtomicBatch {
            expectations: vec![],
            mutations: vec![RowMutation {
                key: namespace_key(&scope),
                value: Some(record.encode().unwrap()),
            }],
        })
        .unwrap();
    Fixture {
        store,
        scope,
        _directory: directory,
    }
}

fn namespace_key(scope: &StateScope) -> RowKey {
    RowKey {
        family: Family::Namespace,
        key: namespace_record_key(&scope.tenant, &scope.namespace).unwrap(),
    }
}

fn allow(scope: &StateScope, _: StateAccess) -> Result<(), StateError> {
    if scope.tenant.0 == "tenant" {
        Ok(())
    } else {
        Err(StateError::PermissionDenied)
    }
}

fn staging() -> RecoveryGuard {
    RecoveryGuard::staging([1; 32], [2; 32], [3; 32]).unwrap()
}

#[test]
fn physical_readiness_cas_rejects_namespace_history_and_restore_changes() {
    for changed in 0..3 {
        let fixture = fixture();
        let view = fixture.store.snapshot().unwrap();
        let expectations = namespace_readiness_expectations(
            &view,
            &fixture.scope.tenant,
            &fixture.scope.namespace,
            1,
        )
        .unwrap();
        let record =
            NamespaceRecord::decode(&view.get(&namespace_key(&fixture.scope)).unwrap().unwrap())
                .unwrap();
        let mutation = match changed {
            0 => {
                let mut changed = record.clone();
                changed.status = NamespaceStatus::Quiescing;
                RowMutation {
                    key: namespace_key(&fixture.scope),
                    value: Some(changed.encode().unwrap()),
                }
            }
            1 => {
                let mut history = NamespaceHistory::initial(&record);
                history.status = HistoryStatus::ReconciliationRequired;
                RowMutation {
                    key: crate::namespace::history::history_key(
                        &record.tenant,
                        &record.id,
                        record.version.incarnation,
                    )
                    .unwrap(),
                    value: Some(history.encode().unwrap()),
                }
            }
            _ => staging().prepare_staging().unwrap().mutations.remove(0),
        };
        fixture
            .store
            .apply(AtomicBatch {
                expectations: vec![],
                mutations: vec![mutation],
            })
            .unwrap();
        let output = RowKey {
            family: Family::Maintenance,
            key: b"guarded-physical-write".to_vec(),
        };
        assert_eq!(
            fixture.store.apply(AtomicBatch {
                expectations: expectations.into(),
                mutations: vec![RowMutation {
                    key: output.clone(),
                    value: Some(vec![1])
                }],
            }),
            Err(StoreError::Conflict)
        );
        let actual = fixture.store.snapshot().unwrap();
        assert_eq!(actual.get(&output), Ok(None));
        assert_eq!(
            namespace_readiness_expectations(
                &actual,
                &fixture.scope.tenant,
                &fixture.scope.namespace,
                1,
            )
            .err(),
            Some(StoreError::Unavailable)
        );
    }
}

#[test]
fn actual_staging_and_completed_restore_guard_block_admission_and_original_namespace_dispatch() {
    let fixture = fixture();
    let old = fixture.store.snapshot().unwrap();
    let mut session =
        StateSession::open(&old, fixture.scope.clone(), SessionLimits::default(), allow).unwrap();
    session
        .put(
            &old,
            b"count".to_vec(),
            latent_core::transaction_contract::Value {
                bytes: 7u64.to_le_bytes().to_vec(),
                media_type: "application/vnd.lsf.aggregate-v1".into(),
                metadata: vec![],
            },
            allow,
        )
        .unwrap();
    let plan = session.seal(&old, allow).unwrap();
    let mut command = AtomicBatch::default();
    plan.append_to(&mut command, crate::namespace::NamespacePins::default())
        .unwrap();
    let captured = crate::session::version::capture_view(&old, &fixture.scope).unwrap();
    assert!(captured.recovery_expectation().value.is_none());
    let guard = staging();
    fixture
        .store
        .apply(guard.prepare_staging().unwrap())
        .unwrap();
    assert_eq!(fixture.store.apply(command), Err(StoreError::Conflict));
    for complete in [false, true] {
        if complete {
            fixture
                .store
                .apply(guard.prepare_completed().unwrap())
                .unwrap();
        }
        let view = fixture.store.snapshot().unwrap();
        assert_eq!(require_ready(&view), Err(StoreError::Unavailable));
        assert_eq!(
            require_namespace_ready(&view, &fixture.scope.tenant, &fixture.scope.namespace, 1),
            Err(StoreError::Unavailable)
        );
        assert!(matches!(
            StateSession::open(
                &view,
                fixture.scope.clone(),
                SessionLimits::default(),
                allow
            ),
            Err(StateError::RecoveryRequired)
        ));
        assert!(matches!(
            crate::session::version::capture_view(&view, &fixture.scope),
            Err(StateError::RecoveryRequired)
        ));
        assert_eq!(view.scan(Family::State, b"", 16, 4096).unwrap(), vec![]);
    }
    drop(old);
}

#[test]
fn reviewed_global_guard_keeps_paused_history_and_current_scope_checks_independent() {
    let fixture = fixture();
    let guard = staging();
    fixture
        .store
        .apply(guard.prepare_staging().unwrap())
        .unwrap();
    fixture
        .store
        .apply(guard.prepare_completed().unwrap())
        .unwrap();
    let view = fixture.store.snapshot().unwrap();
    let paused = RecoveryGuard::capture(&view).unwrap().unwrap();
    assert_eq!(
        paused
            .prepare_reviewed(&view, [4; 32], |_, _, _| Err(StoreError::Unavailable))
            .unwrap_err(),
        StoreError::Unavailable
    );
    let review = paused
        .prepare_reviewed(&view, [4; 32], |_, actual, proof| {
            assert_eq!(actual.snapshot_digest(), [2; 32]);
            assert_eq!(actual.window_digest(), [3; 32]);
            assert_eq!(proof, [4; 32]);
            Ok(())
        })
        .unwrap();
    fixture.store.apply(review).unwrap();
    let view = fixture.store.snapshot().unwrap();
    require_ready(&view).unwrap();
    let namespace =
        NamespaceRecord::decode(&view.get(&namespace_key(&fixture.scope)).unwrap().unwrap())
            .unwrap();
    let history = NamespaceHistory::initial(&namespace)
        .restored_after(&NamespaceHistory::initial(&namespace))
        .unwrap();
    let history_key =
        crate::namespace::history::history_key(&namespace.tenant, &namespace.id, 1).unwrap();
    fixture
        .store
        .apply(AtomicBatch {
            expectations: vec![],
            mutations: vec![RowMutation {
                key: history_key.clone(),
                value: Some(history.encode().unwrap()),
            }],
        })
        .unwrap();
    let view = fixture.store.snapshot().unwrap();
    assert_eq!(
        require_namespace_ready(&view, &namespace.tenant, &namespace.id, 1),
        Err(StoreError::Unavailable)
    );
    assert!(matches!(
        crate::session::version::capture_view(&view, &fixture.scope),
        Err(StateError::RecoveryRequired)
    ));
    let mut ready_history = history;
    ready_history.status = HistoryStatus::Ready;
    fixture
        .store
        .apply(AtomicBatch {
            expectations: vec![],
            mutations: vec![RowMutation {
                key: history_key,
                value: Some(ready_history.encode().unwrap()),
            }],
        })
        .unwrap();
    let view = fixture.store.snapshot().unwrap();
    require_namespace_ready(&view, &namespace.tenant, &namespace.id, 1).unwrap();
    assert_eq!(
        require_namespace_ready(&view, &namespace.tenant, &namespace.id, 2),
        Err(StoreError::Conflict)
    );
    let mut quiesced = namespace;
    quiesced.status = NamespaceStatus::Quiescing;
    fixture
        .store
        .apply(AtomicBatch {
            expectations: vec![],
            mutations: vec![RowMutation {
                key: namespace_key(&fixture.scope),
                value: Some(quiesced.encode().unwrap()),
            }],
        })
        .unwrap();
    assert_eq!(
        require_namespace_ready(
            &fixture.store.snapshot().unwrap(),
            &quiesced.tenant,
            &quiesced.id,
            1
        ),
        Err(StoreError::Unavailable)
    );
}

#[test]
fn recovery_guard_codec_refuses_unknown_phase_zero_proof_truncation_and_foreign_rows() {
    let guard = staging();
    let bytes = guard.encode().unwrap();
    assert_eq!(bytes.len(), GUARD_BYTES);
    assert_eq!(RecoveryGuard::decode(&bytes).unwrap(), guard);
    for length in [0, 4, GUARD_BYTES - 1] {
        assert!(RecoveryGuard::decode(&bytes[..length]).is_err());
    }
    let mut trailing = bytes.clone();
    trailing.push(0);
    assert!(RecoveryGuard::decode(&trailing).is_err());
    let mut unknown = bytes.clone();
    unknown[4] = 99;
    assert_eq!(
        RecoveryGuard::decode(&unknown),
        Err(StoreError::UnsupportedFormat)
    );
    let mut forged = bytes.clone();
    forged[4] = 3;
    assert_eq!(RecoveryGuard::decode(&forged), Err(StoreError::Corrupt));
    let mut zero = bytes;
    zero[5..37].fill(0);
    assert_eq!(RecoveryGuard::decode(&zero), Err(StoreError::Corrupt));
    assert_eq!(
        RecoveryGuard::validate_row(
            &RowKey {
                family: Family::State,
                key: GUARD_KEY.to_vec()
            },
            &guard.encode().unwrap()
        ),
        Err(StoreError::UnsupportedFormat)
    );
}
