use super::*;

#[test]
fn pages_are_tenant_scoped_bounded_and_bound_to_the_original_owner() {
    let root = temporary_root();
    let other_root = temporary_root();
    let owner = store(root.path());
    let other = store(other_root.path());
    let first = put(&owner, b"first");
    let second = put(&owner, b"second");
    let bob = TenantId("bob".into());
    let mut writer = owner
        .create(&bob, "text/plain", Some(3), &|| Ok(()))
        .unwrap();
    writer.write(0, b"bob", &|| Ok(())).unwrap();
    writer.seal(&|| Ok(())).unwrap();
    let mut inventory = LocalReferenceInventory::begin(&owner, &scope()).unwrap();
    assert!(matches!(
        inventory.next_page(&other, 1, &|| Ok(())),
        Err(LocalBlobError::Invalid)
    ));
    assert!(matches!(
        inventory.next_page(&owner, 0, &|| Ok(())),
        Err(LocalBlobError::Invalid)
    ));
    let mut found = Vec::new();
    let mut pages = 0;
    loop {
        let page = inventory.next_page(&owner, 1, &|| Ok(())).unwrap();
        pages += 1;
        assert!(page.references().len() <= 1);
        found.extend(page.references().iter().cloned());
        if page.complete {
            break;
        }
    }
    assert_eq!(pages, 4); // The final empty page proves an exactly full traversal ended.
    assert_eq!(found.len(), 2);
    assert!(found.contains(&first));
    assert!(found.contains(&second));
    assert!(matches!(
        inventory.next_page(&owner, 1, &|| Ok(())),
        Err(LocalBlobError::Invalid)
    ));
}

#[test]
fn publish_release_and_physical_reclamation_invalidate_old_cursors() {
    let root = temporary_root();
    let owner = store(root.path());
    let first = put(&owner, b"first");
    let mut before_publish = LocalReferenceInventory::begin(&owner, &scope()).unwrap();
    let first_page = before_publish.next_page(&owner, 1, &|| Ok(())).unwrap();
    assert!(!first_page.complete);
    assert_eq!(first_page.references(), std::slice::from_ref(&first));
    drop(first_page);
    let second = put(&owner, b"second");
    assert!(matches!(
        before_publish.next_page(&owner, 1, &|| Ok(())),
        Err(LocalBlobError::Busy)
    ));
    let mut before_release = LocalReferenceInventory::begin(&owner, &scope()).unwrap();
    owner
        .release_reference(&scope(), &first, &|| Ok(()))
        .unwrap();
    assert!(matches!(
        before_release.next_page(&owner, 1, &|| Ok(())),
        Err(LocalBlobError::Busy)
    ));
    let mut before_reclaim = LocalReferenceInventory::begin(&owner, &scope()).unwrap();
    assert_eq!(owner.reclaim(1, &|| Ok(())).unwrap().objects, 1);
    assert!(matches!(
        before_reclaim.next_page(&owner, 1, &|| Ok(())),
        Err(LocalBlobError::Busy)
    ));
    let mut fresh = LocalReferenceInventory::begin(&owner, &scope()).unwrap();
    let page = fresh.next_page(&owner, 4, &|| Ok(())).unwrap();
    assert!(page.complete);
    assert_eq!(page.references(), &[second]);
}

#[test]
fn cursor_uses_bounded_work_and_refuses_in_progress_publication() {
    let root = temporary_root();
    let mut bounded = limits();
    bounded.maximum_work = 2;
    let owner = LocalBlobStore::open(root.path(), "private", bounded).unwrap();
    let mut inventory = LocalReferenceInventory::begin(&owner, &scope()).unwrap();
    let page = inventory.next_page(&owner, 1, &|| Ok(())).unwrap();
    assert!(matches!(
        LocalReferenceInventory::begin(&owner, &scope()),
        Err(LocalBlobError::Capacity)
    ));
    drop(inventory);
    assert!(LocalReferenceInventory::begin(&owner, &scope()).is_ok());
    drop(page);
    let publication = owner.inner.publication().unwrap();
    assert!(matches!(
        LocalReferenceInventory::begin(&owner, &scope()),
        Err(LocalBlobError::Busy)
    ));
    drop(publication);
    inventory = LocalReferenceInventory::begin(&owner, &scope()).unwrap();
    let publication = owner.inner.publication().unwrap();
    assert!(matches!(
        inventory.next_page(&owner, 1, &|| Ok(())),
        Err(LocalBlobError::Busy)
    ));
    drop(publication);
    assert!(inventory.next_page(&owner, 1, &|| Ok(())).unwrap().complete);
}

#[test]
fn exhausted_generation_refuses_mutation_without_releasing_the_reference() {
    let root = temporary_root();
    let owner = store(root.path());
    let blob = put(&owner, b"keep");
    owner.inner.state().unwrap().inventory_generation = u64::MAX;
    assert_eq!(
        owner.release_reference(&scope(), &blob, &|| Ok(())),
        Err(LocalBlobError::Capacity)
    );
    let reader = owner.open_read(&scope(), &blob, &|| Ok(())).unwrap();
    assert_eq!(read(&reader, 0, 4).unwrap(), b"keep");
    drop(reader);
    let mut writer = owner
        .create(&scope(), "text/plain", Some(3), &|| Ok(()))
        .unwrap();
    writer.write(0, b"new", &|| Ok(())).unwrap();
    assert!(matches!(
        writer.seal(&|| Ok(())),
        Err(LocalBlobError::Capacity)
    ));
    let mut inventory = LocalReferenceInventory::begin(&owner, &scope()).unwrap();
    let page = inventory.next_page(&owner, 4, &|| Ok(())).unwrap();
    assert_eq!(page.references(), &[blob]);
}

#[test]
fn failed_checkpoint_does_not_advance_the_inventory() {
    let root = temporary_root();
    let owner = store(root.path());
    let blob = put(&owner, b"one");
    let mut inventory = LocalReferenceInventory::begin(&owner, &scope()).unwrap();
    let calls = std::cell::Cell::new(0);
    let checkpoint = || {
        calls.set(calls.get() + 1);
        if calls.get() == 2 {
            Err(LocalBlobError::DeadlineExceeded)
        } else {
            Ok(())
        }
    };
    assert!(matches!(
        inventory.next_page(&owner, 1, &checkpoint),
        Err(LocalBlobError::DeadlineExceeded)
    ));
    let page = inventory.next_page(&owner, 1, &|| Ok(())).unwrap();
    assert!(!page.complete);
    assert_eq!(page.references(), &[blob]);
    drop(page);
    assert!(inventory.next_page(&owner, 1, &|| Ok(())).unwrap().complete);
}

#[test]
fn mutation_during_checkpoint_cannot_publish_a_stale_completed_page() {
    let root = temporary_root();
    let owner = store(root.path());
    put(&owner, b"one");
    let mut inventory = LocalReferenceInventory::begin(&owner, &scope()).unwrap();
    let calls = std::cell::Cell::new(0);
    let checkpoint = || {
        calls.set(calls.get() + 1);
        if calls.get() == 2 {
            put(&owner, b"two");
        }
        Ok(())
    };
    assert!(matches!(
        inventory.next_page(&owner, 4, &checkpoint),
        Err(LocalBlobError::Busy)
    ));
    let mut fresh = LocalReferenceInventory::begin(&owner, &scope()).unwrap();
    let page = fresh.next_page(&owner, 4, &|| Ok(())).unwrap();
    assert!(page.complete);
    assert_eq!(page.references().len(), 2);
}

#[test]
fn duplicate_seal_without_inventory_change_preserves_the_cursor() {
    let root = temporary_root();
    let owner = store(root.path());
    let blob = put(&owner, b"same");
    let mut inventory = LocalReferenceInventory::begin(&owner, &scope()).unwrap();
    assert_eq!(put(&owner, b"same"), blob);
    let page = inventory.next_page(&owner, 4, &|| Ok(())).unwrap();
    assert!(page.complete);
    assert_eq!(page.references(), &[blob]);
}

#[test]
fn owner_close_during_checkpoint_cannot_publish_a_page() {
    let root = temporary_root();
    let owner = store(root.path());
    put(&owner, b"one");
    let mut inventory = LocalReferenceInventory::begin(&owner, &scope()).unwrap();
    let calls = std::cell::Cell::new(0);
    let checkpoint = || {
        calls.set(calls.get() + 1);
        if calls.get() == 2 {
            owner.close();
        }
        Ok(())
    };
    assert!(matches!(
        inventory.next_page(&owner, 4, &checkpoint),
        Err(LocalBlobError::Closed)
    ));
}
