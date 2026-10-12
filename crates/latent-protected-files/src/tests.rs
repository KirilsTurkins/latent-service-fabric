use super::*;
use std::fs;
use std::os::unix::fs::{symlink, PermissionsExt};
use tempfile::{Builder, TempDir};

fn named_user_acl(path: &Path, permissions: u16, directory: bool) {
    // Linux POSIX ACL xattr v2: a named user is governed by the group-mode mask,
    // independently of the owning GID. No external setfacl tool is required.
    let mut bytes = 2_u32.to_le_bytes().to_vec();
    for (tag, mode, id) in [
        (1_u16, if directory { 7_u16 } else { 6_u16 }, u32::MAX),
        (2, permissions, 65_534),
        (4, 0, u32::MAX),
        (16, permissions, u32::MAX),
        (32, 0, u32::MAX),
    ] {
        bytes.extend_from_slice(&tag.to_le_bytes());
        bytes.extend_from_slice(&mode.to_le_bytes());
        bytes.extend_from_slice(&id.to_le_bytes());
    }
    rustix::fs::setxattr(
        path,
        "system.posix_acl_access",
        &bytes,
        rustix::fs::XattrFlags::empty(),
    )
    .expect("Linux fixture filesystem supports POSIX access ACLs");
}

#[test]
fn named_user_acl_cannot_hide_behind_a_trusted_service_group() {
    use std::os::unix::fs::MetadataExt;
    let root = private_directory();
    fs::set_permissions(root.path(), fs::Permissions::from_mode(0o755)).unwrap();
    let path = root.path().join("secret");
    write(&path, b"synthetic-acl-fixture", 0o600);
    named_user_acl(&path, 4, false);
    let metadata = fs::metadata(&path).unwrap();
    assert_eq!(metadata.mode() & 0o777, 0o640);
    assert_eq!(metadata.gid(), rustix::process::getegid().as_raw());
    assert!(read(&path, 32, ProtectedFilePolicy::Secret, "test").is_err());

    // A named user's search right also prevents an ancestor from being treated
    // as a private directory merely because its group bits name a trusted GID.
    let nested = root.path().join("nested");
    fs::create_dir(&nested).unwrap();
    named_user_acl(&nested, 1, true);
    let path = nested.join("secret");
    write(&path, b"synthetic-acl-fixture", 0o644);
    assert_eq!(fs::metadata(&nested).unwrap().mode() & 0o777, 0o710);
    assert!(read(&path, 32, ProtectedFilePolicy::Secret, "test").is_err());
}

#[test]
#[ignore = "requires a privileged disposable Linux fixture; run explicitly with --ignored"]
fn unexpected_file_and_directory_owners_are_rejected() {
    use rustix::process::Uid;
    assert!(rustix::process::geteuid().is_root());
    let root = Builder::new()
        .prefix("lsf-protected-owner-")
        .tempdir_in("/tmp")
        .unwrap();
    let leaf = root.path().join("secret");
    write(&leaf, b"synthetic-owner-fixture", 0o600);
    assert!(read(&leaf, 32, ProtectedFilePolicy::Secret, "test").is_ok());
    rustix::fs::chown(&leaf, Some(Uid::from_raw(65_534)), None).unwrap();
    assert!(read(&leaf, 32, ProtectedFilePolicy::Secret, "test").is_err());
    rustix::fs::chown(&leaf, Some(Uid::ROOT), None).unwrap();
    assert!(read(&leaf, 32, ProtectedFilePolicy::Secret, "test").is_ok());
    rustix::fs::chown(root.path(), Some(Uid::from_raw(65_534)), None).unwrap();
    assert!(read(&leaf, 32, ProtectedFilePolicy::Integrity, "test").is_err());
}

fn private_directory() -> TempDir {
    let directory = TempDir::new().unwrap();
    fs::set_permissions(directory.path(), fs::Permissions::from_mode(0o700)).unwrap();
    directory
}

fn write(path: &Path, bytes: &[u8], mode: u32) {
    fs::write(path, bytes).expect("write protected fixture");
    fs::set_permissions(path, fs::Permissions::from_mode(mode)).expect("set protected mode");
}

#[test]
fn secret_policy_accepts_owner_service_group_and_private_directory_reads() {
    let root = private_directory();
    let owner = root.path().join("owner.json");
    let group = root.path().join("group.json");
    let private_public_mode = root.path().join("private-public-mode.json");
    write(&owner, b"owner", 0o600);
    write(&group, b"group", 0o640);
    write(&private_public_mode, b"private", 0o644);
    assert_eq!(
        read(&owner, 32, ProtectedFilePolicy::Secret, "test").unwrap(),
        b"owner"
    );
    assert_eq!(
        read(&group, 32, ProtectedFilePolicy::Secret, "test").unwrap(),
        b"group"
    );
    assert_eq!(
        read(
            &private_public_mode,
            32,
            ProtectedFilePolicy::Secret,
            "test"
        )
        .unwrap(),
        b"private"
    );
}

#[test]
fn secret_policy_rejects_public_reads_on_traversable_paths_and_writable_group_access() {
    let public = Builder::new()
        .prefix("lsf-protected-")
        .tempfile_in("/tmp")
        .unwrap();
    fs::set_permissions(public.path(), fs::Permissions::from_mode(0o604)).unwrap();
    assert!(read(public.path(), 32, ProtectedFilePolicy::Secret, "test").is_err());

    let root = private_directory();
    let writable = root.path().join("group-write");
    write(&writable, b"secret", 0o620);
    assert!(read(&writable, 32, ProtectedFilePolicy::Secret, "test").is_err());
}

#[test]
fn integrity_policy_allows_public_reads_but_not_untrusted_writes() {
    let root = private_directory();
    let readable = root.path().join("readable.json");
    let writable = root.path().join("writable.json");
    write(&readable, b"policy", 0o644);
    write(&writable, b"policy", 0o664);
    assert_eq!(
        read(&readable, 32, ProtectedFilePolicy::Integrity, "test").unwrap(),
        b"policy"
    );
    assert!(read(&writable, 32, ProtectedFilePolicy::Integrity, "test").is_err());
}

#[test]
fn symlinks_hardlinks_and_untrusted_ancestor_writes_fail_closed() {
    let root = private_directory();
    let original = root.path().join("original");
    let alias = root.path().join("alias");
    let link = root.path().join("link");
    write(&original, b"secret", 0o600);
    fs::hard_link(&original, &alias).unwrap();
    symlink(&original, &link).unwrap();
    assert!(read(&original, 32, ProtectedFilePolicy::Secret, "test").is_err());
    assert!(read(&link, 32, ProtectedFilePolicy::Secret, "test").is_err());

    let writable = root.path().join("writable");
    fs::create_dir(&writable).unwrap();
    fs::set_permissions(&writable, fs::Permissions::from_mode(0o777)).unwrap();
    let nested = writable.join("secret");
    write(&nested, b"secret", 0o600);
    assert!(read(&nested, 32, ProtectedFilePolicy::Secret, "test").is_err());
}

#[test]
fn pathname_replacement_does_not_redirect_opened_descriptor() {
    let root = private_directory();
    let path = root.path().join("authority");
    let replacement = root.path().join("replacement");
    let archived = root.path().join("archived");
    write(&path, b"original", 0o600);
    write(&replacement, b"replacement", 0o600);

    let bytes =
        platform::read_with_checkpoint(&path, 32, ProtectedFilePolicy::Secret, "test", |point| {
            if point == platform::ReadCheckpoint::OpenedLeaf {
                fs::rename(&path, &archived).unwrap();
                fs::rename(&replacement, &path).unwrap();
            }
            Ok(())
        })
        .unwrap();
    assert_eq!(bytes, b"original");
    assert_eq!(fs::read(path).unwrap(), b"replacement");
}

#[test]
fn content_change_after_snapshot_fails_closed() {
    let root = private_directory();
    let path = root.path().join("authority");
    write(&path, b"before", 0o600);

    let result =
        platform::read_with_checkpoint(&path, 32, ProtectedFilePolicy::Secret, "test", |point| {
            if point == platform::ReadCheckpoint::SnapshottedLeaf {
                // A length change makes this deterministic even when the test
                // filesystem rounds both writes to the same timestamp tick.
                fs::write(&path, b"changed-after-snapshot").unwrap();
            }
            Ok(())
        });
    assert!(result.is_err());
}

#[test]
fn fifo_is_rejected_without_waiting_for_a_writer() {
    let root = private_directory();
    let fifo = root.path().join("fifo");
    rustix::fs::mkfifoat(
        rustix::fs::CWD,
        &fifo,
        rustix::fs::Mode::RUSR | rustix::fs::Mode::WUSR,
    )
    .unwrap();
    assert!(read(&fifo, 32, ProtectedFilePolicy::Secret, "test").is_err());
}

#[test]
fn bounded_read_rejects_oversized_content() {
    let root = private_directory();
    let path = root.path().join("large");
    write(&path, b"12345", 0o600);
    assert!(read(&path, 4, ProtectedFilePolicy::Secret, "test").is_err());
}
