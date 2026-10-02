//! Real original rows/closure and descriptive receipt/precondition schedules.
//! The receipt builder is a controlled metadata fixture, not protected archive
//! readback, fresh destination approval or an actual remote-effect campaign.
use super::*;
use crate::recovery_review::{review_restore_input, RestoreInputRequest};
use latent_core::StateNamespaceId;
use latent_state::{
    namespace::{history::NamespaceHistory, namespace_record_key},
    recovery::{
        restore::RestoreWindow,
        snapshot::{visit_view, NamespaceSnapshot, SnapshotManifest, SnapshotReceipt},
    },
};
use sha2::{Digest, Sha256};

fn deadline() -> Instant {
    Instant::now() + Duration::from_secs(20)
}
fn workload() -> Fixture {
    let fixture = Fixture::new(true);
    fixture.command("successful", None, b"count".to_vec(), false);
    fixture.command("rejected", None, b"not-written".to_vec(), true);
    fixture.uncertain();
    fixture.quiesce();
    fixture
}
fn receipt(fixture: &Fixture, metadata: &SnapshotMetadata) -> SnapshotReceipt {
    let view = fixture.store.snapshot().unwrap();
    let reviewed = review_snapshot(
        &view,
        request(fixture, metadata),
        &mut Owners::new(),
        || Ok(()),
    )
    .unwrap();
    let mut namespaces: Vec<_> = fixture
        .quotas
        .iter()
        .map(|quota| {
            let row = RowKey {
                family: Family::Namespace,
                key: namespace_record_key(&quota.tenant, &StateNamespaceId("aggregate".into()))
                    .unwrap(),
            };
            let bytes = view.get(&row).unwrap().unwrap();
            let namespace = latent_state::namespace::NamespaceRecord::decode(&bytes).unwrap();
            NamespaceSnapshot {
                record: bytes,
                history: NamespaceHistory::capture(&view, &namespace)
                    .unwrap()
                    .0
                    .encode()
                    .unwrap(),
            }
        })
        .collect();
    namespaces.sort_by_key(|namespace| {
        let (record, _) = namespace.decode().unwrap();
        namespace_record_key(&record.tenant, &record.id).unwrap()
    });
    let walked = visit_view(&view, deadline(), |_, _, _| Ok(())).unwrap();
    let inventory: Vec<_> = reviewed
        .closure()
        .inventory
        .entries()
        .iter()
        .map(|(format, count)| serde_json::json!({"format":format, "count":count}))
        .collect();
    let manifest: SnapshotManifest = serde_json::from_value(serde_json::json!({
        "format":"latent.offline-snapshot.v2", "engine":latent_state::embedded::STORE_FORMAT,
        "source_store_identity":reviewed.source_controls().store_identity().encode(),
        "metadata":metadata, "namespaces":namespaces, "rows":walked.rows,
        "logical_bytes":walked.logical_bytes, "rows_digest":walked.digest, "inventory":inventory,
    }))
    .unwrap();
    let manifest_digest = Sha256::digest(manifest.encode().unwrap()).into();
    SnapshotReceipt {
        snapshot_digest: [77; 32],
        manifest_digest,
        file_bytes: 4096,
        manifest,
    }
}
fn request<'a>(fixture: &'a Fixture, metadata: &'a SnapshotMetadata) -> RecoveryReviewRequest<'a> {
    RecoveryReviewRequest {
        quotas: &fixture.quotas,
        global_allowance: INSTALLED_GLOBAL_ALLOWANCE,
        metadata,
        deadline: deadline(),
    }
}
fn operation(fixture: &Fixture, snapshot: &SnapshotReceipt) -> RestoreInputRequest {
    let window = RestoreWindow::capture(
        &fixture.store.snapshot().unwrap(),
        snapshot,
        deadline(),
        || Ok(()),
    )
    .unwrap();
    RestoreInputRequest {
        operation_id: "original-restore-input".into(),
        operator_id: "current-operator".into(),
        snapshot_digest: snapshot.snapshot_digest,
        manifest_digest: snapshot.manifest_digest,
        runtime_digest: fixture::RUNTIME,
        window_acknowledgement: window.digest().unwrap(),
    }
}

#[test]
fn acknowledged_full_unit_preserves_rejection_inbox_uncertainty_and_original_operation() {
    let fixture = workload();
    let metadata = fixture.metadata();
    let snapshot = receipt(&fixture, &metadata);
    let operation = operation(&fixture, &snapshot);
    let view = fixture.store.snapshot().unwrap();
    let before = visit_view(&view, deadline(), |_, _, _| Ok(())).unwrap();
    let prepare = || {
        review_restore_input(
            &view,
            &snapshot,
            &operation,
            request(&fixture, &metadata),
            &mut Owners::new(),
            |artifact| {
                if metadata.required_artifacts.contains(artifact) {
                    Ok(())
                } else {
                    Err(StoreError::UnsupportedFormat)
                }
            },
            || Ok(()),
        )
        .unwrap()
    };
    let prepared = prepare();
    assert_eq!(prepared.window().namespaces().len(), 2);
    assert!(prepared.current().closure().inventory.total().unresolved > 0);
    assert!(prepared
        .current()
        .closure()
        .inventory
        .entries()
        .contains_key(&RetainedFormat {
            kind: RetainedKind::RejectionResult,
            identity: "latent.result.v1/3".into(),
        }));
    assert_eq!(prepare().operation_digest(), prepared.operation_digest());
    let after = visit_view(&view, deadline(), |_, _, _| Ok(())).unwrap();
    assert_eq!(
        (before.rows, before.logical_bytes, before.digest),
        (after.rows, after.logical_bytes, after.digest)
    );
    assert!(latent_state::recovery::RecoveryGuard::capture(&view)
        .unwrap()
        .is_none());
}

#[test]
fn absent_original_decoder_or_artifact_refuses_with_healthy_reusable_current_history() {
    let fixture = workload();
    let metadata = fixture.metadata();
    let snapshot = receipt(&fixture, &metadata);
    let operation = operation(&fixture, &snapshot);
    let view = fixture.store.snapshot().unwrap();
    let mut owners = Owners::new();
    owners.formats.remove(&RetainedFormat {
        kind: RetainedKind::RejectionResult,
        identity: "latent.result.v1/3".into(),
    });
    assert!(matches!(
        review_restore_input(
            &view,
            &snapshot,
            &operation,
            request(&fixture, &metadata),
            &mut owners,
            |_| Ok(()),
            || Ok(())
        ),
        Err(RecoveryReviewError::Review(StoreError::UnsupportedFormat))
    ));
    assert!(matches!(
        review_restore_input(
            &view,
            &snapshot,
            &operation,
            request(&fixture, &metadata),
            &mut Owners::new(),
            |_| Err(StoreError::Unavailable),
            || Ok(())
        ),
        Err(RecoveryReviewError::Review(StoreError::Unavailable))
    ));
    fixture.review(&metadata, &mut Owners::new()).unwrap();
}

#[test]
fn stale_window_wrong_runtime_and_revoked_current_access_never_refresh_preconditions() {
    let fixture = workload();
    let metadata = fixture.metadata();
    let snapshot = receipt(&fixture, &metadata);
    let mut operation = operation(&fixture, &snapshot);
    let original = operation.window_acknowledgement;
    let view = fixture.store.snapshot().unwrap();
    operation.window_acknowledgement = [88; 32];
    assert!(matches!(
        review_restore_input(
            &view,
            &snapshot,
            &operation,
            request(&fixture, &metadata),
            &mut Owners::new(),
            |_| Ok(()),
            || Ok(())
        ),
        Err(RecoveryReviewError::Review(StoreError::Conflict))
    ));
    assert_eq!(operation.window_acknowledgement, [88; 32]);
    operation.window_acknowledgement = original;
    operation.runtime_digest = [89; 32];
    assert!(matches!(
        review_restore_input(
            &view,
            &snapshot,
            &operation,
            request(&fixture, &metadata),
            &mut Owners::new(),
            |_| Ok(()),
            || Ok(())
        ),
        Err(RecoveryReviewError::Review(StoreError::Conflict))
    ));
    operation.runtime_digest = fixture::RUNTIME;
    let mut calls = 0;
    assert!(matches!(
        review_restore_input(
            &view,
            &snapshot,
            &operation,
            request(&fixture, &metadata),
            &mut Owners::new(),
            |_| Ok(()),
            || {
                calls += 1;
                if calls >= 4 {
                    Err(StoreError::Unavailable)
                } else {
                    Ok(())
                }
            }
        ),
        Err(RecoveryReviewError::Review(StoreError::Unavailable))
    ));
    assert_eq!(operation.window_acknowledgement, original);
    fixture.review(&metadata, &mut Owners::new()).unwrap();
}
