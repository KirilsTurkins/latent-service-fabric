use super::*;
use std::{
    fs,
    os::unix::fs::{symlink, PermissionsExt},
};

fn root() -> tempfile::TempDir {
    let root = tempfile::TempDir::new().unwrap();
    fs::set_permissions(root.path(), fs::Permissions::from_mode(0o700)).unwrap();
    root
}
fn secret(path: &Path, value: &[u8]) {
    fs::write(path, value).unwrap();
    fs::set_permissions(path, fs::Permissions::from_mode(0o600)).unwrap();
}
#[test]
fn rooted_reads_reject_unbounded_names_types_links_and_sizes() {
    let dir = root();
    let root = ProtectedRoot::open(dir.path()).unwrap();
    let path = dir.path().join("value");
    secret(&path, b"synthetic-value");
    assert_eq!(&*root.read("value", 15).unwrap(), b"synthetic-value");
    for name in ["", ".", "..", "../value", "/value", "dir/value"] {
        assert!(root.read(name, 32).is_err());
    }
    assert!(root.read("value", 0).is_err());
    assert!(root.read("value", 3).is_err());
    assert!(root.read("value", 1024 * 1024 + 1).is_err());
    symlink(&path, dir.path().join("alias")).unwrap();
    assert!(root.read("alias", 32).is_err());
    fs::hard_link(&path, dir.path().join("hard")).unwrap();
    assert!(root.read("value", 32).is_err());
    fs::remove_file(dir.path().join("hard")).unwrap();
    fs::set_permissions(&path, fs::Permissions::from_mode(0o000)).unwrap();
    assert!(root.read("value", 32).is_err());
    fs::create_dir(dir.path().join("directory")).unwrap();
    assert!(root.read("directory", 32).is_err());
    rustix::fs::mkfifoat(
        rustix::fs::CWD,
        dir.path().join("fifo"),
        Mode::RUSR | Mode::WUSR,
    )
    .unwrap();
    assert!(root.read("fifo", 32).is_err());
}
#[test]
fn replacement_and_removal_during_read_never_return_old_bytes() {
    let dir = root();
    let root = ProtectedRoot::open(dir.path()).unwrap();
    let path = dir.path().join("value");
    secret(&path, b"before");
    let result = root.read_with_checkpoint("value", 32, || {
        fs::rename(&path, dir.path().join("archived")).unwrap();
        secret(&path, b"after");
    });
    assert!(result.is_err());
    assert_eq!(&*root.read("value", 32).unwrap(), b"after");
    assert!(root
        .read_with_checkpoint("value", 32, || fs::remove_file(&path).unwrap())
        .is_err());
}
#[test]
fn retained_root_rejects_ancestor_replacement_and_permission_changes() {
    let dir = root();
    let parent = dir.path().join("parent");
    let nested = parent.join("private");
    fs::create_dir(&parent).unwrap();
    fs::create_dir(&nested).unwrap();
    fs::set_permissions(&nested, fs::Permissions::from_mode(0o700)).unwrap();
    secret(&nested.join("value"), b"synthetic");
    let root = ProtectedRoot::open(&nested).unwrap();
    fs::rename(&parent, dir.path().join("moved")).unwrap();
    fs::create_dir(&parent).unwrap();
    assert!(root.read("value", 32).is_err());
    let path = dir.path().join("moved/private");
    let root = ProtectedRoot::open(&path).unwrap();
    fs::set_permissions(path, fs::Permissions::from_mode(0o755)).unwrap();
    assert!(root.read("value", 32).is_err());
}
#[test]
fn content_or_permission_change_after_open_is_rejected() {
    let dir = root();
    let root = ProtectedRoot::open(dir.path()).unwrap();
    let path = dir.path().join("value");
    secret(&path, b"before");
    assert!(root
        .read_with_checkpoint("value", 32, || secret(&path, b"different"))
        .is_err());
    assert!(root
        .read_with_checkpoint("value", 32, || {
            fs::set_permissions(&path, fs::Permissions::from_mode(0o640)).unwrap();
        })
        .is_err());
}

#[test]
fn mutable_engine_file_creation_and_reopen_never_truncate_existing_bytes() {
    use std::io::{Read, Seek, Write};
    let dir = root();
    let root = ProtectedRoot::open(dir.path()).unwrap();
    let (mut file, fence) = root.open_mutable_file("state.redb", 4096, true).unwrap();
    assert!(fence.was_created());
    file.write_all(b"retained-database").unwrap();
    file.sync_all().unwrap();
    root.check_mutable_file(&fence).unwrap();
    drop(file);
    let (mut file, new_fence) = root.open_mutable_file("state.redb", 4096, true).unwrap();
    assert!(!new_fence.was_created());
    file.rewind().unwrap();
    let mut bytes = Vec::new();
    file.read_to_end(&mut bytes).unwrap();
    assert_eq!(bytes, b"retained-database");
    root.check_mutable_file(&new_fence).unwrap();
    assert!(root.open_mutable_file("missing", 4096, false).is_err());
}

#[test]
fn exclusive_offline_output_refuses_existing_failed_files_and_unsafe_names_without_overwrite() {
    use std::io::Write as _;
    let directory = root();
    let root = ProtectedRoot::open(directory.path()).unwrap();
    for name in ["", ".", "..", "../snapshot", "/snapshot", "nested/snapshot"] {
        assert!(root.create_mutable_file(name, 4096).is_err());
    }
    let (mut output, fence) = root.create_mutable_file("snapshot", 4096).unwrap();
    assert!(fence.was_created());
    output.write_all(b"partial-sensitive-snapshot").unwrap();
    output.sync_all().unwrap();
    root.check_mutable_file(&fence).unwrap();
    assert!(root.create_mutable_file("snapshot", 4096).is_err());
    assert_eq!(
        fs::read(directory.path().join("snapshot")).unwrap(),
        b"partial-sensitive-snapshot"
    );
    assert_eq!(output.metadata().unwrap().mode() & 0o777, 0o600);
    symlink(
        directory.path().join("snapshot"),
        directory.path().join("alias"),
    )
    .unwrap();
    assert!(root.create_mutable_file("alias", 4096).is_err());
    assert!(root
        .create_mutable_file("oversized", 1_073_741_825)
        .is_err());
    assert!(!directory.path().join("oversized").exists());
}

#[test]
fn mutable_engine_files_reject_unsafe_names_types_links_permissions_and_lengths() {
    let dir = root();
    let root = ProtectedRoot::open(dir.path()).unwrap();
    for name in ["", ".", "..", "../state", "/state", "nested/state"] {
        assert!(root.open_mutable_file(name, 4096, true).is_err());
    }
    assert!(root.open_mutable_file("state", 0, true).is_err());
    assert!(root
        .open_mutable_file("state", 1_073_741_825, true)
        .is_err());
    assert!(!dir.path().join("state").exists());
    secret(&dir.path().join("state"), b"bytes");
    symlink(dir.path().join("state"), dir.path().join("alias")).unwrap();
    assert!(root.open_mutable_file("alias", 4096, false).is_err());
    fs::hard_link(dir.path().join("state"), dir.path().join("hard")).unwrap();
    assert!(root.open_mutable_file("state", 4096, false).is_err());
    fs::remove_file(dir.path().join("hard")).unwrap();
    assert!(root.open_mutable_file("state", 4, false).is_err());
    fs::set_permissions(dir.path().join("state"), fs::Permissions::from_mode(0o640)).unwrap();
    assert!(root.open_mutable_file("state", 4096, false).is_err());
    fs::create_dir(dir.path().join("directory")).unwrap();
    assert!(root.open_mutable_file("directory", 4096, false).is_err());
    rustix::fs::mkfifoat(
        rustix::fs::CWD,
        dir.path().join("fifo"),
        Mode::RUSR | Mode::WUSR,
    )
    .unwrap();
    assert!(root.open_mutable_file("fifo", 4096, false).is_err());
}

#[test]
fn mutable_file_fence_detects_same_name_replacement_and_wrong_root() {
    let dir = root();
    let original = ProtectedRoot::open(dir.path()).unwrap();
    let (file, fence) = original.open_mutable_file("state", 4096, true).unwrap();
    fs::rename(dir.path().join("state"), dir.path().join("retired")).unwrap();
    secret(&dir.path().join("state"), b"replacement");
    assert!(original.check_mutable_file(&fence).is_err());
    assert_eq!(file.metadata().unwrap().len(), 0);
    let other_dir = root();
    let other_root = ProtectedRoot::open(other_dir.path()).unwrap();
    secret(&other_dir.path().join("state"), b"other");
    assert!(other_root.check_mutable_file(&fence).is_err());
}

#[test]
fn mutable_file_fence_detects_permission_growth_and_ancestor_substitution() {
    let dir = root();
    let parent = dir.path().join("parent");
    let nested = parent.join("private");
    fs::create_dir(&parent).unwrap();
    fs::create_dir(&nested).unwrap();
    fs::set_permissions(&nested, fs::Permissions::from_mode(0o700)).unwrap();
    let root = ProtectedRoot::open(&nested).unwrap();
    let (file, fence) = root.open_mutable_file("state", 4, true).unwrap();
    file.set_len(5).unwrap();
    assert!(root.check_mutable_file(&fence).is_err());
    file.set_len(4).unwrap();
    fs::set_permissions(nested.join("state"), fs::Permissions::from_mode(0o644)).unwrap();
    assert!(root.check_mutable_file(&fence).is_err());
    fs::set_permissions(nested.join("state"), fs::Permissions::from_mode(0o600)).unwrap();
    root.check_mutable_file(&fence).unwrap();
    fs::rename(&parent, dir.path().join("moved")).unwrap();
    fs::create_dir(&parent).unwrap();
    assert!(root.check_mutable_file(&fence).is_err());
}
