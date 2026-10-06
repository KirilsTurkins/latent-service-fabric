use super::*;
use crate::{
    embedded::{EmbeddedStore, FencedStoreError, StoreLimits},
    namespace::{history::HistoryEpochs, NamespacePins, NamespaceQuota, NamespaceTransition},
    session::{SessionLimits, StateError, StateSession},
};
use latent_core::{StateNamespaceId, TenantId};

struct Fixture {
    store: EmbeddedStore,
    request: NamespaceResumeRequest,
    namespace_key: RowKey,
    history_key: RowKey,
    _root: tempfile::TempDir,
}

fn fixture(restored: bool) -> Fixture {
    let root = tempfile::tempdir().unwrap();
    let file = std::fs::OpenOptions::new()
        .read(true)
        .write(true)
        .create_new(true)
        .open(root.path().join("resume.redb"))
        .unwrap();
    let store = EmbeddedStore::open_file(
        file,
        StoreLimits {
            cache_bytes: 1024 * 1024,
            ..StoreLimits::default()
        },
    )
    .unwrap();
    let mut namespace = NamespaceRecord::create(
        TenantId("tenant".into()),
        StateNamespaceId("business".into()),
        format!("sha256:{}", "1".repeat(64)),
        NamespaceQuota::default(),
    )
    .unwrap();
    namespace.pins = NamespacePins {
        unresolved_effects: 1,
        payload_references: 1,
        retained_results: 1,
        inbox_protection: 1,
    };
    namespace = namespace
        .transition(namespace.version, &NamespaceTransition::Quiesce, 0)
        .unwrap();
    let mut history = NamespaceHistory::initial(&namespace);
    if restored {
        history = history.restored_after(&history).unwrap();
    }
    let namespace_key = RowKey {
        family: Family::Namespace,
        key: namespace_record_key(&namespace.tenant, &namespace.id).unwrap(),
    };
    let history_key = history_key(&namespace.tenant, &namespace.id, 1).unwrap();
    store
        .apply(AtomicBatch {
            expectations: vec![],
            mutations: vec![
                RowMutation {
                    key: namespace_key.clone(),
                    value: Some(namespace.encode().unwrap()),
                },
                RowMutation {
                    key: history_key.clone(),
                    value: Some(history.encode().unwrap()),
                },
            ],
        })
        .unwrap();
    if restored {
        let guard = RecoveryGuard::staging([1; 32], [2; 32], [3; 32]).unwrap();
        store.apply(guard.prepare_staging().unwrap()).unwrap();
        store.apply(guard.prepare_completed().unwrap()).unwrap();
    }
    let scope = scope(&namespace);
    let expected_view = ViewIdentity {
        namespace: namespace.version,
        epochs: history.epochs,
    }
    .token(&scope)
    .unwrap();
    Fixture {
        store,
        namespace_key,
        history_key,
        request: NamespaceResumeRequest {
            scope,
            operation_id: "resume-1".into(),
            operator_id: "operator".into(),
            expected_view,
            review_digest: [5; 32],
        },
        _root: root,
    }
}

fn review_global(fixture: &Fixture) {
    let view = fixture.store.snapshot().unwrap();
    let guard = RecoveryGuard::capture(&view).unwrap().unwrap();
    let batch = guard
        .prepare_reviewed(&view, [4; 32], |_, _, _| Ok(()))
        .unwrap();
    drop(view);
    fixture.store.apply(batch).unwrap();
}

fn quiesce_again(fixture: &Fixture) -> NamespaceRecord {
    let view = fixture.store.snapshot().unwrap();
    let actual =
        NamespaceRecord::decode(&view.get(&fixture.namespace_key).unwrap().unwrap()).unwrap();
    let quiesced = actual
        .transition(actual.version, &NamespaceTransition::Quiesce, 0)
        .unwrap();
    drop(view);
    fixture
        .store
        .apply(AtomicBatch {
            expectations: vec![ExpectedRow {
                key: fixture.namespace_key.clone(),
                value: Some(actual.encode().unwrap()),
            }],
            mutations: vec![RowMutation {
                key: fixture.namespace_key.clone(),
                value: Some(quiesced.encode().unwrap()),
            }],
        })
        .unwrap();
    quiesced
}

#[test]
fn explicit_namespace_resume_preserves_restored_ids_and_original_lost_response_receipt() {
    let fixture = fixture(true);
    let view = fixture.store.snapshot().unwrap();
    assert!(matches!(
        NamespaceResumePlan::prepare(&view, &fixture.request, |_, _, _| Ok(())),
        Err(StoreError::Unavailable)
    ));
    drop(view);
    review_global(&fixture);
    let view = fixture.store.snapshot().unwrap();
    let plan = NamespaceResumePlan::prepare(&view, &fixture.request, |_, request, actual| {
        assert_eq!(request.operator_id, "operator");
        assert_eq!(actual.history.status, HistoryStatus::ReconciliationRequired);
        assert_eq!(actual.namespace.status, NamespaceStatus::Quiescing);
        assert_eq!(
            actual.guard.unwrap().status(),
            super::super::RecoveryStatus::ReviewAccepted
        );
        assert!(actual.original_receipt.is_none());
        Ok(())
    })
    .unwrap();
    assert!(!plan.replayed());
    let original = plan.receipt().clone();
    assert_eq!(original.namespace().version.incarnation, 1);
    assert_eq!(
        original.history().epochs,
        HistoryEpochs {
            schema: 1,
            recovery: 2
        }
    );
    assert_eq!(original.namespace().pins.unresolved_effects, 1);
    let bytes = original.encode().unwrap();
    drop(view);
    fixture
        .store
        .apply_fenced(plan.into_batch(), || Ok::<(), StoreError>(()))
        .unwrap();
    let view = fixture.store.snapshot().unwrap();
    super::super::require_namespace_ready(
        &view,
        &fixture.request.scope.tenant,
        &fixture.request.scope.namespace,
        1,
    )
    .unwrap();
    StateSession::open(
        &view,
        fixture.request.scope.clone(),
        SessionLimits::default(),
        |_, _| Ok(()),
    )
    .unwrap();
    // Another real lifecycle transition must not replace the original receipt.
    drop(view);
    let quiesced = quiesce_again(&fixture);
    let view = fixture.store.snapshot().unwrap();
    assert!(matches!(
        NamespaceResumePlan::prepare(&view, &fixture.request, |_, _, _| Err(
            StoreError::Unavailable
        )),
        Err(StoreError::Unavailable)
    ));
    let replay = NamespaceResumePlan::prepare(&view, &fixture.request, |_, _, actual| {
        assert_eq!(actual.namespace, &quiesced);
        assert_eq!(actual.original_receipt.unwrap(), &original);
        Ok(())
    })
    .unwrap();
    assert!(replay.replayed());
    assert_eq!(replay.receipt().encode().unwrap(), bytes);
    assert_ne!(
        replay.receipt().view_token().unwrap(),
        ViewIdentity {
            namespace: quiesced.version,
            epochs: original.history().epochs
        }
        .token(&fixture.request.scope)
        .unwrap()
    );
    drop(view);
    fixture
        .store
        .apply_fenced(replay.into_batch(), || Ok::<(), StoreError>(()))
        .unwrap();
    let view = fixture.store.snapshot().unwrap();
    assert_eq!(
        NamespaceRecord::decode(&view.get(&fixture.namespace_key).unwrap().unwrap()).unwrap(),
        quiesced
    );
    assert_eq!(
        super::super::require_namespace_ready(&view, &quiesced.tenant, &quiesced.id, 1),
        Err(StoreError::Unavailable)
    );
}

#[test]
fn resume_rechecks_final_authority_and_exact_history_and_rejects_stale_or_changed_plans() {
    let fixture = fixture(false);
    let view = fixture.store.snapshot().unwrap();
    let plan = NamespaceResumePlan::prepare(&view, &fixture.request, |_, _, _| Ok(())).unwrap();
    drop(view);
    assert_eq!(
        fixture
            .store
            .apply_fenced(plan.into_batch(), || Err(StoreError::Unavailable)),
        Err(FencedStoreError::Fence(StoreError::Unavailable))
    );
    let view = fixture.store.snapshot().unwrap();
    assert!(view
        .get(&fixture.request.receipt_key().unwrap())
        .unwrap()
        .is_none());
    let plan = NamespaceResumePlan::prepare(&view, &fixture.request, |_, _, _| Ok(())).unwrap();
    let namespace =
        NamespaceRecord::decode(&view.get(&fixture.namespace_key).unwrap().unwrap()).unwrap();
    let (before, _) = NamespaceHistory::capture(&view, &namespace).unwrap();
    let mut after = before.clone();
    after.epochs.recovery += 1;
    drop(view);
    fixture
        .store
        .apply(AtomicBatch {
            expectations: vec![ExpectedRow {
                key: fixture.history_key.clone(),
                value: Some(before.encode().unwrap()),
            }],
            mutations: vec![RowMutation {
                key: fixture.history_key.clone(),
                value: Some(after.encode().unwrap()),
            }],
        })
        .unwrap();
    assert_eq!(
        fixture.store.apply(plan.into_batch()),
        Err(StoreError::Conflict)
    );
    let view = fixture.store.snapshot().unwrap();
    assert!(matches!(
        NamespaceResumePlan::prepare(&view, &fixture.request, |_, _, _| Ok(())),
        Err(StoreError::Conflict)
    ));
    let mut wrong = fixture.request.clone();
    wrong.scope.tenant = TenantId("other".into());
    assert_eq!(wrong.validate(), Err(StoreError::Invalid));
    let mut current = fixture.request.clone();
    current.expected_view = ViewIdentity {
        namespace: namespace.version,
        epochs: after.epochs,
    }
    .token(&current.scope)
    .unwrap();
    let plan = NamespaceResumePlan::prepare(&view, &current, |_, _, _| Ok(())).unwrap();
    drop(view);
    fixture.store.apply(plan.into_batch()).unwrap();
    current.review_digest = [6; 32];
    let view = fixture.store.snapshot().unwrap();
    assert!(matches!(
        NamespaceResumePlan::prepare(&view, &current, |_, _, _| Ok(())),
        Err(StoreError::Conflict)
    ));
    assert_eq!(
        ViewIdentity {
            namespace: namespace.version,
            epochs: after.epochs
        }
        .require_minimum(&current.scope, &fixture.request.expected_view),
        Err(StateError::RecoveryRequired)
    );
}

#[test]
fn namespace_resume_receipt_rejects_truncation_trailing_bytes_and_wrong_physical_identity() {
    let fixture = fixture(false);
    let view = fixture.store.snapshot().unwrap();
    let plan = NamespaceResumePlan::prepare(&view, &fixture.request, |_, _, _| Ok(())).unwrap();
    let receipt = plan.receipt();
    let bytes = receipt.encode().unwrap();
    let key = fixture.request.receipt_key().unwrap();
    NamespaceResumeReceipt::validate_row(&key, &bytes).unwrap();
    for length in 0..bytes.len() {
        assert!(NamespaceResumeReceipt::decode(&bytes[..length]).is_err());
    }
    let mut trailing = bytes.clone();
    trailing.push(0);
    assert_eq!(
        NamespaceResumeReceipt::decode(&trailing),
        Err(StoreError::Corrupt)
    );
    let mut wrong = key.clone();
    *wrong.key.last_mut().unwrap() ^= 1;
    assert_eq!(
        NamespaceResumeReceipt::validate_row(&wrong, &bytes),
        Err(StoreError::Corrupt)
    );
}
