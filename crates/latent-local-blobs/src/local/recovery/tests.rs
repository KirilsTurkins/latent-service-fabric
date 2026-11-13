use super::*;
use crate::{BlobRange, BlobReference};
use latent_core::TenantId;
use std::{os::unix::fs::PermissionsExt, path::PathBuf};

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

fn payload(owner: &LocalBlobStore, tenant: &TenantId, root: &Path) -> (BlobReference, PathBuf) {
    let mut writer = owner
        .create(tenant, "text/plain", Some(4), &|| Ok(()))
        .unwrap();
    writer.write(0, b"data", &|| Ok(())).unwrap();
    let reference = writer.seal(&|| Ok(())).unwrap();
    let record = ReferenceRecord::requested("private", tenant, &reference, 16).unwrap();
    (reference, root.join("objects").join(record.key()))
}

#[test]
fn malformed_release_markers_preserve_all_files_and_refuse_reopen() {
    // Include every partial marker, an unknown version, altered same-length
    // content, trailing garbage and an oversized file. None is release proof.
    let mut malformed: Vec<Vec<u8>> = (0..RELEASE_MARKER.len())
        .map(|length| RELEASE_MARKER[..length].to_vec())
        .collect();
    malformed.extend([
        b"LSF blob reference released v2\n".to_vec(),
        b"LSF blob reference released v0\n".to_vec(),
        [RELEASE_MARKER, b"extra"].concat(),
        vec![b'x'; 65],
    ]);
    for marker in malformed {
        let (root, owner, tenant) = fixture();
        let (reference, directory) = payload(&owner, &tenant, root.path());
        owner
            .release_reference(&tenant, &reference, &|| Ok(()))
            .unwrap();
        let reference_record = std::fs::read(directory.join("REFERENCE.json")).unwrap();
        let stage_record = std::fs::read(directory.join("STAGE.json")).unwrap();
        std::fs::write(directory.join("RELEASED"), &marker).unwrap();

        assert_eq!(
            owner.reclaim(64, &|| Ok(())),
            Err(LocalBlobError::Uncertain)
        );
        let snapshot = owner.snapshot().unwrap();
        assert!(snapshot.poisoned);
        assert_eq!(snapshot.objects, 1);
        assert_eq!(snapshot.resident_disk_bytes, 4);
        assert_eq!(std::fs::read(directory.join("data")).unwrap(), b"data");
        assert_eq!(
            std::fs::read(directory.join("REFERENCE.json")).unwrap(),
            reference_record
        );
        assert_eq!(
            std::fs::read(directory.join("STAGE.json")).unwrap(),
            stage_record
        );
        let limits = owner.limits();
        drop(owner);
        assert!(matches!(
            LocalBlobStore::open(root.path(), "private", limits),
            Err(LocalBlobError::Corrupt)
        ));
        assert_eq!(std::fs::read(directory.join("data")).unwrap(), b"data");
        assert_eq!(std::fs::read(directory.join("RELEASED")).unwrap(), marker);
    }
}

#[test]
fn every_interrupted_release_unlink_boundary_recovers_without_resurrecting_bytes() {
    // Five unlinks include the final empty directory. The two sync points
    // straddle tombstone retirement; failures are reopened, never retried on
    // the quarantined original owner.
    for (operation, skip) in (0..5)
        .map(|skip| ("unlink", skip))
        .chain((0..2).map(|skip| ("sync", skip)))
    {
        let (root, owner, tenant) = fixture();
        let (reference, directory) = payload(&owner, &tenant, root.path());
        owner
            .release_reference(&tenant, &reference, &|| Ok(()))
            .unwrap();
        assert_eq!(
            std::fs::read(directory.join("RELEASED")).unwrap(),
            RELEASE_MARKER
        );
        owner.inner.root.fail_after(operation, skip);
        assert_eq!(
            owner.reclaim(64, &|| Ok(())),
            Err(LocalBlobError::Uncertain)
        );
        assert!(owner.snapshot().unwrap().poisoned);
        let limits = owner.limits();
        drop(owner);

        let reopened = LocalBlobStore::open(root.path(), "private", limits).unwrap();
        let remaining = reopened.snapshot().unwrap().objects;
        assert_eq!(remaining, usize::from(directory.exists()));
        assert_eq!(reopened.snapshot().unwrap().referenced_objects, 0);
        assert!(matches!(
            reopened.open_read(&tenant, &reference, &|| Ok(())),
            Err(LocalBlobError::NotFound)
        ));
        assert_eq!(reopened.reclaim(64, &|| Ok(())).unwrap().objects, remaining);
        assert!(!directory.exists());
        let snapshot = reopened.snapshot().unwrap();
        assert_eq!(snapshot.objects, 0);
        assert_eq!(snapshot.resident_disk_bytes, 0);
        drop(reopened);
        let final_owner = LocalBlobStore::open(root.path(), "private", limits).unwrap();
        assert_eq!(final_owner.snapshot().unwrap().objects, 0);
        assert_eq!(final_owner.reclaim(64, &|| Ok(())).unwrap().objects, 0);
    }
}

#[test]
fn valid_release_marker_does_not_retire_a_physical_reader() {
    let (root, owner, tenant) = fixture();
    let (reference, directory) = payload(&owner, &tenant, root.path());
    let reader = owner.open_read(&tenant, &reference, &|| Ok(())).unwrap();
    owner
        .release_reference(&tenant, &reference, &|| Ok(()))
        .unwrap();
    assert_eq!(owner.reclaim(64, &|| Ok(())).unwrap().objects, 0);
    let mut bytes = [0; 4];
    assert_eq!(
        reader.read(
            &BlobRange {
                offset: 0,
                length: 4,
            },
            &mut bytes,
            &|| Ok(()),
        ),
        Ok(4)
    );
    assert_eq!(&bytes, b"data");
    assert!(directory.exists());
    drop(reader);
    assert_eq!(owner.reclaim(64, &|| Ok(())).unwrap().objects, 1);
    assert!(!directory.exists());
}
