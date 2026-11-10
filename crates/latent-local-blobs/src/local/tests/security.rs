use super::*;
use std::os::unix::fs::{symlink, PermissionsExt};

fn data_path(owner: &LocalBlobStore, root: &Path) -> std::path::PathBuf {
    let state = owner.inner.state().unwrap();
    root.join("objects")
        .join(state.objects.keys().next().unwrap())
        .join("data")
}

#[test]
fn directory_walk_bounds_callbacks_and_propagates_failure() {
    let root = temporary_root();
    std::fs::write(root.path().join("first"), b"").unwrap();
    std::fs::write(root.path().join("second"), b"").unwrap();
    let directory = super::super::fs::Directory::root(root.path()).unwrap();
    let mut visited = 0;
    assert_eq!(
        directory.visit_names(1, |_| {
            visited += 1;
            Ok(())
        }),
        Err(LocalBlobError::Capacity)
    );
    assert_eq!(visited, 1);
    assert_eq!(
        directory.visit_names(2, |_| Err(LocalBlobError::Unavailable)),
        Err(LocalBlobError::Unavailable)
    );
    assert_eq!(directory.names(2).unwrap().len(), 2);
}

#[test]
fn interrupted_recovery_preserves_the_original_payload_for_a_fresh_open() {
    let parent = temporary_root();
    let root = parent.path().join("root");
    let mut bounds = limits();
    bounds.maximum_object_bytes = 16 * 1024;
    bounds.maximum_stage_bytes = 32 * 1024;
    bounds.maximum_disk_bytes = 128 * 1024;
    bounds.maximum_chunk_bytes = 8192;
    let owner = LocalBlobStore::open(&root, "private", bounds).unwrap();
    let payload = vec![42; 9000];
    let mut writer = owner
        .create(&scope(), "text/plain", Some(payload.len() as u64), &|| {
            Ok(())
        })
        .unwrap();
    writer.write(0, &payload[..8192], &|| Ok(())).unwrap();
    writer.write(8192, &payload[8192..], &|| Ok(())).unwrap();
    let reference = writer.seal(&|| Ok(())).unwrap();
    drop(owner);

    let calls = std::cell::Cell::new(0);
    let checkpoint = || {
        calls.set(calls.get() + 1);
        if calls.get() == 5 {
            Err(LocalBlobError::DeadlineExceeded)
        } else {
            Ok(())
        }
    };
    assert!(matches!(
        LocalBlobStore::open_with_checkpoint(&root, "private", bounds, &checkpoint),
        Err(LocalBlobError::DeadlineExceeded)
    ));
    assert_eq!(calls.get(), 5);
    let reopened = LocalBlobStore::open(&root, "private", bounds).unwrap();
    let reader = reopened
        .open_read(&scope(), &reference, &|| Ok(()))
        .unwrap();
    assert_eq!(read(&reader, 0, 8192).unwrap(), payload[..8192]);
    assert_eq!(read(&reader, 8192, 808).unwrap(), payload[8192..]);
}

#[test]
fn expired_recovery_does_not_create_a_root() {
    let parent = temporary_root();
    let root = parent.path().join("uncreated");
    assert!(matches!(
        LocalBlobStore::open_with_checkpoint(&root, "private", limits(), &|| {
            Err(LocalBlobError::DeadlineExceeded)
        }),
        Err(LocalBlobError::DeadlineExceeded)
    ));
    assert!(!root.exists());
}

#[test]
fn recovery_refuses_oversized_directory_before_reading_object_contents() {
    let root = temporary_root();
    drop(store(root.path()));
    for digit in ['a', 'b'] {
        let directory = root
            .path()
            .join("objects")
            .join(digit.to_string().repeat(64));
        std::fs::create_dir(&directory).unwrap();
        // A content walk would instead reject this unknown entry as corrupt.
        std::fs::write(directory.join("unknown"), b"").unwrap();
    }
    let mut limited = limits();
    limited.maximum_objects = 1;
    assert!(matches!(
        LocalBlobStore::open(root.path(), "private", limited),
        Err(LocalBlobError::Capacity)
    ));
}

#[test]
fn insecure_roots_and_symlink_ancestors_are_rejected() {
    let parent = temporary_root();
    let root = parent.path().join("root");
    std::fs::create_dir(&root).unwrap();
    std::fs::set_permissions(&root, std::fs::Permissions::from_mode(0o755)).unwrap();
    assert!(matches!(
        LocalBlobStore::open(&root, "private", limits()),
        Err(LocalBlobError::PermissionDenied)
    ));
    let link = parent.path().join("link");
    symlink(&root, &link).unwrap();
    assert!(LocalBlobStore::open(&link.join("child"), "private", limits()).is_err());
    assert!(!root.join("child").exists());
}

#[test]
fn corrupted_or_missing_payload_never_becomes_a_successful_read() {
    for mutation in ["contents", "missing", "hardlink", "symlink"] {
        let root = temporary_root();
        let owner = store(root.path());
        let reference = put(&owner, b"data");
        let reader = owner.open_read(&scope(), &reference, &|| Ok(())).unwrap();
        let path = data_path(&owner, root.path());
        match mutation {
            "contents" => std::fs::write(&path, b"evil").unwrap(),
            "missing" => std::fs::remove_file(&path).unwrap(),
            "hardlink" => std::fs::hard_link(&path, root.path().join("alias")).unwrap(),
            "symlink" => {
                std::fs::remove_file(&path).unwrap();
                symlink("/etc/passwd", &path).unwrap();
            }
            _ => unreachable!(),
        }
        assert!(read(&reader, 0, 4).is_err());
        assert!(owner.open_read(&scope(), &reference, &|| Ok(())).is_err());
        drop(reader);
        drop(owner);
        assert!(LocalBlobStore::open(root.path(), "private", limits()).is_err());
    }
}

#[test]
fn unknown_entries_and_replaced_directories_are_preserved() {
    let parent = temporary_root();
    let root = parent.path().join("root");
    let owner = store(&root);
    let writer = owner
        .create(&scope(), "text/plain", Some(0), &|| Ok(()))
        .unwrap();
    drop(writer);
    let stage = root.join("staging/0000000000000001");
    let unrelated = stage.join("unrelated");
    std::fs::write(&unrelated, b"keep me").unwrap();
    assert!(owner.reclaim(1, &|| Ok(())).is_err());
    assert_eq!(std::fs::read(&unrelated).unwrap(), b"keep me");
    assert!(stage.join("data").exists());
    drop(owner);
    assert!(LocalBlobStore::open(&root, "private", limits()).is_err());
    assert_eq!(std::fs::read(&unrelated).unwrap(), b"keep me");
}

#[test]
fn replacement_cannot_redirect_an_open_reader_or_reclamation() {
    let parent = temporary_root();
    let root = parent.path().join("root");
    let owner = store(&root);
    let reference = put(&owner, b"data");
    let reader = owner.open_read(&scope(), &reference, &|| Ok(())).unwrap();
    std::fs::rename(&root, parent.path().join("original")).unwrap();
    let replacement = store(&root);
    let replacement_ref = put(&replacement, b"data");
    assert!(read(&reader, 0, 4).is_err());
    assert!(owner
        .release_reference(&scope(), &reference, &|| Ok(()))
        .is_err());
    assert!(owner.reclaim(1, &|| Ok(())).is_err());
    let reader = replacement
        .open_read(&scope(), &replacement_ref, &|| Ok(()))
        .unwrap();
    assert_eq!(read(&reader, 0, 4).unwrap(), b"data");
}

#[test]
fn namespace_is_owned_and_unknown_root_inventory_is_never_adopted() {
    let root = temporary_root();
    drop(store(root.path()));
    assert!(matches!(
        LocalBlobStore::open(root.path(), "another", limits()),
        Err(LocalBlobError::PermissionDenied)
    ));
    let path = root.path().join("unrelated");
    std::fs::write(&path, b"keep").unwrap();
    assert!(LocalBlobStore::open(root.path(), "private", limits()).is_err());
    assert_eq!(std::fs::read(path).unwrap(), b"keep");
}
