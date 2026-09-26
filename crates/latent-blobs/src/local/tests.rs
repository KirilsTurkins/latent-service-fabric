use super::*;
use crate::{BlobRange, BlobReference};

fn limits() -> LocalBlobLimits {
    LocalBlobLimits {
        maximum_objects: 4,
        maximum_object_bytes: 16,
        maximum_disk_bytes: 65536,
        maximum_stages: 4,
        maximum_stage_bytes: 32,
        maximum_handles: 4,
        maximum_chunk_bytes: 8,
        ..LocalBlobLimits::default()
    }
}
fn temporary_root() -> tempfile::TempDir {
    use std::os::unix::fs::PermissionsExt;
    tempfile::Builder::new()
        .permissions(std::fs::Permissions::from_mode(0o700))
        .tempdir()
        .unwrap()
}
fn scope() -> TenantId {
    TenantId("alice".into())
}
fn store(path: &Path) -> Arc<LocalBlobStore> {
    LocalBlobStore::open(path, "private", limits()).unwrap()
}
fn put(store: &LocalBlobStore, data: &[u8]) -> BlobReference {
    let mut writer = store
        .create(&scope(), "text/plain", Some(data.len() as u64), &|| Ok(()))
        .unwrap();
    for chunk in data.chunks(8) {
        writer.write(writer.written(), chunk, &|| Ok(())).unwrap();
    }
    writer.seal(&|| Ok(())).unwrap()
}
fn read(reader: &LocalBlobReader, offset: u64, length: u64) -> Result<Vec<u8>> {
    let mut output = vec![0; usize::try_from(length).unwrap()];
    reader.read(&BlobRange { offset, length }, &mut output, &|| Ok(()))?;
    Ok(output)
}

#[test]
fn exact_empty_and_ranged_data_survive_reopen() {
    let root = temporary_root();
    let owner = store(root.path());
    let empty = put(&owner, b"");
    let reference = put(&owner, b"hello world");
    assert_eq!(owner.snapshot().unwrap().reserved_stage_bytes, 0);
    drop(owner);
    let owner = store(root.path());
    let empty = owner.open_read(&scope(), &empty, &|| Ok(())).unwrap();
    assert_eq!(read(&empty, 0, 0).unwrap(), b"");
    let reader = owner.open_read(&scope(), &reference, &|| Ok(())).unwrap();
    assert_eq!(read(&reader, 6, 5).unwrap(), b"world");
    assert_eq!(read(&reader, 11, 0).unwrap(), b"");
    assert_eq!(read(&reader, 12, 0), Err(LocalBlobError::Invalid));
    assert_eq!(read(&reader, u64::MAX, 1), Err(LocalBlobError::Invalid));
    assert_eq!(read(&reader, 0, 9), Err(LocalBlobError::Invalid));
}

#[test]
fn exact_size_and_sequential_writes_reserve_before_staging() {
    let root = temporary_root();
    let owner = store(root.path());
    let mut writer = owner
        .create(&scope(), "text/plain", Some(16), &|| Ok(()))
        .unwrap();
    let other = owner
        .create(&scope(), "text/plain", None, &|| Ok(()))
        .unwrap();
    assert!(matches!(
        owner.create(&scope(), "text/plain", Some(1), &|| Ok(())),
        Err(LocalBlobError::Capacity)
    ));
    assert_eq!(owner.snapshot().unwrap().reserved_stage_bytes, 32);
    assert_eq!(
        writer.write(1, b"x", &|| Ok(())),
        Err(LocalBlobError::Invalid)
    );
    writer.write(0, b"12345678", &|| Ok(())).unwrap();
    assert_eq!(
        writer.write(0, b"x", &|| Ok(())),
        Err(LocalBlobError::Invalid)
    );
    assert_eq!(writer.seal(&|| Ok(())), Err(LocalBlobError::Invalid));
    drop(other);
    assert_eq!(owner.snapshot().unwrap().reserved_stage_bytes, 32);
    assert_eq!(owner.reclaim(1, &|| Ok(())).unwrap().stages, 1);
    assert_eq!(owner.reclaim(1, &|| Ok(())).unwrap().stages, 1);
    assert_eq!(owner.snapshot().unwrap().reserved_stage_bytes, 0);
}

#[test]
fn duplicate_publication_and_tenant_authority_are_independent() {
    let root = temporary_root();
    let owner = store(root.path());
    let first = put(&owner, b"same");
    assert_eq!(put(&owner, b"same"), first);
    assert_eq!(owner.snapshot().unwrap().objects, 1);
    let bob = TenantId("bob".into());
    assert!(matches!(
        owner.open_read(&bob, &first, &|| Ok(())),
        Err(LocalBlobError::PermissionDenied)
    ));
    let mut forged = first.clone();
    forged.tenant = bob.clone();
    assert!(matches!(
        owner.open_read(&bob, &forged, &|| Ok(())),
        Err(LocalBlobError::NotFound)
    ));
    let mut writer = owner
        .create(&bob, "text/plain", Some(4), &|| Ok(()))
        .unwrap();
    writer.write(0, b"same", &|| Ok(())).unwrap();
    let second = writer.seal(&|| Ok(())).unwrap();
    assert_eq!(first.digest, second.digest);
    assert_ne!(first.tenant, second.tenant);
    assert_eq!(owner.snapshot().unwrap().objects, 2);
    assert_eq!(owner.reclaim(4, &|| Ok(())).unwrap().stages, 1);
}

#[test]
fn pinned_released_object_is_not_reclaimed_and_drop_does_no_deletion() {
    let root = temporary_root();
    let owner = store(root.path());
    let reference = put(&owner, b"hello");
    let reader = owner.open_read(&scope(), &reference, &|| Ok(())).unwrap();
    assert!(owner
        .release_reference(&scope(), &reference, &|| Ok(()))
        .unwrap());
    assert!(matches!(
        owner.open_read(&scope(), &reference, &|| Ok(())),
        Err(LocalBlobError::NotFound)
    ));
    assert_eq!(read(&reader, 0, 5).unwrap(), b"hello");
    assert_eq!(owner.reclaim(4, &|| Ok(())).unwrap().objects, 0);
    drop(reader);
    assert_eq!(owner.snapshot().unwrap().resident_disk_bytes, 5);
    drop(owner);
    let owner = store(root.path());
    assert_eq!(owner.snapshot().unwrap().referenced_objects, 0);
    assert_eq!(owner.reclaim(4, &|| Ok(())).unwrap().objects, 1);
    assert_eq!(owner.snapshot().unwrap().resident_disk_bytes, 0);
}

mod capacities;
mod failures;
mod security;
