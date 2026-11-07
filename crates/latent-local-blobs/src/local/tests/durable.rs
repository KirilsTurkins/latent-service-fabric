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
    assert_eq!(
        owner.release_durable_reference(&scope(), &blob, &state, &|| Ok(())),
        Err(LocalBlobError::PermissionDenied)
    );
    assert!(matches!(
        owner.capture_durable_reference(&scope(), &blob, &|| Ok(())),
        Err(LocalBlobError::PermissionDenied)
    ));
    drop(reader);
    drop(owner);
    let owner =
        LocalBlobStore::open_durable(blob_root.path(), "private", limits(), &state).unwrap();
    let reader = owner.open_read(&scope(), &blob, &|| Ok(())).unwrap();
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
fn reopening_binds_the_same_unique_durable_owner_without_recreating_its_mode() {
    let state_root = temporary_root();
    let other_root = temporary_root();
    let blob_root = temporary_root();
    let state = database(state_root.path(), true, "payload-state-a");
    let other = database(other_root.path(), true, "payload-state-b");
    let mut ordinary = LocalBlobStore::open(blob_root.path(), "private", limits()).unwrap();
    let view = state.snapshot().unwrap();
    assert!(!LocalBlobStore::bind_existing_durable_for_view(&mut ordinary, &view).unwrap());
    assert!(!blob_root.path().join("DURABLE.json").exists());
    drop(view);
    drop(ordinary);
    let owner =
        LocalBlobStore::open_durable(blob_root.path(), "private", limits(), &state).unwrap();
    let blob = put(&owner, b"retained");
    let original_pin = owner
        .capture_durable_reference(&scope(), &blob, &|| Ok(()))
        .unwrap();
    let required = reference(&original_pin, PayloadOwnerKind::Result, 9, "local", 1);
    update(&state, &[(None, Some(required))]);
    drop(original_pin);
    drop(owner);
    let mut owner = LocalBlobStore::open(blob_root.path(), "private", limits()).unwrap();
    let original = Arc::as_ptr(&owner);
    let view = state.snapshot().unwrap();
    let other_view = other.snapshot().unwrap();
    assert_eq!(
        LocalBlobStore::bind_existing_durable_for_view(&mut owner, &other_view),
        Err(LocalBlobError::PermissionDenied)
    );
    let alias = Arc::clone(&owner);
    assert_eq!(
        LocalBlobStore::bind_existing_durable_for_view(&mut owner, &view),
        Err(LocalBlobError::Busy)
    );
    drop(alias);
    assert!(LocalBlobStore::bind_existing_durable_for_view(&mut owner, &view).unwrap());
    assert_eq!(Arc::as_ptr(&owner), original);
    let mut inventory = RequiredBlobInventory::begin(&owner, &view).unwrap();
    assert_eq!(
        inventory
            .next_page(&owner, &view, 1, 1024, &|| Ok(()))
            .unwrap(),
        (1, true)
    );
    let pin = owner
        .capture_durable_reference(&scope(), &blob, &|| Ok(()))
        .unwrap();
    assert!(pin.uses_store_view(&view));
    assert!(!pin.uses_store_view(&other_view));
    assert_eq!(
        LocalBlobStore::bind_existing_durable_for_view(&mut owner, &view),
        Err(LocalBlobError::Busy)
    );
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
    {
        let view = state.snapshot().unwrap();
        let mut audit = LocalReferenceAudit::begin(&owner, &view, &scope(), &|| Ok(())).unwrap();
        let page = audit.next_page(&owner, &view, 4, &|| Ok(())).unwrap();
        assert_eq!(
            page.entries().collect::<Vec<_>>(),
            vec![(&blob, LocalReferenceDisposition::HasOwners)]
        );
    }
    assert_eq!(
        owner.release_durable_reference(&scope(), &blob, &state, &|| Ok(())),
        Err(LocalBlobError::Busy)
    );
    update(&state, &[(Some(second), None)]);
    {
        let view = state.snapshot().unwrap();
        let mut audit = LocalReferenceAudit::begin(&owner, &view, &scope(), &|| Ok(())).unwrap();
        let page = audit.next_page(&owner, &view, 4, &|| Ok(())).unwrap();
        assert_eq!(
            page.entries().collect::<Vec<_>>(),
            vec![(&blob, LocalReferenceDisposition::ZeroOwners)]
        );
    }
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
        let view = state.snapshot().unwrap();
        let mut audit = LocalReferenceAudit::begin(&owner, &view, &scope(), &|| Ok(())).unwrap();
        assert!(matches!(
            audit.next_page(&owner, &view, 4, &|| Ok(())),
            Err(LocalBlobError::Corrupt)
        ));
        drop(audit);
        drop(view);
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

#[test]
fn bounded_audit_distinguishes_durable_owner_from_unreviewed_reference() {
    let state_root = temporary_root();
    let blob_root = temporary_root();
    let state = database(state_root.path(), true, "audit-state");
    let owner =
        LocalBlobStore::open_durable(blob_root.path(), "private", limits(), &state).unwrap();
    let required = put(&owner, b"required");
    let unreviewed = put(&owner, b"orphan");
    let pin = owner
        .capture_durable_reference(&scope(), &required, &|| Ok(()))
        .unwrap();
    let link = reference(&pin, PayloadOwnerKind::Result, 1, "local-a", 1);
    update(&state, &[(None, Some(link))]);
    drop(pin);
    let view = state.snapshot().unwrap();
    let mut audit = LocalReferenceAudit::begin(&owner, &view, &scope(), &|| Ok(())).unwrap();
    let mut seen = Vec::new();
    loop {
        let page = audit.next_page(&owner, &view, 1, &|| Ok(())).unwrap();
        seen.extend(
            page.entries()
                .map(|(reference, disposition)| (reference.clone(), disposition)),
        );
        if page.complete() {
            break;
        }
    }
    assert_eq!(seen.len(), 2);
    assert!(seen.contains(&(required, LocalReferenceDisposition::HasOwners)));
    assert!(seen.contains(&(unreviewed.clone(), LocalReferenceDisposition::Unreviewed)));
    // An audit observation never grants the privileged deletion operation.
    assert_eq!(
        owner.release_durable_reference(&scope(), &unreviewed, &state, &|| Ok(())),
        Err(LocalBlobError::Corrupt)
    );
    assert_eq!(owner.reclaim(4, &|| Ok(())).unwrap().objects, 0);
}

#[test]
fn audit_rejects_rebound_view_and_local_mutation_after_a_page() {
    let state_root = temporary_root();
    let other_root = temporary_root();
    let blob_root = temporary_root();
    let state = database(state_root.path(), true, "audit-fence");
    let other = database(other_root.path(), true, "audit-other");
    let owner =
        LocalBlobStore::open_durable(blob_root.path(), "private", limits(), &state).unwrap();
    put(&owner, b"one");
    let view = state.snapshot().unwrap();
    let other_view = state.snapshot().unwrap();
    let foreign_view = other.snapshot().unwrap();
    assert!(matches!(
        LocalReferenceAudit::begin(&owner, &foreign_view, &scope(), &|| Ok(())),
        Err(LocalBlobError::PermissionDenied)
    ));
    assert_eq!(owner.inner.work.load(Ordering::Acquire), 0);
    let mut rebound = LocalReferenceAudit::begin(&owner, &view, &scope(), &|| Ok(())).unwrap();
    assert!(matches!(
        rebound.next_page(&owner, &other_view, 1, &|| Ok(())),
        Err(LocalBlobError::Invalid)
    ));
    assert!(matches!(
        rebound.next_page(&owner, &view, 1, &|| Ok(())),
        Err(LocalBlobError::Invalid)
    ));
    drop(rebound);
    let mut audit = LocalReferenceAudit::begin(&owner, &view, &scope(), &|| Ok(())).unwrap();
    let page = audit.next_page(&owner, &view, 1, &|| Ok(())).unwrap();
    assert!(!page.complete());
    drop(page);
    put(&owner, b"two");
    assert!(matches!(
        audit.next_page(&owner, &view, 1, &|| Ok(())),
        Err(LocalBlobError::Busy)
    ));
    assert!(matches!(
        audit.next_page(&owner, &view, 1, &|| Ok(())),
        Err(LocalBlobError::Invalid)
    ));
}

#[test]
fn historical_audit_cannot_authorize_reclamation_after_a_new_owner_commits() {
    let state_root = temporary_root();
    let blob_root = temporary_root();
    let state = database(state_root.path(), true, "audit-history");
    let owner =
        LocalBlobStore::open_durable(blob_root.path(), "private", limits(), &state).unwrap();
    let blob = put(&owner, b"history");
    let pin = owner
        .capture_durable_reference(&scope(), &blob, &|| Ok(()))
        .unwrap();
    let view = state.snapshot().unwrap();
    let mut audit = LocalReferenceAudit::begin(&owner, &view, &scope(), &|| Ok(())).unwrap();
    let link = reference(&pin, PayloadOwnerKind::Effect, 2, "local-a", 1);
    update(&state, &[(None, Some(link))]);
    drop(pin);
    let page = audit.next_page(&owner, &view, 4, &|| Ok(())).unwrap();
    let entries: Vec<_> = page.entries().collect();
    assert_eq!(
        entries,
        vec![(&blob, LocalReferenceDisposition::Unreviewed)]
    );
    drop(entries);
    drop(page);
    drop(audit);
    drop(view);
    assert_eq!(
        owner.release_durable_reference(&scope(), &blob, &state, &|| Ok(())),
        Err(LocalBlobError::Busy)
    );
    let reader = owner.open_read(&scope(), &blob, &|| Ok(())).unwrap();
    assert_eq!(read(&reader, 0, 7).unwrap(), b"history");
}

#[test]
fn audit_fails_closed_when_checkpoint_panics_or_mutates_the_local_inventory() {
    let state_root = temporary_root();
    let blob_root = temporary_root();
    let state = database(state_root.path(), true, "audit-interruption");
    let owner =
        LocalBlobStore::open_durable(blob_root.path(), "private", limits(), &state).unwrap();
    put(&owner, b"one");
    let view = state.snapshot().unwrap();
    let mut panic_audit = LocalReferenceAudit::begin(&owner, &view, &scope(), &|| Ok(())).unwrap();
    let panic = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
        let _ = panic_audit.next_page(&owner, &view, 4, &|| panic!("test interruption"));
    }));
    assert!(panic.is_err());
    assert!(matches!(
        panic_audit.next_page(&owner, &view, 4, &|| Ok(())),
        Err(LocalBlobError::Invalid)
    ));
    drop(panic_audit);
    let mut mutation_audit =
        LocalReferenceAudit::begin(&owner, &view, &scope(), &|| Ok(())).unwrap();
    let calls = std::cell::Cell::new(0);
    let checkpoint = || {
        calls.set(calls.get() + 1);
        if calls.get() == 3 {
            put(&owner, b"two");
        }
        Ok(())
    };
    assert!(matches!(
        mutation_audit.next_page(&owner, &view, 4, &checkpoint),
        Err(LocalBlobError::Busy)
    ));
    assert!(matches!(
        mutation_audit.next_page(&owner, &view, 4, &|| Ok(())),
        Err(LocalBlobError::Invalid)
    ));
}

#[test]
fn audit_reports_zero_owner_head_without_converting_it_to_deletion_authority() {
    let state_root = temporary_root();
    let blob_root = temporary_root();
    let state = database(state_root.path(), true, "audit-zero");
    let owner =
        LocalBlobStore::open_durable(blob_root.path(), "private", limits(), &state).unwrap();
    let blob = put(&owner, b"zero");
    let pin = owner
        .capture_durable_reference(&scope(), &blob, &|| Ok(()))
        .unwrap();
    let link = reference(&pin, PayloadOwnerKind::Result, 3, "local-a", 1);
    update(&state, &[(None, Some(link.clone()))]);
    update(&state, &[(Some(link), None)]);
    // The real provisional pin is still live even though the head is zero.
    let view = state.snapshot().unwrap();
    let mut audit = LocalReferenceAudit::begin(&owner, &view, &scope(), &|| Ok(())).unwrap();
    let page = audit.next_page(&owner, &view, 4, &|| Ok(())).unwrap();
    assert_eq!(
        page.entries().collect::<Vec<_>>(),
        vec![(&blob, LocalReferenceDisposition::ZeroOwners)]
    );
    drop(page);
    drop(audit);
    drop(view);
    assert_eq!(
        owner.release_durable_reference(&scope(), &blob, &state, &|| Ok(())),
        Err(LocalBlobError::Busy)
    );
    drop(pin);
}

#[test]
fn expired_state_view_invalidates_the_audit_without_a_page() {
    let state_root = temporary_root();
    let blob_root = temporary_root();
    let file = std::fs::OpenOptions::new()
        .read(true)
        .write(true)
        .create_new(true)
        .open(state_root.path().join("state.redb"))
        .unwrap();
    let state = EmbeddedStore::open_file(
        file,
        StoreLimits {
            cache_bytes: 1024 * 1024,
            maximum_view_age: std::time::Duration::from_secs(1),
            ..StoreLimits::default()
        },
    )
    .unwrap();
    let init_view = state.snapshot().unwrap();
    let initial = StoreIdentity::new("audit-expiry".into())
        .unwrap()
        .prepare_initialization(&init_view)
        .unwrap()
        .unwrap();
    drop(init_view);
    state.apply(initial).unwrap();
    let owner =
        LocalBlobStore::open_durable(blob_root.path(), "private", limits(), &state).unwrap();
    put(&owner, b"one");
    let view = state.snapshot().unwrap();
    let mut audit = LocalReferenceAudit::begin(&owner, &view, &scope(), &|| Ok(())).unwrap();
    let calls = std::cell::Cell::new(0);
    let checkpoint = || {
        calls.set(calls.get() + 1);
        if calls.get() == 2 {
            std::thread::sleep(std::time::Duration::from_millis(1100));
        }
        Ok(())
    };
    assert!(matches!(
        audit.next_page(&owner, &view, 4, &checkpoint),
        Err(LocalBlobError::Unavailable)
    ));
    assert!(matches!(
        audit.next_page(&owner, &view, 4, &|| Ok(())),
        Err(LocalBlobError::Invalid)
    ));
}

#[test]
fn audit_setup_rechecks_the_original_checkpoint_and_returns_work() {
    let state_root = temporary_root();
    let blob_root = temporary_root();
    let state = database(state_root.path(), true, "audit-setup");
    let owner =
        LocalBlobStore::open_durable(blob_root.path(), "private", limits(), &state).unwrap();
    let view = state.snapshot().unwrap();
    let calls = std::cell::Cell::new(0);
    let expire = || {
        calls.set(calls.get() + 1);
        if calls.get() == 4 {
            Err(LocalBlobError::DeadlineExceeded)
        } else {
            Ok(())
        }
    };
    assert!(matches!(
        LocalReferenceAudit::begin(&owner, &view, &scope(), &expire),
        Err(LocalBlobError::DeadlineExceeded)
    ));
    assert_eq!(owner.inner.work.load(Ordering::Acquire), 0);
    let calls = std::cell::Cell::new(0);
    let mutate = || {
        calls.set(calls.get() + 1);
        if calls.get() == 4 {
            put(&owner, b"new");
        }
        Ok(())
    };
    assert!(matches!(
        LocalReferenceAudit::begin(&owner, &view, &scope(), &mutate),
        Err(LocalBlobError::Busy)
    ));
    assert_eq!(owner.inner.work.load(Ordering::Acquire), 0);
}

#[test]
fn same_label_different_live_engine_cannot_authorize_release() {
    let state_root = temporary_root();
    let other_root = temporary_root();
    let blob_root = temporary_root();
    let state = database(state_root.path(), true, "same-label");
    let other = database(other_root.path(), true, "same-label");
    let owner =
        LocalBlobStore::open_durable(blob_root.path(), "private", limits(), &state).unwrap();
    let blob = put(&owner, b"proof");
    let pin = owner
        .capture_durable_reference(&scope(), &blob, &|| Ok(()))
        .unwrap();
    let reference = reference(&pin, PayloadOwnerKind::Result, 5, "local", 1);
    update(&state, &[(None, Some(reference.clone()))]);
    update(&other, &[(None, Some(reference.clone()))]);
    update(&other, &[(Some(reference), None)]);
    drop(pin);
    assert_eq!(
        owner.release_durable_reference(&scope(), &blob, &other, &|| Ok(())),
        Err(LocalBlobError::PermissionDenied)
    );
    assert_eq!(
        owner.release_durable_reference(&scope(), &blob, &state, &|| Ok(())),
        Err(LocalBlobError::Busy)
    );
    let reader = owner.open_read(&scope(), &blob, &|| Ok(())).unwrap();
    assert_eq!(read(&reader, 0, 5).unwrap(), b"proof");
}

#[test]
fn recovery_checks_actual_required_bytes_and_rejects_foreign_view_or_corruption() {
    let state_root = temporary_root();
    let other_root = temporary_root();
    let blob_root = temporary_root();
    let state = database(state_root.path(), true, "same-label");
    let other = database(other_root.path(), true, "same-label");
    let owner =
        LocalBlobStore::open_durable(blob_root.path(), "private", limits(), &state).unwrap();
    let blob = put(&owner, b"proof");
    let pin = owner
        .capture_durable_reference(&scope(), &blob, &|| Ok(()))
        .unwrap();
    let reference = reference(&pin, PayloadOwnerKind::Effect, 7, "local", 1);
    update(&state, &[(None, Some(reference.clone()))]);
    let key = reference.owner_key().unwrap();
    let bytes = reference.encode().unwrap();
    let view = state.snapshot().unwrap();
    owner
        .verify_required_reference(&view, &key, &bytes, &|| Ok(()))
        .unwrap();
    let foreign = other.snapshot().unwrap();
    assert_eq!(
        owner.verify_required_reference(&foreign, &key, &bytes, &|| Ok(())),
        Err(LocalBlobError::PermissionDenied)
    );
    drop((view, foreign, pin));
    let object = owner
        .inner
        .state()
        .unwrap()
        .objects
        .keys()
        .next()
        .unwrap()
        .clone();
    let path = blob_root.path().join("objects").join(object).join("data");
    std::fs::write(&path, b"wrong").unwrap();
    let view = state.snapshot().unwrap();
    assert_eq!(
        owner.verify_required_reference(&view, &key, &bytes, &|| Ok(())),
        Err(LocalBlobError::Corrupt)
    );
    std::fs::remove_file(path).unwrap();
    assert!(owner
        .verify_required_reference(&view, &key, &bytes, &|| Ok(()))
        .is_err());
}

#[test]
fn bounded_recovery_pages_stay_with_original_view_and_refuse_corruption() {
    let state_root = temporary_root();
    let blob_root = temporary_root();
    let state = database(state_root.path(), true, "payload-state-a");
    let owner =
        LocalBlobStore::open_durable(blob_root.path(), "private", limits(), &state).unwrap();
    let blob = put(&owner, b"proof");
    let pin = owner
        .capture_durable_reference(&scope(), &blob, &|| Ok(()))
        .unwrap();
    let result = reference(&pin, PayloadOwnerKind::Result, 1, "local", 1);
    let effect = reference(&pin, PayloadOwnerKind::Effect, 2, "local", 1);
    update(&state, &[(None, Some(result)), (None, Some(effect))]);
    let view = state.snapshot().unwrap();
    let mut inventory = RequiredBlobInventory::begin(&owner, &view).unwrap();
    assert_eq!(
        inventory
            .next_page(&owner, &view, 1, 1024, &|| Ok(()))
            .unwrap(),
        (1, false)
    );
    let another_view = state.snapshot().unwrap();
    assert_eq!(
        inventory.next_page(&owner, &another_view, 1, 1024, &|| Ok(())),
        Err(LocalBlobError::PermissionDenied)
    );
    drop(another_view);
    let object = owner
        .inner
        .state()
        .unwrap()
        .objects
        .keys()
        .next()
        .unwrap()
        .clone();
    std::fs::write(
        blob_root.path().join("objects").join(object).join("data"),
        b"wrong",
    )
    .unwrap();
    assert_eq!(
        inventory.next_page(&owner, &view, 1, 1024, &|| Ok(())),
        Err(LocalBlobError::Corrupt)
    );
}

#[test]
fn equal_bytes_in_two_tenants_have_independent_physical_custody() {
    let state_root = temporary_root();
    let blob_root = temporary_root();
    let state = database(state_root.path(), true, "payload-state-a");
    let owner =
        LocalBlobStore::open_durable(blob_root.path(), "private", limits(), &state).unwrap();
    let alice = put(&owner, b"equal");
    let bob_scope = TenantId("bob".into());
    let mut writer = owner
        .create(&bob_scope, "text/plain", Some(5), &|| Ok(()))
        .unwrap();
    writer.write(0, b"equal", &|| Ok(())).unwrap();
    let bob = writer.seal(&|| Ok(())).unwrap();
    assert_eq!(alice.digest, bob.digest);
    assert!(matches!(
        owner.open_read(&scope(), &bob, &|| Ok(())),
        Err(LocalBlobError::PermissionDenied)
    ));
    let alice_pin = owner
        .capture_durable_reference(&scope(), &alice, &|| Ok(()))
        .unwrap();
    let bob_pin = owner
        .capture_durable_reference(&bob_scope, &bob, &|| Ok(()))
        .unwrap();
    let alice_ref = reference(&alice_pin, PayloadOwnerKind::Result, 1, "local", 1);
    let mut bob_ref = reference(&bob_pin, PayloadOwnerKind::Effect, 2, "local", 1);
    bob_ref.owner.tenant = bob_scope.0.clone();
    update(
        &state,
        &[
            (None, Some(alice_ref.clone())),
            (None, Some(bob_ref.clone())),
        ],
    );
    drop((alice_pin, bob_pin));
    update(&state, &[(Some(alice_ref), None)]);
    assert!(owner
        .release_durable_reference(&scope(), &alice, &state, &|| Ok(()))
        .unwrap());
    assert_eq!(owner.reclaim(4, &|| Ok(())).unwrap().objects, 1);
    assert_eq!(
        owner.release_durable_reference(&bob_scope, &bob, &state, &|| Ok(())),
        Err(LocalBlobError::Busy)
    );
    let reader = owner.open_read(&bob_scope, &bob, &|| Ok(())).unwrap();
    assert_eq!(read(&reader, 0, 5).unwrap(), b"equal");
}
