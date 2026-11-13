use super::*;
use crate::local::{LocalBlobLimits, OWNER_BYTES};
use std::{
    cell::Cell,
    os::unix::fs::PermissionsExt,
    panic::{catch_unwind, AssertUnwindSafe},
    sync::mpsc::sync_channel,
    time::Duration,
};

const PAGE_BYTES: usize = HANDLE_BYTES + OBJECT_BYTES;

fn fixture(extra_metadata: usize) -> (tempfile::TempDir, Arc<LocalBlobStore>, TenantId) {
    let root = tempfile::Builder::new()
        .permissions(std::fs::Permissions::from_mode(0o700))
        .tempdir()
        .unwrap();
    let limits = LocalBlobLimits {
        maximum_objects: 4,
        maximum_object_bytes: 16,
        maximum_disk_bytes: 65536,
        maximum_stages: 4,
        maximum_stage_bytes: 32,
        maximum_handles: 4,
        maximum_chunk_bytes: 8,
        maximum_metadata_bytes: OWNER_BYTES + extra_metadata,
        ..LocalBlobLimits::default()
    };
    let owner = LocalBlobStore::open(root.path(), "private", limits).unwrap();
    (root, owner, TenantId("alice".into()))
}

fn put(owner: &LocalBlobStore, tenant: &TenantId, bytes: &[u8]) -> BlobReference {
    let mut writer = owner
        .create(tenant, "text/plain", Some(bytes.len() as u64), &|| Ok(()))
        .unwrap();
    writer.write(0, bytes, &|| Ok(())).unwrap();
    writer.seal(&|| Ok(())).unwrap()
}

#[test]
fn retained_pages_remain_charged_independently_of_their_cursor_and_owner_closure() {
    let (_root, owner, tenant) = fixture(2 * OBJECT_BYTES + HANDLE_BYTES + 2 * PAGE_BYTES);
    put(&owner, &tenant, b"one");
    put(&owner, &tenant, b"two");
    let base = owner.snapshot().unwrap().metadata_bytes;
    let mut cursor = LocalReferenceInventory::begin(&owner, &tenant, &|| Ok(())).unwrap();
    assert_eq!(
        owner.snapshot().unwrap().metadata_bytes,
        base + HANDLE_BYTES
    );
    let first = cursor.next_page(&owner, 1, &|| Ok(())).unwrap();
    let second = cursor.next_page(&owner, 1, &|| Ok(())).unwrap();
    assert!(!first.complete && !second.complete);
    let full = owner.snapshot().unwrap();
    assert_eq!(full.metadata_bytes, owner.limits().maximum_metadata_bytes);
    assert!(matches!(
        cursor.next_page(&owner, 1, &|| Ok(())),
        Err(LocalBlobError::Capacity)
    ));
    assert_eq!(owner.snapshot().unwrap(), full);
    drop(first);
    let empty = cursor.next_page(&owner, 1, &|| Ok(())).unwrap();
    assert!(empty.complete && empty.references().is_empty());
    drop(cursor);
    assert_eq!(
        owner.snapshot().unwrap().metadata_bytes,
        base + 2 * PAGE_BYTES
    );
    owner.close();
    assert_eq!(
        owner.snapshot().unwrap().metadata_bytes,
        base + 2 * PAGE_BYTES
    );
    drop(second);
    assert_eq!(owner.snapshot().unwrap().metadata_bytes, base + PAGE_BYTES);
    drop(empty);
    let retired = owner.snapshot().unwrap();
    assert_eq!(retired.metadata_bytes, base);
    assert_eq!(retired.active_work, 0);
}

#[test]
fn page_metadata_competes_with_real_readers_under_the_same_limit() {
    let (_root, owner, tenant) = fixture(OBJECT_BYTES + HANDLE_BYTES + PAGE_BYTES);
    let reference = put(&owner, &tenant, b"data");
    let base = owner.snapshot().unwrap().metadata_bytes;
    let mut cursor = LocalReferenceInventory::begin(&owner, &tenant, &|| Ok(())).unwrap();
    let page = cursor.next_page(&owner, 1, &|| Ok(())).unwrap();
    assert_eq!(page.references(), std::slice::from_ref(&reference));
    assert!(matches!(
        owner.open_read(&tenant, &reference, &|| Ok(())),
        Err(LocalBlobError::Capacity)
    ));
    assert_eq!(owner.snapshot().unwrap().handles, 0);
    drop(cursor);
    let reader = owner.open_read(&tenant, &reference, &|| Ok(())).unwrap();
    assert_eq!(
        owner.snapshot().unwrap().metadata_bytes,
        base + PAGE_BYTES + HANDLE_BYTES
    );
    drop(reader);
    assert_eq!(owner.snapshot().unwrap().metadata_bytes, base + PAGE_BYTES);
    drop(page);
    assert_eq!(owner.snapshot().unwrap().metadata_bytes, base);
}

#[test]
fn a_smaller_page_can_resume_after_metadata_refusal_without_skipping_references() {
    let (_root, owner, tenant) = fixture(OBJECT_BYTES + HANDLE_BYTES + PAGE_BYTES);
    let reference = put(&owner, &tenant, b"data");
    let mut cursor = LocalReferenceInventory::begin(&owner, &tenant, &|| Ok(())).unwrap();
    let before = owner.snapshot().unwrap();
    assert!(matches!(
        cursor.next_page(&owner, 64, &|| Ok(())),
        Err(LocalBlobError::Capacity)
    ));
    assert_eq!(owner.snapshot().unwrap(), before);
    let page = cursor.next_page(&owner, 1, &|| Ok(())).unwrap();
    assert_eq!(page.references(), &[reference]);
    assert!(!page.complete);
}

#[test]
fn failed_or_unwound_page_construction_refunds_only_its_own_reservation() {
    for unwind in [false, true] {
        let (_root, owner, tenant) = fixture(OBJECT_BYTES + HANDLE_BYTES + PAGE_BYTES);
        let reference = put(&owner, &tenant, b"data");
        let mut cursor = LocalReferenceInventory::begin(&owner, &tenant, &|| Ok(())).unwrap();
        let before = owner.snapshot().unwrap();
        let calls = Cell::new(0);
        let result = catch_unwind(AssertUnwindSafe(|| {
            cursor.next_page(&owner, 1, &|| {
                calls.set(calls.get() + 1);
                if calls.get() == 2 {
                    assert!(!unwind, "injected page completion unwind");
                    return Err(LocalBlobError::DeadlineExceeded);
                }
                Ok(())
            })
        }));
        assert_eq!(calls.get(), 2);
        if unwind {
            assert!(result.is_err());
        } else {
            assert!(matches!(
                result.unwrap(),
                Err(LocalBlobError::DeadlineExceeded)
            ));
        }
        assert_eq!(owner.snapshot().unwrap(), before);
        assert!(cursor.after.is_none() && !cursor.complete);
        let page = cursor.next_page(&owner, 1, &|| Ok(())).unwrap();
        assert_eq!(page.references(), &[reference]);
    }
}

#[test]
fn cursor_admission_refuses_unusable_metadata_and_refunds_failed_checkpoints() {
    let (_root, owner, tenant) = fixture(HANDLE_BYTES + PAGE_BYTES - 1);
    let before = owner.snapshot().unwrap();
    assert!(matches!(
        LocalReferenceInventory::begin(&owner, &tenant, &|| Ok(())),
        Err(LocalBlobError::Capacity)
    ));
    assert_eq!(owner.snapshot().unwrap(), before);

    let (_root, owner, tenant) = fixture(HANDLE_BYTES + PAGE_BYTES);
    let before = owner.snapshot().unwrap();
    for unwind in [false, true] {
        let calls = Cell::new(0);
        let result = catch_unwind(AssertUnwindSafe(|| {
            LocalReferenceInventory::begin(&owner, &tenant, &|| {
                calls.set(calls.get() + 1);
                if calls.get() == 2 {
                    assert!(!unwind, "injected cursor admission unwind");
                    return Err(LocalBlobError::Cancelled);
                }
                Ok(())
            })
        }));
        if unwind {
            assert!(result.is_err());
        } else {
            assert!(matches!(result.unwrap(), Err(LocalBlobError::Cancelled)));
        }
        assert_eq!(calls.get(), 2);
        assert_eq!(owner.snapshot().unwrap(), before);
    }
}

#[test]
fn a_paused_page_cannot_lend_its_metadata_to_a_concurrent_inventory() {
    let (_root, owner, tenant) = fixture(2 * HANDLE_BYTES + PAGE_BYTES);
    let mut first = LocalReferenceInventory::begin(&owner, &tenant, &|| Ok(())).unwrap();
    let mut second = LocalReferenceInventory::begin(&owner, &tenant, &|| Ok(())).unwrap();
    let (paused, observed) = sync_channel(0);
    let (resume, resumed) = sync_channel(0);
    std::thread::scope(|threads| {
        let store = &owner;
        let worker = threads.spawn(move || {
            let calls = Cell::new(0);
            let page = first.next_page(store, 1, &|| {
                calls.set(calls.get() + 1);
                if calls.get() == 2 {
                    paused.send(()).unwrap();
                    resumed.recv_timeout(Duration::from_secs(5)).unwrap();
                }
                Ok(())
            });
            (first, page)
        });
        observed.recv_timeout(Duration::from_secs(5)).unwrap();
        let before = owner.snapshot().unwrap();
        let refused = second.next_page(&owner, 1, &|| Ok(()));
        let after = owner.snapshot().unwrap();
        resume.send(()).unwrap();
        let (first, page) = worker.join().unwrap();
        let page = page.unwrap();
        assert_eq!(before.metadata_bytes, owner.limits().maximum_metadata_bytes);
        assert!(matches!(refused, Err(LocalBlobError::Capacity)));
        assert_eq!(before, after);
        assert_eq!(
            owner.snapshot().unwrap().metadata_bytes,
            before.metadata_bytes
        );
        drop(page);
        let next = second.next_page(&owner, 1, &|| Ok(())).unwrap();
        assert!(next.complete);
        drop(first);
        drop(next);
    });
    drop(second);
    let retired = owner.snapshot().unwrap();
    assert_eq!(retired.metadata_bytes, OWNER_BYTES);
    assert_eq!(retired.active_work, 0);
}

#[test]
fn retained_audit_page_keeps_its_charge_after_the_audit_and_view_retire() {
    use crate::local::{LocalReferenceAudit, LocalReferenceDisposition};
    use latent_state::{
        embedded::{EmbeddedStore, StoreLimits},
        store_identity::StoreIdentity,
    };

    let (_root, mut owner, tenant) =
        fixture(OBJECT_BYTES + HANDLE_BYTES + PAGE_BYTES + 4 * crate::local::RECORD_BYTES);
    let reference = put(&owner, &tenant, b"data");
    let state_root = tempfile::tempdir().unwrap();
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
            ..StoreLimits::default()
        },
    )
    .unwrap();
    let view = state.snapshot().unwrap();
    let initialization = StoreIdentity::new("inventory-metadata".into())
        .unwrap()
        .prepare_initialization(&view)
        .unwrap()
        .unwrap();
    drop(view);
    state.apply(initialization).unwrap();
    let view = state.snapshot().unwrap();
    LocalBlobStore::enable_durable_for_view(&mut owner, &view).unwrap();
    let base = owner.snapshot().unwrap().metadata_bytes;
    let mut audit = LocalReferenceAudit::begin(&owner, &view, &tenant, &|| Ok(())).unwrap();
    let saw_charged_scratch = Cell::new(false);
    let page = audit
        .next_page(&owner, &view, 1, &|| {
            if owner.snapshot().unwrap().active_work == 2 {
                saw_charged_scratch.set(true);
                assert_eq!(
                    owner.snapshot().unwrap().metadata_bytes,
                    base + HANDLE_BYTES + PAGE_BYTES + 4 * crate::local::RECORD_BYTES
                );
            }
            Ok(())
        })
        .unwrap();
    assert!(saw_charged_scratch.get());
    assert_eq!(
        owner.snapshot().unwrap().metadata_bytes,
        base + HANDLE_BYTES + PAGE_BYTES
    );
    assert_eq!(
        page.entries().collect::<Vec<_>>(),
        vec![(&reference, LocalReferenceDisposition::Unreviewed)]
    );
    drop(audit);
    drop(view);
    assert_eq!(owner.snapshot().unwrap().metadata_bytes, base + PAGE_BYTES);
    drop(page);
    assert_eq!(owner.snapshot().unwrap().metadata_bytes, base);
    assert_eq!(owner.snapshot().unwrap().active_work, 0);
}
