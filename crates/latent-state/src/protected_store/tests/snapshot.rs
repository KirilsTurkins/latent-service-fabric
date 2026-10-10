//! Actual rooted-file/engine schedules; production Wire policy/audit composition
//! is separate and is not established by the controlled fixture callbacks here.
use super::*;
use crate::namespace::catalog::NamespaceCatalog;
use crate::namespace::compatibility::{RetainedInventory, SchemaId};
use crate::namespace::{
    namespace_record_key, NamespaceQuota, NamespaceRecord, NamespaceTransition,
};
use crate::recovery::snapshot::{
    visit_view, RequiredArtifact, SnapshotClosure, SnapshotError, SnapshotMetadata,
};
use crate::store_identity::StoreIdentity;
use latent_core::native_capacity::{
    NativeAdmissionClass, NativeCapacityOwner, NativeReservation, NativeReservationRequest,
};
use latent_core::{StateNamespaceId, SystemActivationClock, TenantId};
use sha2::{Digest, Sha256};
use std::os::unix::fs::PermissionsExt;

const DEFINITION: &[u8] =
    include_bytes!("../../../../../contracts/state/application-aggregate-v1.schema.json");

fn row(key: &RowKey, value: &[u8]) -> Result<(), StoreError> {
    if key == &StoreIdentity::row_key() {
        StoreIdentity::validate_row(key, value)
    } else {
        NamespaceCatalog::validate_row(key, value).map_err(|_| StoreError::Corrupt)
    }
}

fn source() -> (
    tempfile::TempDir,
    ProtectedStoreOwner,
    NativeCapacityOwner,
    Arc<NativeReservation>,
    SnapshotMetadata,
) {
    let (root, config) = fixture();
    let owner = wait(
        ProtectedStoreOwner::start_bound_validated_view_with_clock(
            config,
            StoreIdentity::new("original-protected-source".into()).unwrap(),
            0,
            |view| {
                visit_view(view, Instant::now() + WATCHDOG, |_, key, value| {
                    row(key, value)
                })?;
                Ok(())
            },
            Arc::new(SystemActivationClock),
        )
        .unwrap(),
    )
    .unwrap();
    let native = NativeCapacityOwner::new(Default::default()).unwrap();
    owner.bind_native_capacity(&native).unwrap();
    let original = Arc::new(
        native
            .reserve(
                NativeAdmissionClass::Recovery,
                NativeReservationRequest {
                    request_bytes: 8192,
                    work_bytes: 9 * 1024 * 1024,
                    response_bytes: 1024 * 1024,
                },
                Instant::now() + std::time::Duration::from_secs(30),
            )
            .unwrap(),
    );
    let schema = SchemaId::from_definition(DEFINITION).unwrap();
    let active = NamespaceRecord::create(
        TenantId("tenant".into()),
        StateNamespaceId("business".into()),
        schema.as_str().into(),
        NamespaceQuota::default(),
    )
    .unwrap();
    let record = active
        .transition(active.version, &NamespaceTransition::Quiesce, 0)
        .unwrap();
    wait(
        owner
            .with_store_retaining(
                StoreIoKind::RecoveryWrite,
                8192,
                Arc::clone(&original) as Arc<dyn std::any::Any + Send + Sync>,
                move |engine| {
                    engine.apply(AtomicBatch {
                        expectations: vec![],
                        mutations: vec![RowMutation {
                            key: RowKey {
                                family: Family::Namespace,
                                key: namespace_record_key(&record.tenant, &record.id).unwrap(),
                            },
                            value: Some(record.encode().unwrap()),
                        }],
                    })
                },
            )
            .unwrap(),
    )
    .unwrap()
    .unwrap();
    owner
        .ready
        .wait_test_metadata_retirement(Instant::now() + WATCHDOG);
    let metadata = SnapshotMetadata {
        tenant: "tenant".into(),
        operation_id: "backup-original".into(),
        operator_id: "operator".into(),
        runtime_digest: [90; 32],
        decoder_formats: vec![],
        required_artifacts: vec![RequiredArtifact {
            identity: schema.as_str().into(),
            digest: Sha256::digest(DEFINITION).into(),
        }],
    };
    (root, owner, native, original, metadata)
}

fn output() -> tempfile::TempDir {
    let (root, _) = fixture();
    root
}

fn create(
    owner: &ProtectedStoreOwner,
    root: PathBuf,
    original: Arc<NativeReservation>,
    metadata: SnapshotMetadata,
) -> Result<ProtectedSnapshotJob, ProtectedStoreError> {
    let artifacts = metadata.required_artifacts.clone();
    owner.create_snapshot(
        ProtectedSnapshotConfig {
            root,
            file_name: "original-backup.v2".into(),
        },
        metadata,
        original,
        move |view| {
            visit_view(view, Instant::now() + WATCHDOG, |_, key, value| {
                row(key, value)
            })?;
            Ok(SnapshotClosure {
                inventory: RetainedInventory::default(),
                required_artifacts: artifacts,
            })
        },
        |artifact| {
            if artifact.digest == <[u8; 32]>::from(Sha256::digest(DEFINITION)) {
                Ok(())
            } else {
                Err(StoreError::Corrupt)
            }
        },
        row,
        Arc::new(|| Ok(())), // controlled current fixture reader, no production grant
    )
}

#[test]
fn rooted_snapshot_uses_original_recovery_capacity_and_readback_before_receipt() {
    let (_source, owner, native, original, metadata) = source();
    let target = output();
    let (mut snapshot, receipt) = wait(
        create(
            &owner,
            target.path().to_path_buf(),
            Arc::clone(&original),
            metadata,
        )
        .unwrap(),
    )
    .unwrap();
    let receipt = receipt.unwrap().unwrap();
    let witness = snapshot.retirement_witness().unwrap();
    assert!(owner.snapshot().unwrap().custody_active);
    assert_eq!(native.snapshot().unwrap().recovery.slots, 1);
    let file = target.path().join("original-backup.v2");
    assert_eq!(
        fs::metadata(&file).unwrap().permissions().mode() & 0o777,
        0o600
    );
    assert_eq!(fs::metadata(&file).unwrap().len(), receipt.file_bytes);
    assert_eq!(
        receipt.snapshot_digest,
        <[u8; 32]>::from(Sha256::digest(fs::read(file).unwrap()))
    );
    let (snapshot, inspected) =
        wait(owner.inspect_created_snapshot(snapshot, row).unwrap()).unwrap();
    assert_eq!(inspected.unwrap().unwrap(), receipt);
    assert!(!witness.has_retired());
    wait(snapshot.retire());
    owner
        .ready
        .wait_test_metadata_retirement(Instant::now() + WATCHDOG);
    assert!(witness.has_retired());
    assert!(!owner.snapshot().unwrap().custody_active);
    drop(original);
    assert_eq!(native.snapshot().unwrap().recovery.slots, 0);
    assert!(finish(&owner).clean);
}

#[test]
fn real_native_query_view_refuses_snapshot_until_its_actual_reserved_retirement() {
    let (_source, owner, _native, original, metadata) = source();
    let view = wait(
        owner
            .open_recovery_view_retaining(
                Arc::clone(&original) as Arc<dyn std::any::Any + Send + Sync>
            )
            .unwrap(),
    )
    .unwrap()
    .unwrap();
    let target = output();
    assert!(matches!(
        create(
            &owner,
            target.path().to_path_buf(),
            Arc::clone(&original),
            metadata.clone()
        ),
        Err(ProtectedStoreError::Io(StoreIoError::CustodyBusy))
    ));
    assert!(!target.path().join("original-backup.v2").exists());
    wait(view.retire());
    owner
        .ready
        .wait_test_metadata_retirement(Instant::now() + WATCHDOG);
    let (snapshot, result) =
        wait(create(&owner, target.path().to_path_buf(), original, metadata).unwrap()).unwrap();
    result.unwrap().unwrap();
    wait(snapshot.retire());
    assert!(finish(&owner).clean);
}

#[test]
fn unsafe_output_existing_leaf_and_foreign_global_owner_refuse_without_source_quarantine() {
    let (source, owner, _native, original, metadata) = source();
    let (snapshot, refused) = wait(
        create(
            &owner,
            source.path().to_path_buf(),
            Arc::clone(&original),
            metadata.clone(),
        )
        .unwrap(),
    )
    .unwrap();
    assert_eq!(
        refused.unwrap(),
        Err(SnapshotError::Review(StoreError::Invalid))
    );
    wait(snapshot.retire());
    owner
        .ready
        .wait_test_metadata_retirement(Instant::now() + WATCHDOG);
    assert_eq!(owner.failure(), None);
    let foreign = NativeCapacityOwner::new(Default::default()).unwrap();
    let foreign_reservation = Arc::new(
        foreign
            .reserve(
                NativeAdmissionClass::Recovery,
                NativeReservationRequest {
                    work_bytes: 9 * 1024 * 1024,
                    ..Default::default()
                },
                Instant::now() + WATCHDOG,
            )
            .unwrap(),
    );
    let target = output();
    assert!(matches!(
        create(
            &owner,
            target.path().to_path_buf(),
            foreign_reservation,
            metadata.clone()
        ),
        Err(ProtectedStoreError::InvalidConfiguration)
    ));
    let path = target.path().join("original-backup.v2");
    std::os::unix::fs::symlink(source.path().join("transaction-state.redb"), &path).unwrap();
    let (snapshot, refused) =
        wait(create(&owner, target.path().to_path_buf(), original, metadata).unwrap()).unwrap();
    assert_eq!(refused.unwrap(), Err(SnapshotError::Output));
    wait(snapshot.retire());
    owner
        .ready
        .wait_test_metadata_retirement(Instant::now() + WATCHDOG);
    assert!(fs::symlink_metadata(path).unwrap().file_type().is_symlink());
    assert_eq!(owner.failure(), None);
    assert!(finish(&owner).clean);
}
