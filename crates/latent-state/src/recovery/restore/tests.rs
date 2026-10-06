//! Actual selected-engine/archive histories. These descriptions are not a
//! qualified fresh-root import, authenticated operator or provider campaign.
use super::*;
use crate::{
    embedded::{AtomicBatch, RowKey, RowMutation},
    namespace::{history::history_key, NamespaceStatus},
    recovery::{
        migration::{tests::fixture, AggregateMigrationRecipe},
        snapshot::inspect_snapshot,
    },
    session::version::ViewIdentity,
};
use std::{io::Cursor, time::Duration};

fn fixture() -> fixture::Fixture {
    fixture::Fixture::new(AggregateMigrationRecipe::Count, true)
}
fn receipt(fixture: &fixture::Fixture) -> SnapshotReceipt {
    let view = fixture.store.snapshot().unwrap();
    inspect_snapshot(
        &mut Cursor::new(&fixture.archive),
        fixture::deadline(),
        |key, bytes| fixture::row(&view, key, bytes),
    )
    .unwrap()
}

#[test]
fn exact_original_window_preserves_ids_and_proposes_only_paused_fresh_live_tokens() {
    let fixture = fixture();
    let snapshot = receipt(&fixture);
    let view = fixture.store.snapshot().unwrap();
    let before = visit_view(&view, fixture::deadline(), |_, _, _| Ok(())).unwrap();
    let window = RestoreWindow::capture(&view, &snapshot, fixture::deadline(), || Ok(())).unwrap();
    assert_eq!(window.namespaces().len(), 1);
    let entry = &window.namespaces()[0];
    let (record, original) = entry.snapshot().decode().unwrap();
    assert_eq!(
        record.version.incarnation,
        fixture.request.scope.incarnation
    );
    assert_eq!(record.status, NamespaceStatus::Quiescing);
    let proposed = entry.proposed_history().unwrap();
    assert_eq!(proposed.epochs.schema, original.epochs.schema);
    assert_eq!(proposed.epochs.recovery, original.epochs.recovery + 1);
    assert_eq!(
        proposed.status,
        crate::namespace::history::HistoryStatus::ReconciliationRequired
    );
    let old = ViewIdentity {
        namespace: record.version,
        epochs: original.epochs,
    };
    let proposed_token = ViewIdentity {
        namespace: record.version,
        epochs: proposed.epochs,
    }
    .token(&fixture.request.scope)
    .unwrap();
    assert_ne!(old.token(&fixture.request.scope).unwrap(), proposed_token);
    let after = visit_view(&view, fixture::deadline(), |_, _, _| Ok(())).unwrap();
    assert_eq!(
        (after.rows, after.logical_bytes, after.digest),
        (before.rows, before.logical_bytes, before.digest)
    );
    let again = RestoreWindow::capture(&view, &snapshot, fixture::deadline(), || Ok(())).unwrap();
    assert_eq!(again.digest().unwrap(), window.digest().unwrap());
    assert_eq!(window.snapshot_digest(), snapshot.snapshot_digest);
    assert_eq!(window.manifest_digest(), snapshot.manifest_digest);
}

#[test]
fn newer_original_recovery_epoch_changes_the_acknowledged_whole_unit_window() {
    let fixture = fixture();
    let snapshot = receipt(&fixture);
    let view = fixture.store.snapshot().unwrap();
    let before = RestoreWindow::capture(&view, &snapshot, fixture::deadline(), || Ok(())).unwrap();
    let (_, mut history) = before.namespaces()[0].current().decode().unwrap();
    history.epochs.recovery = 9;
    let key = history_key(&history.tenant, &history.namespace, history.incarnation).unwrap();
    drop(view);
    fixture
        .store
        .apply(AtomicBatch {
            expectations: vec![],
            mutations: vec![RowMutation {
                key,
                value: Some(history.encode().unwrap()),
            }],
        })
        .unwrap();
    let view = fixture.store.snapshot().unwrap();
    let after = RestoreWindow::capture(&view, &snapshot, fixture::deadline(), || Ok(())).unwrap();
    assert_ne!(before.digest().unwrap(), after.digest().unwrap());
    assert_ne!(before.current_rows_digest(), after.current_rows_digest());
    assert_eq!(
        after.namespaces()[0]
            .proposed_history()
            .unwrap()
            .epochs
            .recovery,
        10
    );
    assert_eq!(after.snapshot_digest(), before.snapshot_digest());
}

#[test]
fn changed_source_identity_wrong_roster_and_future_namespace_preconditions_refuse() {
    let fixture = fixture();
    let snapshot = receipt(&fixture);
    let view = fixture.store.snapshot().unwrap();
    let mut wrong_source = snapshot.clone();
    wrong_source.manifest.source_store_identity = StoreIdentity::new("another-owned-source".into())
        .unwrap()
        .encode();
    rehash(&mut wrong_source);
    assert!(matches!(
        RestoreWindow::capture(&view, &wrong_source, fixture::deadline(), || Ok(())),
        Err(SnapshotError::Review(StoreError::Conflict))
    ));
    let mut wrong_tenant = snapshot.clone();
    let (mut record, mut history) = wrong_tenant.manifest.namespaces[0].decode().unwrap();
    record.tenant.0 = "other-tenant".into();
    history.tenant = record.tenant.clone();
    wrong_tenant.manifest.namespaces[0].record = record.encode().unwrap();
    wrong_tenant.manifest.namespaces[0].history = history.encode().unwrap();
    rehash(&mut wrong_tenant);
    assert!(matches!(
        RestoreWindow::capture(&view, &wrong_tenant, fixture::deadline(), || Ok(())),
        Err(SnapshotError::Review(StoreError::Conflict))
    ));
    let mut future = snapshot.clone();
    let (mut record, _) = future.manifest.namespaces[0].decode().unwrap();
    record.version.generation += 1;
    future.manifest.namespaces[0].record = record.encode().unwrap();
    rehash(&mut future);
    assert!(matches!(
        RestoreWindow::capture(&view, &future, fixture::deadline(), || Ok(())),
        Err(SnapshotError::Review(StoreError::Conflict))
    ));
}

#[test]
fn current_refusal_during_scan_and_expired_original_deadline_stay_healthy() {
    let fixture = fixture();
    let snapshot = receipt(&fixture);
    let view = fixture.store.snapshot().unwrap();
    let before = visit_view(&view, fixture::deadline(), |_, _, _| Ok(())).unwrap();
    let mut calls = 0;
    assert!(matches!(
        RestoreWindow::capture(&view, &snapshot, fixture::deadline(), || {
            calls += 1;
            if calls >= 3 {
                Err(StoreError::Unavailable)
            } else {
                Ok(())
            }
        }),
        Err(SnapshotError::Review(StoreError::Unavailable))
    ));
    assert!(calls >= 3);
    assert!(matches!(
        RestoreWindow::capture(
            &view,
            &snapshot,
            Instant::now() - Duration::from_secs(1),
            || Ok(())
        ),
        Err(SnapshotError::Deadline)
    ));
    let after = visit_view(&view, fixture::deadline(), |_, _, _| Ok(())).unwrap();
    assert_eq!(
        (after.rows, after.logical_bytes, after.digest),
        (before.rows, before.logical_bytes, before.digest)
    );
    RestoreWindow::capture(&view, &snapshot, fixture::deadline(), || Ok(())).unwrap();
}

#[test]
fn malformed_original_history_is_source_corruption_and_epoch_exhaustion_is_refusal() {
    let fixture = fixture();
    let snapshot = receipt(&fixture);
    let (record, mut history) = snapshot.manifest.namespaces[0].decode().unwrap();
    let key = RowKey {
        family: crate::embedded::Family::Namespace,
        key: history_key(&record.tenant, &record.id, record.version.incarnation)
            .unwrap()
            .key,
    };
    fixture
        .store
        .apply(AtomicBatch {
            expectations: vec![],
            mutations: vec![RowMutation {
                key: key.clone(),
                value: Some(b"corrupt".to_vec()),
            }],
        })
        .unwrap();
    assert!(matches!(
        RestoreWindow::capture(
            &fixture.store.snapshot().unwrap(),
            &snapshot,
            fixture::deadline(),
            || Ok(())
        ),
        Err(SnapshotError::Source(StoreError::Corrupt))
    ));
    history.epochs.recovery = u64::MAX;
    fixture
        .store
        .apply(AtomicBatch {
            expectations: vec![],
            mutations: vec![RowMutation {
                key,
                value: Some(history.encode().unwrap()),
            }],
        })
        .unwrap();
    assert!(matches!(
        RestoreWindow::capture(
            &fixture.store.snapshot().unwrap(),
            &snapshot,
            fixture::deadline(),
            || Ok(())
        ),
        Err(SnapshotError::Capacity)
    ));
}

fn rehash(snapshot: &mut SnapshotReceipt) {
    snapshot.manifest_digest = Sha256::digest(snapshot.manifest.encode().unwrap()).into();
}
