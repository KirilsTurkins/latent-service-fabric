use super::*;
use crate::{
    embedded::{AtomicBatch, ExpectedRow, RowMutation, StoreLimits},
    namespace::{namespace_record_key, NamespaceQuota, NamespaceTransition},
    session::{SessionLimits, StateAccess, StateError, StateMode, StateScope, StateSession},
};
use latent_core::{transaction_contract::Value, StateNamespaceId, TenantId};
use std::{fs::OpenOptions, io::Cursor, time::Duration};

const DEFINITION: &[u8] =
    include_bytes!("../../../../../contracts/state/application-aggregate-v1.schema.json");

struct Fixture {
    store: EmbeddedStore,
    metadata: SnapshotMetadata,
    _directory: tempfile::TempDir,
}

fn fixture() -> Fixture {
    let directory = tempfile::tempdir().unwrap();
    let file = OpenOptions::new()
        .read(true)
        .write(true)
        .create_new(true)
        .open(directory.path().join("snapshot.redb"))
        .unwrap();
    let store = EmbeddedStore::open_file(
        file,
        StoreLimits {
            cache_bytes: 1024 * 1024,
            ..StoreLimits::default()
        },
    )
    .unwrap();
    let schema = SchemaId::from_definition(DEFINITION).unwrap();
    let scope = StateScope {
        tenant: TenantId("tenant".into()),
        namespace: StateNamespaceId("business".into()),
        incarnation: 1,
        state_schema: schema.as_str().into(),
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
    let key = RowKey {
        family: Family::Namespace,
        key: namespace_record_key(&record.tenant, &record.id).unwrap(),
    };
    store
        .apply(AtomicBatch {
            expectations: vec![],
            mutations: vec![RowMutation {
                key: key.clone(),
                value: Some(record.encode().unwrap()),
            }],
        })
        .unwrap();
    let view = store.snapshot().unwrap();
    let mut session = StateSession::open(&view, scope, SessionLimits::default(), allow).unwrap();
    session
        .put(
            &view,
            b"count".to_vec(),
            Value {
                bytes: 7u64.to_le_bytes().to_vec(),
                media_type: "application/vnd.lsf.aggregate-v1".into(),
                metadata: vec![],
            },
            allow,
        )
        .unwrap();
    let plan = session.seal(&view, allow).unwrap();
    let mut batch = AtomicBatch::default();
    plan.append_to(&mut batch, crate::namespace::NamespacePins::default())
        .unwrap();
    store.apply(batch).unwrap();
    drop(view);
    let view = store.snapshot().unwrap();
    let original = view.get(&key).unwrap().unwrap();
    let record = NamespaceRecord::decode(&original).unwrap();
    let quiesced = record
        .transition(record.version, &NamespaceTransition::Quiesce, 0)
        .unwrap();
    drop(view);
    store
        .apply(AtomicBatch {
            expectations: vec![ExpectedRow {
                key: key.clone(),
                value: Some(original),
            }],
            mutations: vec![RowMutation {
                key,
                value: Some(quiesced.encode().unwrap()),
            }],
        })
        .unwrap();
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
    Fixture {
        store,
        metadata,
        _directory: directory,
    }
}

fn allow(scope: &StateScope, _: StateAccess) -> Result<(), StateError> {
    if scope.tenant.0 == "tenant" {
        Ok(())
    } else {
        Err(StateError::PermissionDenied)
    }
}

fn deadline() -> Instant {
    Instant::now() + Duration::from_secs(20)
}

fn validate_row(view: &ReadView, key: &RowKey, bytes: &[u8]) -> Result<(), StoreError> {
    if key.family == Family::Namespace {
        NamespaceCatalog::validate_row(key, bytes).map_err(|_| StoreError::Corrupt)
    } else {
        crate::session::validate_row(view, key, bytes)
    }
}

fn closure(view: &ReadView, metadata: &SnapshotMetadata) -> Result<SnapshotClosure, StoreError> {
    for family in FAMILIES {
        let page = view.scan_after(family, b"", None, 128, PAGE_BYTES)?;
        if page.resume.is_some() {
            return Err(StoreError::Capacity);
        }
        for (key, bytes) in page.rows {
            validate_row(view, &key, &bytes)?;
        }
    }
    Ok(SnapshotClosure {
        inventory: RetainedInventory::default(),
        required_artifacts: metadata.required_artifacts.clone(),
    })
}

fn export(fixture: &Fixture) -> (Vec<u8>, SnapshotReceipt) {
    let mut output = Vec::new();
    let receipt = export_snapshot(
        &fixture.store,
        fixture.metadata.clone(),
        &mut output,
        deadline(),
        |view| closure(view, &fixture.metadata),
        |artifact| {
            if artifact.digest == <[u8; 32]>::from(Sha256::digest(DEFINITION)) {
                Ok(())
            } else {
                Err(StoreError::Corrupt)
            }
        },
    )
    .unwrap();
    (output, receipt)
}

#[test]
fn actual_engine_snapshot_stream_retains_exact_rows_and_source_schema_history() {
    let fixture = fixture();
    let (bytes, receipt) = export(&fixture);
    let view = fixture.store.snapshot().unwrap();
    let inspected = inspect_snapshot(&mut Cursor::new(&bytes), deadline(), |key, bytes| {
        validate_row(&view, key, bytes)
    })
    .unwrap();
    assert_eq!(receipt, inspected);
    assert_eq!(
        receipt.snapshot_digest,
        <[u8; 32]>::from(Sha256::digest(&bytes))
    );
    assert_eq!(receipt.file_bytes, u64::try_from(bytes.len()).unwrap());
    let (namespace, history) = receipt.manifest.namespaces[0].decode().unwrap();
    assert_eq!(namespace.version.incarnation, 1);
    assert_eq!(namespace.version.generation, 3);
    assert_eq!(namespace.status, NamespaceStatus::Quiescing);
    assert_eq!(history.epochs.recovery, 1);
    assert_eq!(receipt.manifest.rows, 3);
    drop(view);
    let (again, second) = export(&fixture);
    assert_eq!(again, bytes);
    assert_eq!(receipt, second);
}

#[test]
fn retained_view_active_namespace_missing_artifact_and_linked_validator_refuse_before_export() {
    let fixture = fixture();
    let view = fixture.store.snapshot().unwrap();
    let mut output = Vec::new();
    assert_eq!(
        export_snapshot(
            &fixture.store,
            fixture.metadata.clone(),
            &mut output,
            deadline(),
            |_| panic!("live reader reached export validation"),
            |_| Ok(())
        )
        .unwrap_err(),
        StoreError::Conflict
    );
    drop(view);
    assert!(output.is_empty());
    assert_eq!(
        export_snapshot(
            &fixture.store,
            fixture.metadata.clone(),
            &mut output,
            deadline(),
            |_| Err(StoreError::Corrupt),
            |_| Ok(())
        )
        .unwrap_err(),
        StoreError::Corrupt
    );
    assert!(output.is_empty());
    let mut missing = fixture.metadata.clone();
    missing.required_artifacts.clear();
    assert_eq!(
        export_snapshot(
            &fixture.store,
            missing,
            &mut output,
            deadline(),
            |view| closure(view, &fixture.metadata),
            |_| Ok(())
        )
        .unwrap_err(),
        StoreError::Corrupt
    );
    assert!(output.is_empty());
    assert_eq!(
        export_snapshot(
            &fixture.store,
            fixture.metadata.clone(),
            &mut output,
            deadline(),
            |view| closure(view, &fixture.metadata),
            |_| Err(StoreError::Unavailable)
        )
        .unwrap_err(),
        StoreError::Unavailable
    );
    assert!(output.is_empty());
    let view = fixture.store.snapshot().unwrap();
    let key = view.scan(Family::Namespace, b"ns-v1\0", 1, 4096).unwrap()[0]
        .0
        .clone();
    let original = view.get(&key).unwrap().unwrap();
    let mut active = NamespaceRecord::decode(&original).unwrap();
    active.status = NamespaceStatus::Active;
    drop(view);
    fixture
        .store
        .apply(AtomicBatch {
            expectations: vec![],
            mutations: vec![RowMutation {
                key,
                value: Some(active.encode().unwrap()),
            }],
        })
        .unwrap();
    assert_eq!(
        export_snapshot(
            &fixture.store,
            fixture.metadata.clone(),
            &mut output,
            deadline(),
            |_| panic!("active namespace reached linked export"),
            |_| Ok(())
        )
        .unwrap_err(),
        StoreError::Conflict
    );
    assert!(output.is_empty());
}

#[test]
fn snapshot_manifest_rejects_unknown_runtime_duplicate_fields_wrong_scope_and_missing_decoder() {
    let fixture = fixture();
    let (_, receipt) = export(&fixture);
    let encoded = receipt.manifest.encode().unwrap();
    let mut wrong = receipt.manifest.clone();
    wrong.engine = "latent.transaction-store.v999".into();
    assert_eq!(wrong.encode(), Err(StoreError::UnsupportedFormat));
    wrong = receipt.manifest.clone();
    wrong.metadata.tenant = "foreign".into();
    assert_eq!(wrong.encode(), Err(StoreError::Conflict));
    wrong = receipt.manifest.clone();
    wrong.metadata.required_artifacts[0].digest = [4; 32];
    assert_eq!(wrong.encode(), Err(StoreError::Corrupt));
    let mut duplicate = b"{\"format\":\"latent.offline-snapshot.v1\",".to_vec();
    duplicate.extend_from_slice(&encoded[1..]);
    assert_eq!(
        SnapshotManifest::decode(&duplicate),
        Err(StoreError::Corrupt)
    );
    let mut unknown = b"{\"unbounded\":[],".to_vec();
    unknown.extend_from_slice(&encoded[1..]);
    assert_eq!(SnapshotManifest::decode(&unknown), Err(StoreError::Corrupt));
    wrong = receipt.manifest;
    wrong.inventory.push(InventoryEntry {
        format: RetainedFormat {
            kind: crate::namespace::compatibility::RetainedKind::EffectPayload,
            identity: "original-v1".into(),
        },
        count: RetainedCount {
            rows: 1,
            bytes: 12,
            unresolved: 1,
        },
    });
    assert_eq!(wrong.encode(), Err(StoreError::UnsupportedFormat));
}

#[test]
fn interrupted_corrupt_unsupported_and_trailing_streams_never_produce_a_usable_receipt() {
    let fixture = fixture();
    let (bytes, _) = export(&fixture);
    let view = fixture.store.snapshot().unwrap();
    for length in [0, MAGIC.len(), bytes.len() - 1] {
        assert!(inspect_snapshot(
            &mut Cursor::new(&bytes[..length]),
            deadline(),
            |key, value| validate_row(&view, key, value)
        )
        .is_err());
    }
    let mut corrupt = bytes.clone();
    corrupt[MAGIC.len() + 1] = 99;
    assert_eq!(
        inspect_snapshot(&mut Cursor::new(corrupt), deadline(), |key, value| {
            validate_row(&view, key, value)
        })
        .unwrap_err(),
        StoreError::UnsupportedFormat
    );
    let mut trailing = bytes;
    trailing.push(0);
    assert_eq!(
        inspect_snapshot(&mut Cursor::new(trailing), deadline(), |key, value| {
            validate_row(&view, key, value)
        })
        .unwrap_err(),
        StoreError::Corrupt
    );
    assert_eq!(
        inspect_snapshot(
            &mut Cursor::new(Vec::<u8>::new()),
            Instant::now(),
            |_, _| Ok(())
        )
        .unwrap_err(),
        StoreError::SnapshotExpired
    );
    assert_eq!(
        inspect_snapshot(
            &mut Cursor::new(Vec::<u8>::new()),
            Instant::now() + Duration::from_mins(2),
            |_, _| panic!("excessive deadline reached a decoder")
        )
        .unwrap_err(),
        StoreError::Capacity
    );
}
