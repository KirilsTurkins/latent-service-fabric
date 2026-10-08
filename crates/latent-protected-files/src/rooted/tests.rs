use super::*;
use std::{
    fs,
    os::unix::fs::{symlink, FileTypeExt, PermissionsExt},
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

#[test]
fn exclusive_mutable_creation_preserves_existing_empty_malformed_and_linked_leaves() {
    let dir = root();
    let root = ProtectedRoot::open(dir.path()).unwrap();
    for (name, bytes) in [("empty", b"".as_slice()), ("malformed", b"bad-checkpoint")] {
        let path = dir.path().join(name);
        secret(&path, bytes);
        let before = path.metadata().unwrap();
        assert!(root.create_mutable_file(name, 4096).is_err());
        let after = path.metadata().unwrap();
        assert_eq!(fs::read(&path).unwrap(), bytes);
        assert_eq!(
            (after.dev(), after.ino(), after.len(), after.mode()),
            (before.dev(), before.ino(), before.len(), before.mode())
        );
    }
    let target = dir.path().join("malformed");
    symlink(&target, dir.path().join("alias")).unwrap();
    assert!(root.create_mutable_file("alias", 4096).is_err());
    assert_eq!(fs::read_link(dir.path().join("alias")).unwrap(), target);
    fs::hard_link(&target, dir.path().join("hard")).unwrap();
    assert!(root.create_mutable_file("hard", 4096).is_err());
    assert_eq!(fs::read(&target).unwrap(), b"bad-checkpoint");
    assert_eq!(target.metadata().unwrap().nlink(), 2);
    fs::create_dir(dir.path().join("directory")).unwrap();
    assert!(root.create_mutable_file("directory", 4096).is_err());
    assert!(dir.path().join("directory").is_dir());
    rustix::fs::mkfifoat(
        rustix::fs::CWD,
        dir.path().join("fifo"),
        Mode::RUSR | Mode::WUSR,
    )
    .unwrap();
    assert!(root.create_mutable_file("fifo", 4096).is_err());
    assert!(fs::symlink_metadata(dir.path().join("fifo"))
        .unwrap()
        .file_type()
        .is_fifo());
}

#[test]
fn exclusive_mutable_creation_has_one_racing_owner_and_retains_winner_identity() {
    use std::{io::Write, sync::Barrier};
    let dir = root();
    let left = ProtectedRoot::open(dir.path()).unwrap();
    let right = ProtectedRoot::open(dir.path()).unwrap();
    let barrier = Barrier::new(3);
    let (left_result, right_result) = std::thread::scope(|scope| {
        let left_job = scope.spawn(|| {
            barrier.wait();
            let (mut file, fence) = left.create_mutable_file("checkpoint", 4096)?;
            file.write_all(b"left-owner").unwrap();
            file.sync_all().unwrap();
            left.check_mutable_file(&fence).unwrap();
            Ok::<_, PlatformError>((file, fence))
        });
        let right_job = scope.spawn(|| {
            barrier.wait();
            let (mut file, fence) = right.create_mutable_file("checkpoint", 4096)?;
            file.write_all(b"right-owner").unwrap();
            file.sync_all().unwrap();
            right.check_mutable_file(&fence).unwrap();
            Ok::<_, PlatformError>((file, fence))
        });
        barrier.wait();
        (left_job.join().unwrap(), right_job.join().unwrap())
    });
    let (file, fence, expected) = match (left_result, right_result) {
        (Ok((file, fence)), Err(_)) => (file, fence, b"left-owner".as_slice()),
        (Err(_), Ok((file, fence))) => (file, fence, b"right-owner".as_slice()),
        _ => panic!("exclusive creation must have exactly one owner"),
    };
    left.check_mutable_file(&fence).unwrap();
    right.check_mutable_file(&fence).unwrap();
    let actual = file.metadata().unwrap();
    let named = dir.path().join("checkpoint").metadata().unwrap();
    assert_eq!((actual.dev(), actual.ino()), (named.dev(), named.ino()));
    assert_eq!(actual.mode() & 0o7777, 0o600);
    assert_eq!(actual.nlink(), 1);
    assert_eq!(fs::read(dir.path().join("checkpoint")).unwrap(), expected);
    assert!(left.create_mutable_file("checkpoint", 4096).is_err());
    assert_eq!(fs::read(dir.path().join("checkpoint")).unwrap(), expected);
}

#[test]
fn fresh_root_inventory_refuses_every_old_entry_and_rechecks_from_original_descriptor() {
    let dir = root();
    let protected = ProtectedRoot::open(dir.path()).unwrap();
    protected.check_empty().unwrap();
    protected.check_empty().unwrap();
    secret(&dir.path().join("interrupted-empty"), b"");
    assert!(protected.check_empty().is_err());
    assert_eq!(fs::read(dir.path().join("interrupted-empty")).unwrap(), b"");
    fs::remove_file(dir.path().join("interrupted-empty")).unwrap();
    fs::create_dir(dir.path().join("unexpected-directory")).unwrap();
    assert!(protected.check_empty().is_err());
    fs::remove_dir(dir.path().join("unexpected-directory")).unwrap();
    symlink("missing", dir.path().join("unexpected-link")).unwrap();
    assert!(protected.check_empty().is_err());
    assert_eq!(
        fs::read_link(dir.path().join("unexpected-link")).unwrap(),
        Path::new("missing")
    );
    fs::remove_file(dir.path().join("unexpected-link")).unwrap();
    protected.check_empty().unwrap();
    let (_lock, lock_fence) = protected.create_mutable_file("owner.lock", 1).unwrap();
    protected.check_exact_mutable_files(&[&lock_fence]).unwrap();
    let (_engine, engine_fence) = protected.create_mutable_file("state", 4096).unwrap();
    assert!(protected.check_exact_mutable_files(&[&lock_fence]).is_err());
    protected
        .check_exact_mutable_files(&[&engine_fence, &lock_fence])
        .unwrap();
    protected
        .check_exact_mutable_files(&[&lock_fence, &engine_fence])
        .unwrap();
    secret(&dir.path().join("after-enumeration"), b"retained");
    assert!(protected
        .check_exact_mutable_files(&[&lock_fence, &engine_fence])
        .is_err());
    assert_eq!(
        fs::read(dir.path().join("after-enumeration")).unwrap(),
        b"retained"
    );
}

#[test]
fn fresh_root_inventory_refuses_duplicate_foreign_replaced_and_linked_fences() {
    let dir = root();
    let protected = ProtectedRoot::open(dir.path()).unwrap();
    let (_engine, fence) = protected.create_mutable_file("state", 4096).unwrap();
    assert!(protected
        .check_exact_mutable_files(&[&fence, &fence])
        .is_err());
    assert!(protected.check_exact_mutable_files(&[&fence; 5]).is_err());
    let foreign_dir = root();
    let foreign = ProtectedRoot::open(foreign_dir.path()).unwrap();
    let (_foreign_engine, foreign_fence) = foreign.create_mutable_file("state", 4096).unwrap();
    assert!(protected
        .check_exact_mutable_files(&[&foreign_fence])
        .is_err());
    fs::hard_link(dir.path().join("state"), dir.path().join("hard")).unwrap();
    assert!(protected.check_exact_mutable_files(&[&fence]).is_err());
    fs::remove_file(dir.path().join("hard")).unwrap();
    protected.check_exact_mutable_files(&[&fence]).unwrap();
    fs::rename(dir.path().join("state"), dir.path().join("retained")).unwrap();
    secret(&dir.path().join("state"), b"replacement");
    assert!(protected.check_exact_mutable_files(&[&fence]).is_err());
    assert_eq!(fs::read(dir.path().join("state")).unwrap(), b"replacement");
}

#[test]
fn exclusive_mutable_creation_rejects_unsafe_bounds_and_changed_ancestors_before_io() {
    let dir = root();
    let parent = dir.path().join("parent");
    let nested = parent.join("private");
    fs::create_dir(&parent).unwrap();
    fs::create_dir(&nested).unwrap();
    fs::set_permissions(&nested, fs::Permissions::from_mode(0o700)).unwrap();
    let root = ProtectedRoot::open(&nested).unwrap();
    for name in [
        "",
        ".",
        "..",
        "../checkpoint",
        "/checkpoint",
        "nested/checkpoint",
    ] {
        assert!(root.create_mutable_file(name, 4096).is_err());
    }
    assert!(root.create_mutable_file(&"a".repeat(256), 4096).is_err());
    assert!(root.create_mutable_file("checkpoint", 0).is_err());
    assert!(root
        .create_mutable_file("checkpoint", 1_073_741_825)
        .is_err());
    assert_eq!(fs::read_dir(&nested).unwrap().count(), 0);
    fs::set_permissions(&nested, fs::Permissions::from_mode(0o755)).unwrap();
    assert!(root.create_mutable_file("checkpoint", 4096).is_err());
    assert_eq!(fs::read_dir(&nested).unwrap().count(), 0);
    fs::set_permissions(&nested, fs::Permissions::from_mode(0o700)).unwrap();
    fs::rename(&parent, dir.path().join("moved")).unwrap();
    fs::create_dir(&parent).unwrap();
    assert!(root.create_mutable_file("checkpoint", 4096).is_err());
    assert!(!dir.path().join("moved/private/checkpoint").exists());
    assert!(!parent.join("private").exists());
}

#[test]
fn anchored_root_separation_allows_siblings_and_rejects_equal_ancestor_and_descendant_roots() {
    let top = root();
    let left_path = top.path().join("left");
    let right_path = top.path().join("right");
    let nested_path = left_path.join("nested");
    for path in [&left_path, &right_path, &nested_path] {
        fs::create_dir(path).unwrap();
        fs::set_permissions(path, fs::Permissions::from_mode(0o700)).unwrap();
    }
    let ancestor = ProtectedRoot::open(top.path()).unwrap();
    let left = ProtectedRoot::open(&left_path).unwrap();
    let same = ProtectedRoot::open(&left_path).unwrap();
    let right = ProtectedRoot::open(&right_path).unwrap();
    let nested = ProtectedRoot::open(&nested_path).unwrap();
    assert!(left.is_separate_from(&right).unwrap());
    assert!(right.is_separate_from(&left).unwrap());
    assert!(!left.is_separate_from(&same).unwrap());
    assert!(!left.is_separate_from(&nested).unwrap());
    assert!(!nested.is_separate_from(&left).unwrap());
    assert!(!left.is_separate_from(&ancestor).unwrap());
    assert!(!ancestor.is_separate_from(&left).unwrap());
    symlink(&right_path, top.path().join("alias")).unwrap();
    assert!(ProtectedRoot::open(&top.path().join("alias")).is_err());
}

#[test]
fn anchored_root_separation_refuses_changed_ancestry_and_grown_permissions() {
    let top = root();
    let parent = top.path().join("parent");
    let left_path = parent.join("left");
    let right_path = top.path().join("right");
    for path in [&parent, &left_path, &right_path] {
        fs::create_dir(path).unwrap();
        fs::set_permissions(path, fs::Permissions::from_mode(0o700)).unwrap();
    }
    let left = ProtectedRoot::open(&left_path).unwrap();
    let right = ProtectedRoot::open(&right_path).unwrap();
    assert!(left.is_separate_from(&right).unwrap());
    fs::set_permissions(&right_path, fs::Permissions::from_mode(0o755)).unwrap();
    assert!(left.is_separate_from(&right).is_err());
    assert!(right.is_separate_from(&left).is_err());
    fs::set_permissions(&right_path, fs::Permissions::from_mode(0o700)).unwrap();
    fs::rename(&parent, top.path().join("moved")).unwrap();
    fs::create_dir(&parent).unwrap();
    assert!(left.is_separate_from(&right).is_err());
    assert!(right.is_separate_from(&left).is_err());
}
