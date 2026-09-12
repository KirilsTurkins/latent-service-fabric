use super::*;
use std::fs;
use std::os::unix::fs::{symlink, PermissionsExt};

fn private_key(root: &Path) -> std::path::PathBuf {
    let parent = root.join("private");
    fs::create_dir(&parent).unwrap();
    fs::set_permissions(&parent, fs::Permissions::from_mode(0o700)).unwrap();
    let path = parent.join("key");
    fs::write(&path, [0x37; 32]).unwrap();
    fs::set_permissions(&path, fs::Permissions::from_mode(0o600)).unwrap();
    path
}

#[test]
fn private_exact_key_is_consumed_without_creating_storage_or_reading_compiler() {
    let directory = TempDir::new().unwrap();
    let path = private_key(directory.path());
    assert_eq!(*super::super::key::read(&path).unwrap(), [0x37; 32]);
    let settings = parsed(directory.path()).derive().unwrap();
    let aot = settings.isolated_aot.unwrap();
    assert_eq!(aot.approved_digest, [0xab; 32]);
    assert!(!aot.executable.exists());
    assert!(!aot.cache.blob_root.exists());
    assert!(!aot.cache.receipt_root.exists());
    assert!(!settings.data_directory.exists());
}

#[test]
fn wrong_lengths_permissions_and_links_reject_with_static_errors() {
    let directory = TempDir::new().unwrap();
    let path = private_key(directory.path());
    for length in [0, 31, 33, 4096] {
        fs::write(&path, vec![0x37; length]).unwrap();
        let failure = super::super::key::read(&path).err().unwrap();
        assert_eq!(
            failure.message,
            "invalid standalone configuration: isolatedAot.keyFile"
        );
        assert!(failure.details.is_empty());
    }
    fs::write(&path, [0x37; 32]).unwrap();
    for mode in [0o200, 0o640, 0o604, 0o700, 0o4600] {
        fs::set_permissions(&path, fs::Permissions::from_mode(mode)).unwrap();
        assert!(super::super::key::read(&path).is_err());
    }
    fs::set_permissions(&path, fs::Permissions::from_mode(0o400)).unwrap();
    assert!(super::super::key::read(&path).is_ok());
    fs::hard_link(&path, directory.path().join("key-link")).unwrap();
    assert!(super::super::key::read(&path).is_err());
    fs::remove_file(directory.path().join("key-link")).unwrap();
    let link = path.with_file_name("symlink");
    symlink(&path, &link).unwrap();
    assert!(super::super::key::read(&link).is_err());
    fs::set_permissions(path.parent().unwrap(), fs::Permissions::from_mode(0o755)).unwrap();
    assert!(super::super::key::read(&path).is_err());
}

#[test]
fn zero_key_and_cache_symlink_aliases_cannot_enter_settings() {
    let directory = TempDir::new().unwrap();
    let key = private_key(directory.path());
    fs::write(&key, [0; 32]).unwrap();
    assert!(parsed(directory.path()).derive().is_err());
    fs::write(&key, [0x37; 32]).unwrap();
    fs::create_dir(directory.path().join("data")).unwrap();
    symlink(
        directory.path().join("data"),
        directory.path().join("alias"),
    )
    .unwrap();
    let mut config = parsed(directory.path());
    config.isolated_aot.as_mut().unwrap().blob_root = directory.path().join("alias/blobs");
    assert!(config.derive().is_err());
    assert!(!directory.path().join("data/blobs").exists());
}
