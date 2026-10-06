use super::*;
use latent_state::{
    embedded::{AtomicBatch, EmbeddedStore, RowMutation, StoreLimits},
    payload_references::{
        physical_owner_count, PayloadOwner, PayloadOwnerKind, PayloadReference,
        PreparedPayloadReferences,
    },
    store_identity::StoreIdentity,
};
fn database(root: &Path, fresh: bool, identity: &str) -> EmbeddedStore {
    let file = std::fs::OpenOptions::new()
        .read(true)
        .write(true)
        .create_new(fresh)
        .open(root.join("payload-state.redb"))
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
    let batch = StoreIdentity::new(identity.into())
        .unwrap()
        .prepare_initialization(&view)
        .unwrap();
    drop(view);
    if let Some(batch) = batch {
        store.apply(batch).unwrap();
    }
    store
}
fn reference(
    pin: &super::super::LocalDurablePin,
    kind: PayloadOwnerKind,
    id: u8,
    provider: &str,
    epoch: u64,
) -> PayloadReference {
    PayloadReference {
        owner: PayloadOwner {
            tenant: scope().0,
            namespace: "business".into(),
            incarnation: 1,
            kind,
            identity: [id; 32],
            generation: 1,
            format: "application-v1".into(),
        },
        payload: pin.identity(provider, epoch).unwrap(),
    }
}
fn update(store: &EmbeddedStore, changes: &[(Option<PayloadReference>, Option<PayloadReference>)]) {
    let view = store.snapshot().unwrap();
    let plan = PreparedPayloadReferences::prepare(&view, changes).unwrap();
    let mut batch = AtomicBatch::default();
    plan.append_to(&mut batch).unwrap();
    drop(view);
    store.apply(batch).unwrap();
}
#[test]
fn response_release_reopen_and_independent_effect_snapshot_owners_keep_actual_bytes() {
    let state_root = temporary_root();
    let blob_root = temporary_root();
    let state = database(state_root.path(), true, "payload-state-a");
    let owner =
        LocalBlobStore::open_durable(blob_root.path(), "private", limits(), &state).unwrap();
    let blob = put(&owner, b"shared");
    let pin = owner
        .capture_durable_reference(&scope(), &blob, &|| Ok(()))
        .unwrap();
    let response = reference(&pin, PayloadOwnerKind::Result, 1, "local-a", 1);
    let effect = reference(&pin, PayloadOwnerKind::Effect, 2, "local-a", 1);
    let snapshot = reference(&pin, PayloadOwnerKind::Snapshot, 3, "local-a", 1);
    assert_eq!(
        owner.release_durable_reference(&scope(), &blob, &state, &|| Ok(())),
        Err(LocalBlobError::Busy)
    );
    update(
        &state,
        &[
            (None, Some(response.clone())),
            (None, Some(effect.clone())),
            (None, Some(snapshot.clone())),
        ],
    );
    drop(pin);
    update(&state, &[(Some(response), None)]);
    assert_eq!(
        owner.release_durable_reference(&scope(), &blob, &state, &|| Ok(())),
        Err(LocalBlobError::Busy)
    );
    drop(owner);
    drop(state);
    let state = database(state_root.path(), false, "payload-state-a");
    // An ordinary Phase 3 opener still recognizes durable retention after reboot.
    let owner = store(blob_root.path());
    assert_eq!(
        owner.release_reference(&scope(), &blob, &|| Ok(())),
        Err(LocalBlobError::Busy)
    );
    let reader = owner.open_read(&scope(), &blob, &|| Ok(())).unwrap();
    assert_eq!(read(&reader, 0, 6).unwrap(), b"shared");
    update(&state, &[(Some(effect), None), (Some(snapshot), None)]);
    assert!(owner
        .release_durable_reference(&scope(), &blob, &state, &|| Ok(()))
        .unwrap());
    assert_eq!(owner.reclaim(4, &|| Ok(())).unwrap().objects, 0);
    assert_eq!(read(&reader, 0, 6).unwrap(), b"shared");
    drop(reader);
    assert_eq!(owner.reclaim(4, &|| Ok(())).unwrap().objects, 1);
    assert_eq!(owner.snapshot().unwrap().resident_disk_bytes, 0);
}
#[test]
fn provider_aliases_and_epochs_share_physical_retention_without_sharing_authority() {
    let state_root = temporary_root();
    let blob_root = temporary_root();
    let state = database(state_root.path(), true, "payload-state-a");
    let owner =
        LocalBlobStore::open_durable(blob_root.path(), "private", limits(), &state).unwrap();
    let blob = put(&owner, b"equal");
    let pin = owner
        .capture_durable_reference(&scope(), &blob, &|| Ok(()))
        .unwrap();
    let first = reference(&pin, PayloadOwnerKind::State, 4, "local-a", 1);
    let second = reference(&pin, PayloadOwnerKind::Effect, 5, "local-b", 9);
    update(
        &state,
        &[(None, Some(first.clone())), (None, Some(second.clone()))],
    );
    assert_eq!(
        physical_owner_count(&state.snapshot().unwrap(), &first.payload).unwrap(),
        Some(2)
    );
    drop(pin);
    update(&state, &[(Some(first), None)]);
    assert_eq!(
        owner.release_durable_reference(&scope(), &blob, &state, &|| Ok(())),
        Err(LocalBlobError::Busy)
    );
    update(&state, &[(Some(second), None)]);
    assert!(owner
        .release_durable_reference(&scope(), &blob, &state, &|| Ok(()))
        .unwrap());
    assert_eq!(owner.reclaim(4, &|| Ok(())).unwrap().objects, 1);
}
#[test]
fn missing_physical_index_or_primary_is_a_visible_failure_and_preserves_native_content() {
    let state_root = temporary_root();
    let blob_root = temporary_root();
    let state = database(state_root.path(), true, "payload-state-a");
    let owner =
        LocalBlobStore::open_durable(blob_root.path(), "private", limits(), &state).unwrap();
    let blob = put(&owner, b"proof");
    let pin = owner
        .capture_durable_reference(&scope(), &blob, &|| Ok(()))
        .unwrap();
    let required = reference(&pin, PayloadOwnerKind::Effect, 6, "local-a", 1);
    update(&state, &[(None, Some(required.clone()))]);
    drop(pin);
    let encoded = required.encode().unwrap();
    for key in [
        required.physical_key().unwrap(),
        required.owner_key().unwrap(),
    ] {
        state
            .apply(AtomicBatch {
                expectations: vec![],
                mutations: vec![RowMutation {
                    key: key.clone(),
                    value: None,
                }],
            })
            .unwrap();
        assert_eq!(
            owner.release_durable_reference(&scope(), &blob, &state, &|| Ok(())),
            Err(LocalBlobError::Corrupt)
        );
        assert_eq!(owner.reclaim(4, &|| Ok(())).unwrap().objects, 0);
        let reader = owner.open_read(&scope(), &blob, &|| Ok(())).unwrap();
        assert_eq!(read(&reader, 0, 5).unwrap(), b"proof");
        drop(reader);
        state
            .apply(AtomicBatch {
                expectations: vec![],
                mutations: vec![RowMutation {
                    key,
                    value: Some(encoded.clone()),
                }],
            })
            .unwrap();
    }
}
#[test]
fn different_store_identity_and_unreviewed_orphan_never_authorize_reclamation() {
    let state_root = temporary_root();
    let other_root = temporary_root();
    let blob_root = temporary_root();
    let state = database(state_root.path(), true, "payload-state-a");
    let other = database(other_root.path(), true, "payload-state-b");
    let owner =
        LocalBlobStore::open_durable(blob_root.path(), "private", limits(), &state).unwrap();
    let blob = put(&owner, b"orphan");
    assert_eq!(
        owner.release_durable_reference(&scope(), &blob, &other, &|| Ok(())),
        Err(LocalBlobError::PermissionDenied)
    );
    // No fabricated zero count: absence requires the later bounded orphan review.
    assert_eq!(
        owner.release_durable_reference(&scope(), &blob, &state, &|| Ok(())),
        Err(LocalBlobError::Corrupt)
    );
    assert_eq!(owner.reclaim(4, &|| Ok(())).unwrap().objects, 0);
    let reader = owner.open_read(&scope(), &blob, &|| Ok(())).unwrap();
    assert_eq!(read(&reader, 0, 6).unwrap(), b"orphan");
}
