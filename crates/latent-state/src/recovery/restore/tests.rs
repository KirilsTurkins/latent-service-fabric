use super::*;
use crate::{
    embedded::{ExpectedRow, Family},
    namespace::{history::HistoryStatus, NamespaceRecord, NamespaceTransition},
    recovery::snapshot::tests::{closure, deadline, export, fixture, validate_row, Fixture},
    session::{
        version::ViewIdentity, SessionLimits, StateError, StateMode, StateScope, StateSession,
    },
};
use std::{fs::OpenOptions, io::Cursor};

fn destination(limits: StoreLimits) -> (tempfile::TempDir, EmbeddedStore) {
    let directory = tempfile::tempdir().unwrap();
    let file = OpenOptions::new()
        .read(true)
        .write(true)
        .create_new(true)
        .open(directory.path().join("restored.redb"))
        .unwrap();
    (directory, EmbeddedStore::open_file(file, limits).unwrap())
}

fn request(view: &ReadView, snapshot: &SnapshotReceipt) -> RestoreRequest {
    RestoreRequest {
        operation_id: "restore-original".into(),
        operator_id: "operator".into(),
        snapshot_digest: snapshot.snapshot_digest,
        runtime_digest: snapshot.manifest.metadata.runtime_digest,
        window_acknowledgement: RestoreWindow::capture(view, snapshot)
            .unwrap()
            .digest()
            .unwrap(),
    }
}

fn retire_after_backup(fixture: &Fixture) {
    let view = fixture.store.snapshot().unwrap();
    let (key, bytes) = view
        .scan(Family::Namespace, b"ns-v1\0", 1, 4096)
        .unwrap()
        .pop()
        .unwrap();
    let record = NamespaceRecord::decode(&bytes).unwrap();
    let next = record
        .transition(record.version, &NamespaceTransition::Retire, 0)
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
fn actual_older_snapshot_restore_preserves_original_rows_and_business_incarnation_but_invalidates_live_tokens(
) {
    let fixture = fixture();
    let (bytes, snapshot) = export(&fixture);
    retire_after_backup(&fixture);
    let current = fixture.store.snapshot().unwrap();
    let (record, old_history) = snapshot.manifest.namespaces[0].decode().unwrap();
    let scope = StateScope {
        tenant: record.tenant.clone(),
        namespace: record.id.clone(),
        incarnation: record.version.incarnation,
        state_schema: record.state_schema.clone(),
        entity: None,
        mode: StateMode::Query,
    };
    let old_token = ViewIdentity {
        namespace: record.version,
        epochs: old_history.epochs,
    }
    .token(&scope)
    .unwrap();
    let approved = request(&current, &snapshot);
    let plan = RestorePlan::prepare(&current, snapshot.clone(), &approved, |window, _| {
        let original = window.namespaces()[0].snapshot.decode().unwrap().0;
        let actual = window.namespaces()[0].current.decode().unwrap().0;
        assert!(actual.version.generation > original.version.generation);
        Ok(())
    })
    .unwrap();
    let (_directory, restored) = destination(StoreLimits::default());
    let guard = plan
        .execute(
            &mut Cursor::new(bytes),
            &restored,
            deadline(),
            |key, value| validate_row(&current, key, value),
            |view| closure(view, &fixture.metadata),
        )
        .unwrap();
    assert_eq!(
        guard.status(),
        super::super::RecoveryStatus::ReconciliationRequired
    );
    let after = restored.snapshot().unwrap();
    assert_eq!(
        capture_namespaces(&after, "tenant").unwrap()[0].record,
        snapshot.manifest.namespaces[0].record
    );
    let history = NamespaceHistory::capture(&after, &record).unwrap().0;
    assert_eq!(history.epochs.recovery, old_history.epochs.recovery + 1);
    assert_eq!(history.status, HistoryStatus::ReconciliationRequired);
    let identity = ViewIdentity {
        namespace: record.version,
        epochs: history.epochs,
    };
    assert_eq!(
        identity.require_minimum(&scope, &old_token),
        Err(StateError::RecoveryRequired)
    );
    assert_ne!(identity.token(&scope).unwrap(), old_token);
    assert_eq!(
        StateSession::open(&after, scope, SessionLimits::default(), |_, _| Ok(())).err(),
        Some(StateError::RecoveryRequired)
    );
    assert_eq!(
        crate::recovery::require_namespace_ready(
            &after,
            &record.tenant,
            &record.id,
            record.version.incarnation
        ),
        Err(StoreError::Unavailable)
    );
    for family in [Family::State, Family::Maintenance] {
        for (key, value) in current.scan(family, b"", 128, 1024 * 1024).unwrap() {
            assert_eq!(after.get(&key).unwrap(), Some(value));
        }
    }
}

#[test]
fn restore_review_refuses_unacknowledged_wrong_runtime_scope_stale_window_and_changed_roster() {
    let fixture = fixture();
    let (_, snapshot) = export(&fixture);
    let view = fixture.store.snapshot().unwrap();
    let mut input = request(&view, &snapshot);
    input.window_acknowledgement = [0; 32];
    assert_eq!(
        RestorePlan::prepare(&view, snapshot.clone(), &input, |_, _| panic!(
            "no acknowledgement reached review"
        ))
        .err(),
        Some(StoreError::Conflict)
    );
    input = request(&view, &snapshot);
    input.runtime_digest = [89; 32];
    assert_eq!(
        RestorePlan::prepare(&view, snapshot.clone(), &input, |_, _| panic!(
            "wrong runtime reached review"
        ))
        .err(),
        Some(StoreError::UnsupportedFormat)
    );
    input = request(&view, &snapshot);
    assert_eq!(
        RestorePlan::prepare(&view, snapshot.clone(), &input, |_, _| Err(
            StoreError::Unavailable
        ))
        .err(),
        Some(StoreError::Unavailable)
    );
    let stale = request(&view, &snapshot);
    drop(view);
    retire_after_backup(&fixture);
    let current = fixture.store.snapshot().unwrap();
    assert_eq!(
        RestorePlan::prepare(&current, snapshot.clone(), &stale, |_, _| panic!(
            "stale plan reached review"
        ))
        .err(),
        Some(StoreError::Conflict)
    );
    let approved = request(&current, &snapshot);
    let mut foreign = snapshot.clone();
    foreign.manifest.metadata.tenant = "foreign".into();
    assert_eq!(
        RestorePlan::prepare(&current, foreign, &approved, |_, _| panic!(
            "foreign snapshot reached review"
        ))
        .err(),
        Some(StoreError::Conflict)
    );
    let mut record = snapshot.manifest.namespaces[0].decode().unwrap().0;
    record.id.0 = "newer-namespace".into();
    fixture
        .store
        .apply(AtomicBatch {
            expectations: vec![],
            mutations: vec![RowMutation {
                key: RowKey {
                    family: Family::Namespace,
                    key: crate::namespace::namespace_record_key(&record.tenant, &record.id)
                        .unwrap(),
                },
                value: Some(record.encode().unwrap()),
            }],
        })
        .unwrap();
    drop(current);
    assert_eq!(
        RestoreWindow::capture(&fixture.store.snapshot().unwrap(), &snapshot).err(),
        Some(StoreError::Conflict)
    );
}

#[test]
fn recovery_window_acknowledges_non_namespace_rows_and_preserves_original_deadline() {
    let fixture = fixture();
    let (_, snapshot) = export(&fixture);
    let before = fixture.store.snapshot().unwrap();
    let acknowledgement = request(&before, &snapshot);
    let captured = RestoreWindow::capture(&before, &snapshot).unwrap();
    let (record, initial) = captured.namespaces()[0].current.decode().unwrap();
    let key = history_key(&record.tenant, &record.id, record.version.incarnation).unwrap();
    drop(before);
    fixture
        .store
        .apply(AtomicBatch {
            expectations: vec![ExpectedRow {
                key: key.clone(),
                value: None,
            }],
            mutations: vec![RowMutation {
                key,
                value: Some(initial.encode().unwrap()),
            }],
        })
        .unwrap();
    let current = fixture.store.snapshot().unwrap();
    let changed = RestoreWindow::capture(&current, &snapshot).unwrap();
    assert_eq!(
        changed.namespaces()[0].current.decode().unwrap().0.version,
        record.version
    );
    assert_ne!(
        changed.digest().unwrap(),
        acknowledgement.window_acknowledgement
    );
    assert_eq!(
        RestorePlan::prepare_until(
            &current,
            snapshot.clone(),
            &acknowledgement,
            deadline(),
            |_, _| panic!("changed linked rows reused an old acknowledgement")
        )
        .err(),
        Some(StoreError::Conflict)
    );
    let fresh = request(&current, &snapshot);
    assert_eq!(
        RestorePlan::prepare_until(&current, snapshot, &fresh, Instant::now(), |_, _| panic!(
            "expired operation reached review"
        ))
        .err(),
        Some(StoreError::SnapshotExpired)
    );
}

#[test]
fn interrupted_restore_leaves_durable_staging_and_never_changes_current_store_or_completes_recovery(
) {
    let fixture = fixture();
    let (bytes, snapshot) = export(&fixture);
    let current = fixture.store.snapshot().unwrap();
    let approved = request(&current, &snapshot);
    let (_directory, restored) = destination(StoreLimits {
        maximum_batch_rows: 1,
        ..StoreLimits::default()
    });
    let plan = RestorePlan::prepare(&current, snapshot, &approved, |_, _| Ok(())).unwrap();
    assert_eq!(
        plan.execute(
            &mut Cursor::new(&bytes[..bytes.len() - 1]),
            &restored,
            deadline(),
            |key, value| validate_row(&current, key, value),
            |_| panic!("interrupted input reached complete linked validation")
        )
        .err(),
        Some(StoreError::Corrupt)
    );
    let partial = restored.snapshot().unwrap();
    assert_eq!(
        RecoveryGuard::capture(&partial).unwrap().unwrap().status(),
        super::super::RecoveryStatus::Staging
    );
    assert!(!partial
        .scan(Family::Namespace, b"ns-v1\0", 128, 1024 * 1024)
        .unwrap()
        .is_empty());
    assert_eq!(
        crate::recovery::require_ready(&partial),
        Err(StoreError::Unavailable)
    );
    assert_eq!(RecoveryGuard::capture(&current).unwrap(), None);
    assert_eq!(
        current
            .scan(Family::State, b"", 128, 1024 * 1024)
            .unwrap()
            .len(),
        1
    );
    drop(current);
    assert_eq!(export(&fixture).1.snapshot_digest, approved.snapshot_digest);
}

#[test]
fn restore_quota_existing_destination_and_inconsistent_linked_inventory_refuse_before_unpausing() {
    let fixture = fixture();
    let (bytes, snapshot) = export(&fixture);
    let current = fixture.store.snapshot().unwrap();
    let approved = request(&current, &snapshot);
    let plan = RestorePlan::prepare(&current, snapshot.clone(), &approved, |_, _| Ok(())).unwrap();
    assert_eq!(
        plan.require_capacity(StoreLimits {
            maximum_rows: 3,
            ..StoreLimits::default()
        }),
        Err(StoreError::Capacity)
    );
    let (_directory, restored) = destination(StoreLimits::default());
    restored
        .apply(
            RecoveryGuard::staging([1; 32], [2; 32], [3; 32])
                .unwrap()
                .prepare_staging()
                .unwrap(),
        )
        .unwrap();
    assert_eq!(
        plan.execute(
            &mut Cursor::new(&bytes),
            &restored,
            deadline(),
            |_, _| Ok(()),
            |_| panic!("existing destination reached validation")
        )
        .err(),
        Some(StoreError::Conflict)
    );
    let plan = RestorePlan::prepare(&current, snapshot, &approved, |_, _| Ok(())).unwrap();
    let (_other, fresh) = destination(StoreLimits::default());
    assert_eq!(
        plan.execute(
            &mut Cursor::new(&bytes),
            &fresh,
            deadline(),
            |key, value| validate_row(&current, key, value),
            |_| Err(StoreError::Corrupt)
        )
        .err(),
        Some(StoreError::Corrupt)
    );
    assert_eq!(
        RecoveryGuard::capture(&fresh.snapshot().unwrap())
            .unwrap()
            .unwrap()
            .status(),
        super::super::RecoveryStatus::Staging
    );
}

#[test]
fn checked_restore_fences_each_durable_write_and_preserves_failed_staging_without_touching_source()
{
    let fixture = fixture();
    let (bytes, snapshot) = export(&fixture);
    let current = fixture.store.snapshot().unwrap();
    let approved = request(&current, &snapshot);
    for failure_at in [1, 2, 4] {
        let plan =
            RestorePlan::prepare(&current, snapshot.clone(), &approved, |_, _| Ok(())).unwrap();
        let (_directory, fresh) = destination(StoreLimits::default());
        let mut checks = 0;
        let result = plan.execute_checked(
            &mut Cursor::new(&bytes),
            &fresh,
            deadline(),
            RestoreChecks {
                row: |key: &RowKey, value: &[u8]| validate_row(&current, key, value),
                view: |view: &ReadView| closure(view, &fixture.metadata),
                fence: || {
                    checks += 1;
                    if checks == failure_at {
                        Err(StoreError::Unavailable)
                    } else {
                        Ok(())
                    }
                },
            },
        );
        assert_eq!(
            result.err(),
            Some(if failure_at == 1 {
                StoreError::Unavailable
            } else {
                StoreError::CommitUncertain
            })
        );
        let guard = RecoveryGuard::capture(&fresh.snapshot().unwrap()).unwrap();
        if failure_at == 1 {
            assert!(guard.is_none());
        } else {
            assert_eq!(
                guard.unwrap().status(),
                super::super::RecoveryStatus::Staging
            );
        }
    }
    drop(current);
    assert_eq!(export(&fixture).1.snapshot_digest, snapshot.snapshot_digest);
}
