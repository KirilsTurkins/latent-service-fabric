use super::*;
use crate::local::LocalBlobLimits;
use std::{
    cell::Cell,
    os::unix::fs::PermissionsExt,
    panic::{catch_unwind, AssertUnwindSafe},
};

fn fixture() -> (tempfile::TempDir, Arc<LocalBlobStore>, TenantId) {
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
        ..LocalBlobLimits::default()
    };
    let owner = LocalBlobStore::open(root.path(), "private", limits).unwrap();
    (root, owner, TenantId("alice".into()))
}

#[test]
fn post_write_unwind_cannot_resume_or_publish_and_keeps_the_original_stage_lease() {
    // Empty, complete and partial writes all cross the physical acceptance
    // boundary; none may publish after an unwound completion checkpoint.
    for (bytes, expected_size) in [(b"".as_slice(), 0), (b"data", 4), (b"data", 8)] {
        let (_root, owner, tenant) = fixture();
        let mut writer = owner
            .create(&tenant, "text/plain", Some(expected_size), &|| Ok(()))
            .unwrap();
        let calls = Cell::new(0);
        let result = catch_unwind(AssertUnwindSafe(|| {
            writer.write(0, bytes, &|| {
                calls.set(calls.get() + 1);
                assert_ne!(calls.get(), 2, "injected post-write unwind");
                Ok(())
            })
        }));
        assert!(result.is_err());
        assert_eq!(calls.get(), 2);
        assert_eq!(writer.written(), bytes.len() as u64);
        assert_eq!(
            writer.write(writer.written(), b"", &|| Ok(())),
            Err(LocalBlobError::Closed)
        );
        let snapshot = owner.snapshot().unwrap();
        assert_eq!(snapshot.objects, 0);
        assert_eq!(snapshot.stages, 1);
        assert_eq!(snapshot.reserved_stage_bytes, expected_size);
        assert_eq!(snapshot.handles, 1);
        assert_eq!(snapshot.active_work, 0);
        assert_eq!(owner.reclaim(64, &|| Ok(())).unwrap().stages, 0);
        assert_eq!(writer.seal(&|| Ok(())), Err(LocalBlobError::Closed));
        assert_eq!(owner.snapshot().unwrap().handles, 0);
        assert_eq!(owner.snapshot().unwrap().reserved_stage_bytes, expected_size);
        let reclaimed = owner.reclaim(64, &|| Ok(())).unwrap();
        assert_eq!(reclaimed.stages, 1);
        assert_eq!(reclaimed.released_payload_reservations, expected_size);
        assert_eq!(owner.snapshot().unwrap().reserved_stage_bytes, 0);
        assert_eq!(owner.snapshot().unwrap().objects, 0);
    }
}

#[test]
fn pre_write_unwind_does_not_poison_an_untouched_writer() {
    let (_root, owner, tenant) = fixture();
    let mut writer = owner
        .create(&tenant, "text/plain", Some(4), &|| Ok(()))
        .unwrap();
    let result = catch_unwind(AssertUnwindSafe(|| {
        writer.write(0, b"data", &|| panic!("injected pre-write unwind"))
    }));
    assert!(result.is_err());
    assert_eq!(writer.written(), 0);
    assert_eq!(owner.snapshot().unwrap().active_work, 0);
    assert_eq!(writer.write(0, b"data", &|| Ok(())), Ok(4));
    assert_eq!(writer.seal(&|| Ok(())).unwrap().size_bytes, 4);
    assert_eq!(owner.snapshot().unwrap().objects, 1);
}

#[test]
fn post_write_error_remains_terminal_and_reopen_preserves_only_an_abandoned_stage() {
    let (root, owner, tenant) = fixture();
    let mut writer = owner
        .create(&tenant, "text/plain", Some(8), &|| Ok(()))
        .unwrap();
    let calls = Cell::new(0);
    assert_eq!(
        writer.write(0, b"data", &|| {
            calls.set(calls.get() + 1);
            if calls.get() == 2 {
                Err(LocalBlobError::DeadlineExceeded)
            } else {
                Ok(())
            }
        }),
        Err(LocalBlobError::DeadlineExceeded)
    );
    assert_eq!(
        writer.write(4, b"more", &|| Ok(())),
        Err(LocalBlobError::Closed)
    );
    assert_eq!(owner.reclaim(64, &|| Ok(())).unwrap().stages, 0);
    drop(writer);
    assert_eq!(owner.snapshot().unwrap().reserved_stage_bytes, 8);
    let limits = owner.limits();
    drop(owner);
    let reopened = LocalBlobStore::open(root.path(), "private", limits).unwrap();
    let snapshot = reopened.snapshot().unwrap();
    assert_eq!(snapshot.objects, 0);
    assert_eq!(snapshot.stages, 1);
    assert_eq!(snapshot.reserved_stage_bytes, 4);
    assert_eq!(reopened.reclaim(64, &|| Ok(())).unwrap().stages, 1);
    assert_eq!(reopened.snapshot().unwrap().reserved_stage_bytes, 0);
    let mut fresh = reopened
        .create(&tenant, "text/plain", Some(4), &|| Ok(()))
        .unwrap();
    fresh.write(0, b"next", &|| Ok(())).unwrap();
    assert_eq!(fresh.seal(&|| Ok(())).unwrap().size_bytes, 4);
}
