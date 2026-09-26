use super::*;
use std::os::unix::fs::{symlink, PermissionsExt};

fn data_path(owner: &LocalBlobStore, root: &Path) -> std::path::PathBuf {
    let state = owner.inner.state().unwrap();
    root.join("objects")
        .join(state.objects.keys().next().unwrap())
        .join("data")
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
