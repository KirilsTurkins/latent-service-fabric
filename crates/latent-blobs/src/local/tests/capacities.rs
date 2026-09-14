use super::*;

#[test]
fn object_disk_handle_and_metadata_ceilings_are_independent() {
    for dimension in ["object", "disk", "handle", "metadata"] {
        let root = temporary_root();
        let mut limits = limits();
        match dimension {
            "object" => limits.maximum_objects = 1,
            "disk" => {
                limits.maximum_disk_bytes = DISK_ROOT_BYTES + DISK_ENTRY_BYTES + 16;
                limits.maximum_stage_bytes = 16;
            }
            "handle" => limits.maximum_handles = 1,
            "metadata" => limits.maximum_metadata_bytes = OWNER_BYTES + STAGE_BYTES + HANDLE_BYTES,
            _ => unreachable!(),
        }
        let owner = LocalBlobStore::open(root.path(), "private", limits).unwrap();
        if dimension == "metadata" {
            let writer = owner
                .create(&scope(), "text/plain", Some(0), &|| Ok(()))
                .unwrap();
            assert_eq!(
                owner.snapshot().unwrap().metadata_bytes,
                limits.maximum_metadata_bytes
            );
            assert!(matches!(
                owner.create(&scope(), "text/plain", Some(0), &|| Ok(())),
                Err(LocalBlobError::Capacity)
            ));
            assert_eq!(writer.seal(&|| Ok(())), Err(LocalBlobError::Capacity));
        } else if dimension == "handle" {
            let writer = owner
                .create(&scope(), "text/plain", Some(0), &|| Ok(()))
                .unwrap();
            assert!(matches!(
                owner.create(&scope(), "text/plain", Some(0), &|| Ok(())),
                Err(LocalBlobError::Capacity)
            ));
            drop(writer);
            assert_eq!(owner.snapshot().unwrap().handles, 0);
        } else {
            let _first = put(&owner, b"0123456789abcdef");
            if dimension == "disk" {
                assert!(matches!(
                    owner.create(&scope(), "text/plain", Some(1), &|| Ok(())),
                    Err(LocalBlobError::Capacity)
                ));
            } else {
                let mut writer = owner
                    .create(&scope(), "text/plain", Some(1), &|| Ok(()))
                    .unwrap();
                writer.write(0, b"x", &|| Ok(())).unwrap();
                assert_eq!(writer.seal(&|| Ok(())), Err(LocalBlobError::Capacity));
            }
        }
        assert_eq!(owner.snapshot().unwrap().active_work, 0);
    }
}

#[test]
fn stage_and_work_saturation_reject_without_hidden_queues() {
    let root = temporary_root();
    let mut limits = limits();
    limits.maximum_stages = 1;
    limits.maximum_work = 1;
    let owner = LocalBlobStore::open(root.path(), "private", limits).unwrap();
    let work = owner.inner.work().unwrap();
    assert!(matches!(
        owner.create(&scope(), "text/plain", Some(0), &|| Ok(())),
        Err(LocalBlobError::Capacity)
    ));
    drop(work);
    let writer = owner
        .create(&scope(), "text/plain", Some(0), &|| Ok(()))
        .unwrap();
    assert!(matches!(
        owner.create(&scope(), "text/plain", Some(0), &|| Ok(())),
        Err(LocalBlobError::Capacity)
    ));
    assert_eq!(owner.reclaim(1, &|| Ok(())).unwrap().stages, 0);
    drop(writer);
    assert_eq!(owner.reclaim(1, &|| Ok(())).unwrap().stages, 1);
}

#[test]
fn empty_objects_cannot_bypass_disk_sidecar_reservations() {
    let root = temporary_root();
    let mut limits = limits();
    limits.maximum_disk_bytes = DISK_ROOT_BYTES + DISK_ENTRY_BYTES + 16;
    let owner = LocalBlobStore::open(root.path(), "private", limits).unwrap();
    put(&owner, b"");
    assert_eq!(
        owner.snapshot().unwrap().accounted_disk_bytes,
        DISK_ROOT_BYTES + DISK_ENTRY_BYTES
    );
    assert!(matches!(
        owner.create(&scope(), "other", Some(0), &|| Ok(())),
        Err(LocalBlobError::Capacity)
    ));
}
