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
