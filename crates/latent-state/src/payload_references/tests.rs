use super::*;
use crate::embedded::{EmbeddedStore, FencedStoreError, StoreLimits};
fn store(root: &std::path::Path, fresh: bool) -> EmbeddedStore {
    let file = std::fs::OpenOptions::new()
        .read(true)
        .write(true)
        .create_new(fresh)
        .open(root.join("payload-references.redb"))
        .unwrap();
    EmbeddedStore::open_file(
        file,
        StoreLimits {
            cache_bytes: 1024 * 1024,
            ..StoreLimits::default()
        },
    )
    .unwrap()
}
fn reference(kind: PayloadOwnerKind, identity: u8) -> PayloadReference {
    PayloadReference {
        owner: PayloadOwner {
            tenant: "tenant-a".into(),
            namespace: "business".into(),
            incarnation: 1,
            kind,
            identity: [identity; 32],
            generation: 1,
            format: "application-v1".into(),
        },
        payload: LocalPayloadIdentity {
            tenant: "tenant-a".into(),
            provider: "local-payloads".into(),
            provider_epoch: 1,
            provider_configuration: [3; 32],
            blob_namespace: "owned".into(),
            digest: [4; 32],
            size: 64,
            media_type: "application/octet-stream".into(),
        },
    }
}
fn update(
    store: &EmbeddedStore,
    before: Option<PayloadReference>,
    after: Option<PayloadReference>,
) {
    let view = store.snapshot().unwrap();
    let plan = PreparedPayloadReferences::prepare(&view, &[(before, after)]).unwrap();
    let mut batch = AtomicBatch::default();
    plan.append_to(&mut batch).unwrap();
    drop(view);
    store.apply(batch).unwrap();
}
#[test]
fn result_expiry_preserves_effect_and_snapshot_owners_across_reopen() {
    let root = tempfile::tempdir().unwrap();
    let database = store(root.path(), true);
    let result = reference(PayloadOwnerKind::Result, 1);
    let effect = reference(PayloadOwnerKind::Effect, 2);
    let snapshot = reference(PayloadOwnerKind::Snapshot, 3);
    for owner in [&result, &effect, &snapshot] {
        update(&database, None, Some(owner.clone()));
    }
    update(&database, Some(result.clone()), None);
    let view = database.snapshot().unwrap();
    let page = required_page(&view, &effect.payload, None, 1, MAX_REFERENCE_BYTES).unwrap();
    assert_eq!(page.references.len(), 1);
    assert!(page.resume.is_some());
    let next = required_page(
        &view,
        &effect.payload,
        page.resume.as_deref(),
        1,
        MAX_REFERENCE_BYTES,
    )
    .unwrap();
    assert_eq!(next.references.len(), 1);
    assert!(next.resume.is_none());
    assert!(view.get(&result.owner_key().unwrap()).unwrap().is_none());
    drop(view);
    drop(database);
    let database = store(root.path(), false);
    let view = database.snapshot().unwrap();
    let retained = required_page(&view, &effect.payload, None, 4, 4 * MAX_REFERENCE_BYTES).unwrap();
    assert_eq!(retained.references.len(), 2);
    assert!(retained.references.contains(&effect) && retained.references.contains(&snapshot));
    for reference in retained.references {
        validate_row(
            &view,
            &reference.owner_key().unwrap(),
            &reference.encode().unwrap(),
        )
        .unwrap();
        validate_row(
            &view,
            &reference.object_key().unwrap(),
            &reference.encode().unwrap(),
        )
        .unwrap();
    }
    drop(view);
    update(&database, Some(effect.clone()), None);
    update(&database, Some(snapshot), None);
    assert!(required_page(
        &database.snapshot().unwrap(),
        &effect.payload,
        None,
        1,
        MAX_REFERENCE_BYTES
    )
    .unwrap()
    .references
    .is_empty());
}
#[test]
fn atomic_failure_cannot_publish_a_partial_reference_index_or_business_row() {
    let root = tempfile::tempdir().unwrap();
    let database = store(root.path(), true);
    let owner = reference(PayloadOwnerKind::State, 7);
    let view = database.snapshot().unwrap();
    let plan = PreparedPayloadReferences::prepare(&view, &[(None, Some(owner.clone()))]).unwrap();
    assert_eq!(plan.live_payload_bytes_delta(), 64);
    assert!(plan.encoded_metadata_bytes() > 64);
    let mut batch = AtomicBatch::default();
    plan.append_to(&mut batch).unwrap();
    let business = RowKey {
        family: Family::State,
        key: b"same-envelope".to_vec(),
    };
    batch.expectations.push(ExpectedRow {
        key: business.clone(),
        value: None,
    });
    batch.mutations.push(RowMutation {
        key: business.clone(),
        value: Some(b"committed".to_vec()),
    });
    drop(view);
    assert!(matches!(
        database.apply_fenced(batch, || Err::<(), _>("original authority revoked")),
        Err(FencedStoreError::Fence(_))
    ));
    let view = database.snapshot().unwrap();
    assert!(view.get(&business).unwrap().is_none());
    assert!(view.get(&owner.owner_key().unwrap()).unwrap().is_none());
    assert!(view.get(&owner.object_key().unwrap()).unwrap().is_none());
}
#[test]
fn cross_tenant_identity_and_foreign_provider_epoch_never_share_an_owner_index() {
    let root = tempfile::tempdir().unwrap();
    let database = store(root.path(), true);
    let owner = reference(PayloadOwnerKind::Effect, 4);
    update(&database, None, Some(owner.clone()));
    let mut other = owner.clone();
    other.owner.tenant = "tenant-b".into();
    assert_eq!(other.validate(), Err(StoreError::Invalid));
    other.payload.tenant = "tenant-b".into();
    update(&database, None, Some(other.clone()));
    let view = database.snapshot().unwrap();
    assert_eq!(
        required_page(&view, &owner.payload, None, 2, 2 * MAX_REFERENCE_BYTES)
            .unwrap()
            .references,
        vec![owner.clone()]
    );
    assert_eq!(
        required_page(&view, &other.payload, None, 2, 2 * MAX_REFERENCE_BYTES)
            .unwrap()
            .references,
        vec![other]
    );
    let mut rotated = owner.payload;
    rotated.provider_epoch = 2;
    assert!(required_page(&view, &rotated, None, 1, MAX_REFERENCE_BYTES)
        .unwrap()
        .references
        .is_empty());
}
#[test]
fn corrupt_or_missing_primary_is_a_recovery_error_and_never_a_reclamation_grant() {
    let root = tempfile::tempdir().unwrap();
    let database = store(root.path(), true);
    let owner = reference(PayloadOwnerKind::Snapshot, 8);
    update(&database, None, Some(owner.clone()));
    database
        .apply(AtomicBatch {
            expectations: vec![],
            mutations: vec![RowMutation {
                key: owner.owner_key().unwrap(),
                value: None,
            }],
        })
        .unwrap();
    assert!(matches!(
        required_page(
            &database.snapshot().unwrap(),
            &owner.payload,
            None,
            1,
            MAX_REFERENCE_BYTES
        ),
        Err(StoreError::Corrupt)
    ));
    let exact = owner.encode().unwrap();
    for length in 0..exact.len() {
        assert!(PayloadReference::decode(&exact[..length]).is_err());
    }
    let mut unknown = exact.clone();
    unknown[4] = 2;
    assert_eq!(
        PayloadReference::decode(&unknown),
        Err(StoreError::UnsupportedFormat)
    );
    let mut trailing = exact;
    trailing.push(0);
    assert!(PayloadReference::decode(&trailing).is_err());
    let oversized = vec![0; MAX_REFERENCE_BYTES + 1];
    database
        .apply(AtomicBatch {
            expectations: vec![],
            mutations: vec![RowMutation {
                key: owner.owner_key().unwrap(),
                value: Some(oversized.clone()),
            }],
        })
        .unwrap();
    let view = database.snapshot().unwrap();
    assert_eq!(
        view.get_bounded(&owner.owner_key().unwrap(), MAX_REFERENCE_BYTES),
        Err(StoreError::Corrupt)
    );
    assert_eq!(
        view.get(&owner.owner_key().unwrap()).unwrap(),
        Some(oversized)
    );
    assert!(matches!(
        required_page(&view, &owner.payload, None, 1, MAX_REFERENCE_BYTES),
        Err(StoreError::Capacity)
    ));
}
#[test]
fn original_generation_cas_and_bounded_pages_preserve_independent_ownership() {
    let root = tempfile::tempdir().unwrap();
    let database = store(root.path(), true);
    let first = reference(PayloadOwnerKind::State, 9);
    update(&database, None, Some(first.clone()));
    let view = database.snapshot().unwrap();
    let mut forged = first.clone();
    forged.owner.generation = 2;
    assert!(matches!(
        PreparedPayloadReferences::prepare(&view, &[(Some(first.clone()), Some(forged))]),
        Err(StoreError::Conflict)
    ));
    let duplicate = vec![(Some(first.clone()), None), (Some(first.clone()), None)];
    assert!(matches!(
        PreparedPayloadReferences::prepare(&view, &duplicate),
        Err(StoreError::Conflict)
    ));
    assert!(required_page(
        &view,
        &first.payload,
        None,
        MAX_REFERENCE_UPDATES + 1,
        MAX_REFERENCE_BYTES
    )
    .is_err());
    assert!(required_page(
        &view,
        &first.payload,
        None,
        1,
        MAX_REFERENCE_UPDATES * MAX_REFERENCE_BYTES + 1
    )
    .is_err());
    assert_eq!(
        required_page(&view, &first.payload, None, 1, MAX_REFERENCE_BYTES)
            .unwrap()
            .references,
        vec![first]
    );
}
