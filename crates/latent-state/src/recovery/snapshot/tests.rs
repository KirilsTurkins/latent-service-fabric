//! Real redb/archive schedules. Fixture-only closed row codecs exercise all
//! ten families; they do not qualify production command/effect codec closure.
use super::*;
use crate::embedded::{AtomicBatch, RowMutation, StoreLimits};
use crate::namespace::compatibility::RetainedKind;
use crate::namespace::{namespace_record_key, NamespaceQuota, NamespaceTransition};
use crate::store_identity::StoreIdentity;
use latent_core::{StateNamespaceId, TenantId};
use std::io::Cursor;

#[test]
fn legacy_snapshot_decoder_refuses_original_v2_archive_before_any_row_callback() {
    let fixture = fixture();
    let (bytes, _) = export(&fixture);
    let mut callbacks = 0;
    let refused = crate::recovery::v1::snapshot::inspect_snapshot(
        &mut Cursor::new(bytes),
        deadline(),
        |_, _| {
            callbacks += 1;
            Ok(())
        },
    );
    assert_eq!(refused, Err(StoreError::UnsupportedFormat));
    assert_eq!(callbacks, 0);
}

const DEFINITION: &[u8] =
    include_bytes!("../../../../../contracts/state/application-aggregate-v1.schema.json");
const FIXTURE_KEY: &[u8] = b"closed-codec-fixture-v1\0";

struct Fixture {
    store: EmbeddedStore,
    metadata: SnapshotMetadata,
    _root: tempfile::TempDir,
}

fn fixture() -> Fixture {
    let root = tempfile::tempdir().unwrap();
    let file = std::fs::OpenOptions::new()
        .read(true)
        .write(true)
        .create_new(true)
        .open(root.path().join("archive.redb"))
        .unwrap();
    let store = EmbeddedStore::open_file(
        file,
        StoreLimits {
            cache_bytes: 1024 * 1024,
            ..StoreLimits::default()
        },
    )
    .unwrap();
    let identity = StoreIdentity::new("original-snapshot-source".into()).unwrap();
    let view = store.snapshot().unwrap();
    let initial = identity.prepare_initialization(&view).unwrap().unwrap();
    drop(view);
    store.apply(initial).unwrap();
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
    let mut mutations = vec![RowMutation {
        key: RowKey {
            family: Family::Namespace,
            key: namespace_record_key(&record.tenant, &record.id).unwrap(),
        },
        value: Some(record.encode().unwrap()),
    }];
    for family in FAMILIES {
        mutations.push(RowMutation {
            key: RowKey {
                family,
                key: FIXTURE_KEY.to_vec(),
            },
            value: Some(vec![family as u8, 0, 255, 19]),
        });
    }
    store
        .apply(AtomicBatch {
            expectations: vec![],
            mutations,
        })
        .unwrap();
    let metadata = SnapshotMetadata {
        tenant: "tenant".into(),
        operation_id: "backup-original".into(),
        operator_id: "operator".into(),
        runtime_digest: [90; 32],
        decoder_formats: vec![RetainedFormat {
            kind: RetainedKind::CommandFingerprint,
            identity: "closed-fixture-v1".into(),
        }],
        required_artifacts: vec![RequiredArtifact {
            identity: schema.as_str().into(),
            digest: Sha256::digest(DEFINITION).into(),
        }],
    };
    Fixture {
        store,
        metadata,
        _root: root,
    }
}

fn deadline() -> Instant {
    Instant::now() + Duration::from_secs(20)
}

fn validate_row(key: &RowKey, value: &[u8]) -> Result<(), StoreError> {
    if key == &StoreIdentity::row_key() {
        return StoreIdentity::validate_row(key, value);
    }
    if key.family == Family::Namespace && key.key.starts_with(b"ns-v1\0") {
        return NamespaceCatalog::validate_row(key, value).map_err(|_| StoreError::Corrupt);
    }
    if key.family == Family::Namespace
        && key
            .key
            .starts_with(crate::namespace::history::HISTORY_PREFIX)
    {
        return NamespaceHistory::validate_row(key, value).map_err(|_| StoreError::Corrupt);
    }
    if key.key != FIXTURE_KEY || value != [key.family as u8, 0, 255, 19] {
        return Err(StoreError::UnsupportedFormat);
    }
    Ok(())
}

fn closure(view: &ReadView, metadata: &SnapshotMetadata) -> Result<SnapshotClosure, StoreError> {
    visit_view(view, deadline(), |_, key, value| validate_row(key, value))?;
    let mut inventory = RetainedInventory::default();
    inventory
        .observe(
            metadata.decoder_formats[0].clone(),
            RetainedCount {
                rows: 10,
                bytes: 40,
                unresolved: 3,
            },
        )
        .map_err(|_| StoreError::Corrupt)?;
    Ok(SnapshotClosure {
        inventory,
        required_artifacts: metadata.required_artifacts.clone(),
    })
}

fn export(fixture: &Fixture) -> (Vec<u8>, SnapshotReceipt) {
    let mut bytes = Vec::new();
    let receipt = export_snapshot(
        &fixture.store,
        fixture.metadata.clone(),
        &mut bytes,
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
    (bytes, receipt)
}

#[test]
fn actual_engine_snapshot_captures_all_ten_families_and_exact_source_identity() {
    let fixture = fixture();
    let (bytes, receipt) = export(&fixture);
    let inspected = inspect_snapshot(&mut Cursor::new(&bytes), deadline(), validate_row).unwrap();
    assert_eq!(receipt, inspected);
    assert_eq!(
        receipt.snapshot_digest,
        <[u8; 32]>::from(Sha256::digest(&bytes))
    );
    assert_eq!(receipt.manifest.rows, 12);
    assert_eq!(
        StoreIdentity::decode(&receipt.manifest.source_store_identity)
            .unwrap()
            .as_str(),
        "original-snapshot-source"
    );
    let (namespace, history) = receipt.manifest.namespaces[0].decode().unwrap();
    assert_eq!(namespace.status, NamespaceStatus::Quiescing);
    assert_eq!(history.epochs.recovery, 1); // explicit supported absent-history behavior
    assert_eq!(receipt.manifest.inventory().unwrap().total().unresolved, 3);
    let (again, repeated) = export(&fixture);
    assert_eq!(bytes, again);
    assert_eq!(receipt, repeated);
}

fn add_foreign_namespace(fixture: &Fixture, active: bool) -> NamespaceRecord {
    let schema = SchemaId::from_definition(DEFINITION).unwrap();
    let record = NamespaceRecord::create(
        TenantId("other-tenant".into()),
        StateNamespaceId("business".into()),
        schema.as_str().into(),
        NamespaceQuota::default(),
    )
    .unwrap();
    let record = if active {
        record
    } else {
        record
            .transition(record.version, &NamespaceTransition::Quiesce, 0)
            .unwrap()
    };
    let mut history = NamespaceHistory::initial(&record);
    history.epochs.schema = 4;
    history.epochs.recovery = 7;
    fixture
        .store
        .apply(AtomicBatch {
            expectations: vec![],
            mutations: vec![
                RowMutation {
                    key: RowKey {
                        family: Family::Namespace,
                        key: namespace_record_key(&record.tenant, &record.id).unwrap(),
                    },
                    value: Some(record.encode().unwrap()),
                },
                RowMutation {
                    key: crate::namespace::history::history_key(
                        &record.tenant,
                        &record.id,
                        record.version.incarnation,
                    )
                    .unwrap(),
                    value: Some(history.encode().unwrap()),
                },
            ],
        })
        .unwrap();
    record
}

#[test]
fn full_unit_snapshot_captures_distinct_tenants_with_the_same_namespace_and_exact_history() {
    let fixture = fixture();
    let foreign = add_foreign_namespace(&fixture, false);
    let (bytes, receipt) = export(&fixture);
    assert_eq!(receipt.manifest.metadata.tenant, "tenant");
    assert_eq!(receipt.manifest.namespaces.len(), 2);
    assert_eq!(receipt.manifest.rows, 14);
    let (record, history) = receipt
        .manifest
        .namespaces
        .iter()
        .map(|entry| entry.decode().unwrap())
        .find(|(record, _)| record.tenant == foreign.tenant)
        .unwrap();
    assert_eq!(record, foreign);
    assert_eq!(history.epochs.schema, 4);
    assert_eq!(history.epochs.recovery, 7);
    assert_eq!(
        inspect_snapshot(&mut Cursor::new(&bytes), deadline(), validate_row).unwrap(),
        receipt
    );
    let mut repeated = receipt.manifest.clone();
    repeated.namespaces.push(repeated.namespaces[0].clone());
    assert_eq!(repeated.encode(), Err(StoreError::Conflict));
}

#[test]
fn an_active_foreign_namespace_refuses_the_full_unit_before_any_snapshot_output() {
    let fixture = fixture();
    add_foreign_namespace(&fixture, true);
    let mut bytes = Vec::new();
    assert_eq!(
        export_snapshot(
            &fixture.store,
            fixture.metadata.clone(),
            &mut bytes,
            deadline(),
            |view| closure(view, &fixture.metadata),
            |_| Ok(())
        ),
        Err(SnapshotError::Review(StoreError::Conflict))
    );
    assert!(bytes.is_empty());
    assert!(fixture.store.snapshot().is_ok());
}

#[test]
fn full_unit_manifest_cannot_omit_a_tenant_or_relabel_its_original_history() {
    let fixture = fixture();
    let foreign = add_foreign_namespace(&fixture, false);
    let (bytes, receipt) = export(&fixture);
    let original_manifest_length = receipt.manifest.encode().unwrap().len();
    for omit in [false, true] {
        let mut changed = receipt.manifest.clone();
        let index = changed
            .namespaces
            .iter()
            .position(|entry| entry.decode().unwrap().0.tenant == foreign.tenant)
            .unwrap();
        if omit {
            changed.namespaces.remove(index);
        } else {
            let (_, mut history) = changed.namespaces[index].decode().unwrap();
            history.epochs.recovery += 1;
            changed.namespaces[index].history = history.encode().unwrap();
        }
        // The altered canonical manifest has its own valid checksum. Matching
        // the complete archived namespace roster and NSH bytes still refuses.
        let manifest = changed.encode().unwrap();
        let mut altered = bytes.clone();
        altered.truncate(bytes.len() - original_manifest_length - 32 - 4);
        altered.extend_from_slice(&(manifest.len() as u32).to_le_bytes());
        altered.extend_from_slice(&manifest);
        altered.extend_from_slice(&Sha256::digest(&manifest));
        assert_eq!(
            inspect_snapshot(&mut Cursor::new(altered), deadline(), validate_row),
            Err(StoreError::Corrupt)
        );
    }
}

#[test]
fn snapshot_source_faults_are_distinct_from_review_and_partial_output_refusal() {
    struct Broken {
        remaining: usize,
    }
    impl Write for Broken {
        fn write(&mut self, bytes: &[u8]) -> std::io::Result<usize> {
            if self.remaining == 0 {
                return Err(std::io::Error::other("controlled disk-full output"));
            }
            let amount = bytes.len().min(self.remaining);
            self.remaining -= amount;
            Ok(amount)
        }
        fn flush(&mut self) -> std::io::Result<()> {
            Err(std::io::Error::other("controlled flush uncertainty"))
        }
    }
    let fixture = fixture();
    let mut output = Vec::new();
    assert_eq!(
        export_snapshot(
            &fixture.store,
            fixture.metadata.clone(),
            &mut output,
            deadline(),
            |_| Err(StoreError::Corrupt),
            |_| Ok(())
        ),
        Err(SnapshotError::Source(StoreError::Corrupt))
    );
    assert!(output.is_empty());
    assert_eq!(
        export_snapshot(
            &fixture.store,
            fixture.metadata.clone(),
            &mut output,
            deadline(),
            |view| closure(view, &fixture.metadata),
            |_| Err(StoreError::UnsupportedFormat)
        ),
        Err(SnapshotError::Review(StoreError::UnsupportedFormat))
    );
    assert!(output.is_empty());
    for remaining in [0, MAGIC.len(), 100] {
        assert_eq!(
            export_snapshot(
                &fixture.store,
                fixture.metadata.clone(),
                &mut Broken { remaining },
                deadline(),
                |view| closure(view, &fixture.metadata),
                |_| Ok(())
            ),
            Err(SnapshotError::Output)
        );
    }
    assert!(fixture.store.snapshot().is_ok());
}

#[test]
fn snapshot_manifest_bounds_nested_fields_and_refuses_missing_original_decoders() {
    let fixture = fixture();
    let (_, receipt) = export(&fixture);
    let encoded = receipt.manifest.encode().unwrap();
    for field in ["namespaces", "inventory", "source_store_identity"] {
        let mut value: serde_json::Value = serde_json::from_slice(&encoded).unwrap();
        let sample = value[field].as_array().unwrap()[0].clone();
        value[field] = serde_json::Value::Array(vec![
            sample;
            if field == "source_store_identity" {
                4097
            } else {
                129
            }
        ]);
        let bytes = serde_json::to_vec(&value).unwrap();
        assert_eq!(SnapshotManifest::decode(&bytes), Err(StoreError::Corrupt));
    }
    let mut value: serde_json::Value = serde_json::from_slice(&encoded).unwrap();
    value["metadata"]["operation_id"] = serde_json::Value::String("x".repeat(257));
    assert_eq!(
        SnapshotManifest::decode(&serde_json::to_vec(&value).unwrap()),
        Err(StoreError::Corrupt)
    );
    let mut wrong = receipt.manifest;
    wrong.metadata.decoder_formats.clear();
    assert_eq!(wrong.encode(), Err(StoreError::UnsupportedFormat));
}

#[test]
fn truncated_old_format_changed_identity_and_trailing_streams_never_yield_receipts() {
    let fixture = fixture();
    let (bytes, receipt) = export(&fixture);
    for length in [0, MAGIC.len(), bytes.len() - 1] {
        assert!(
            inspect_snapshot(&mut Cursor::new(&bytes[..length]), deadline(), validate_row).is_err()
        );
    }
    let mut old = bytes.clone();
    old[MAGIC.len() - 1] = 1;
    assert_eq!(
        inspect_snapshot(&mut Cursor::new(old), deadline(), validate_row),
        Err(StoreError::UnsupportedFormat)
    );
    let mut trailing = bytes.clone();
    trailing.push(0);
    assert_eq!(
        inspect_snapshot(&mut Cursor::new(trailing), deadline(), validate_row),
        Err(StoreError::Corrupt)
    );
    let original_manifest_length = receipt.manifest.encode().unwrap().len();
    let mut wrong = receipt.manifest;
    wrong.source_store_identity = StoreIdentity::new("different-root-owner".into())
        .unwrap()
        .encode();
    // Even correctly encoded foreign identity cannot match the archived row.
    let mut altered = bytes;
    let manifest = wrong.encode().unwrap();
    // Different manifest size is rebuilt explicitly, never accepted via padding.
    let start = altered.len() - original_manifest_length - 32 - 4;
    altered.truncate(start);
    altered.extend_from_slice(&(manifest.len() as u32).to_le_bytes());
    altered.extend_from_slice(&manifest);
    altered.extend_from_slice(&Sha256::digest(&manifest));
    assert_eq!(
        inspect_snapshot(&mut Cursor::new(altered), deadline(), validate_row),
        Err(StoreError::Corrupt)
    );
}

#[test]
fn manifest_history_matches_archived_rows_and_only_exact_supported_absence_falls_back() {
    fn replace_manifest(
        mut bytes: Vec<u8>,
        original: &SnapshotManifest,
        changed: &SnapshotManifest,
    ) -> Vec<u8> {
        let start = bytes.len() - original.encode().unwrap().len() - 32 - 4;
        let manifest = changed.encode().unwrap();
        bytes.truncate(start);
        bytes.extend_from_slice(&(manifest.len() as u32).to_le_bytes());
        bytes.extend_from_slice(&manifest);
        bytes.extend_from_slice(&Sha256::digest(&manifest));
        bytes
    }
    let fixture = fixture();
    let (bytes, legacy) = export(&fixture);
    let (record, mut history) = legacy.manifest.namespaces[0].decode().unwrap();
    history.epochs.recovery = 9;
    let mut forged = legacy.manifest.clone();
    forged.namespaces[0].history = history.encode().unwrap();
    assert_eq!(
        inspect_snapshot(
            &mut Cursor::new(replace_manifest(bytes, &legacy.manifest, &forged)),
            deadline(),
            validate_row
        ),
        Err(StoreError::Corrupt)
    );
    history.status = crate::namespace::history::HistoryStatus::ReconciliationRequired;
    fixture
        .store
        .apply(AtomicBatch {
            expectations: vec![],
            mutations: vec![RowMutation {
                key: crate::namespace::history::history_key(
                    &record.tenant,
                    &record.id,
                    record.version.incarnation,
                )
                .unwrap(),
                value: Some(history.encode().unwrap()),
            }],
        })
        .unwrap();
    let (bytes, actual) = export(&fixture);
    assert_eq!(
        inspect_snapshot(&mut Cursor::new(&bytes), deadline(), validate_row).unwrap(),
        actual
    );
    let (_, observed) = actual.manifest.namespaces[0].decode().unwrap();
    assert_eq!(observed, history);
    let mut forged = actual.manifest.clone();
    history.epochs.schema += 1;
    forged.namespaces[0].history = history.encode().unwrap();
    assert_eq!(
        inspect_snapshot(
            &mut Cursor::new(replace_manifest(bytes, &actual.manifest, &forged)),
            deadline(),
            validate_row
        ),
        Err(StoreError::Corrupt)
    );
}
