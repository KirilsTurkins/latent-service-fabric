use latent_core::PlatformError;
use std::path::Path;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(super) enum ProtectedFilePolicy {
    Secret,
    Integrity,
}

#[must_use]
pub(super) const fn supported() -> bool {
    cfg!(all(target_os = "linux", target_arch = "x86_64"))
}

pub(super) fn read(
    path: &Path,
    maximum_bytes: u64,
    policy: ProtectedFilePolicy,
    field: &'static str,
) -> Result<Vec<u8>, PlatformError> {
    platform::read(path, maximum_bytes, policy, field)
}

#[cfg(all(target_os = "linux", target_arch = "x86_64"))]
mod platform {
    use super::ProtectedFilePolicy;
    use latent_core::PlatformError;
    use rustix::fs::{Mode, OFlags};
    use std::ffi::OsString;
    use std::fs::File;
    use std::io::Read;
    use std::os::unix::fs::MetadataExt;
    use std::path::{Component, Path, PathBuf};

    const MAXIMUM_PATH_BYTES: usize = 4096;

    #[derive(Clone, Copy, Debug, PartialEq, Eq)]
    struct Snapshot {
        device: u64,
        inode: u64,
        mode: u32,
        links: u64,
        owner: u32,
        group: u32,
        length: u64,
        modified_seconds: i64,
        modified_nanos: i64,
        changed_seconds: i64,
        changed_nanos: i64,
    }

    impl Snapshot {
        fn from(metadata: &std::fs::Metadata) -> Self {
            Self {
                device: metadata.dev(),
                inode: metadata.ino(),
                mode: metadata.mode(),
                links: metadata.nlink(),
                owner: metadata.uid(),
                group: metadata.gid(),
                length: metadata.len(),
                modified_seconds: metadata.mtime(),
                modified_nanos: metadata.mtime_nsec(),
                changed_seconds: metadata.ctime(),
                changed_nanos: metadata.ctime_nsec(),
            }
        }
    }

    pub(super) fn read(
        path: &Path,
        maximum_bytes: u64,
        policy: ProtectedFilePolicy,
        field: &'static str,
    ) -> Result<Vec<u8>, PlatformError> {
        let failure = || super::super::invalid(field);
        if maximum_bytes == 0 || path.as_os_str().len() > MAXIMUM_PATH_BYTES {
            return Err(failure());
        }
        let absolute = absolute(path).map_err(|()| failure())?;
        let parts = normal_components(&absolute).map_err(|()| failure())?;
        let (leaf, ancestors) = parts.split_last().ok_or_else(failure)?;
        let uid = rustix::process::geteuid().as_raw();
        let gid = rustix::process::getegid().as_raw();

        let mut directory = File::from(
            rustix::fs::open("/", directory_flags(), Mode::empty()).map_err(|_| failure())?,
        );
        validate_directory(&directory, uid, gid).map_err(|()| failure())?;
        for ancestor in ancestors {
            directory = File::from(
                rustix::fs::openat(&directory, ancestor, directory_flags(), Mode::empty())
                    .map_err(|_| failure())?,
            );
            validate_directory(&directory, uid, gid).map_err(|()| failure())?;
        }

        let mut file = File::from(
            rustix::fs::openat(
                &directory,
                leaf,
                OFlags::RDONLY | OFlags::NOFOLLOW | OFlags::CLOEXEC | OFlags::NONBLOCK,
                Mode::empty(),
            )
            .map_err(|_| failure())?,
        );
        let before = file.metadata().map_err(|_| failure())?;
        validate_file(&before, policy, uid, gid, maximum_bytes).map_err(|()| failure())?;
        let before = Snapshot::from(&before);

        let mut bytes = Vec::with_capacity(
            usize::try_from(before.length.min(maximum_bytes)).map_err(|_| failure())?,
        );
        (&mut file)
            .take(maximum_bytes.saturating_add(1))
            .read_to_end(&mut bytes)
            .map_err(|_| failure())?;
        if u64::try_from(bytes.len()).map_err(|_| failure())? > maximum_bytes {
            return Err(failure());
        }

        let after = file.metadata().map_err(|_| failure())?;
        validate_file(&after, policy, uid, gid, maximum_bytes).map_err(|()| failure())?;
        if before != Snapshot::from(&after) || before.length != bytes.len() as u64 {
            return Err(failure());
        }
        Ok(bytes)
    }

    fn absolute(path: &Path) -> Result<PathBuf, ()> {
        let absolute = if path.is_absolute() {
            path.to_path_buf()
        } else {
            std::env::current_dir().map_err(|_| ())?.join(path)
        };
        if absolute.as_os_str().len() > MAXIMUM_PATH_BYTES {
            return Err(());
        }
        Ok(absolute)
    }

    fn normal_components(path: &Path) -> Result<Vec<OsString>, ()> {
        let mut parts = Vec::new();
        for part in path.components() {
            match part {
                Component::RootDir | Component::CurDir => {}
                Component::Normal(name) => parts.push(name.to_os_string()),
                Component::ParentDir | Component::Prefix(_) => return Err(()),
            }
        }
        Ok(parts)
    }

    fn directory_flags() -> OFlags {
        OFlags::RDONLY | OFlags::DIRECTORY | OFlags::NOFOLLOW | OFlags::CLOEXEC | OFlags::NONBLOCK
    }

    fn validate_directory(directory: &File, uid: u32, gid: u32) -> Result<(), ()> {
        let metadata = directory.metadata().map_err(|_| ())?;
        if !metadata.is_dir() || (metadata.uid() != 0 && metadata.uid() != uid) {
            return Err(());
        }
        let mode = metadata.mode();
        let group_writable = mode & 0o020 != 0;
        let other_writable = mode & 0o002 != 0;
        if group_writable && metadata.gid() != gid {
            return Err(());
        }
        if other_writable && !(metadata.uid() == 0 && mode & 0o1000 != 0) {
            return Err(());
        }
        Ok(())
    }

    fn validate_file(
        metadata: &std::fs::Metadata,
        policy: ProtectedFilePolicy,
        uid: u32,
        gid: u32,
        maximum_bytes: u64,
    ) -> Result<(), ()> {
        if !metadata.is_file()
            || metadata.nlink() != 1
            || metadata.len() > maximum_bytes
            || (metadata.uid() != 0 && metadata.uid() != uid)
        {
            return Err(());
        }
        let mode = metadata.mode() & 0o7777;
        if mode & 0o7000 != 0 || mode & 0o111 != 0 || mode & 0o400 == 0 {
            return Err(());
        }
        match policy {
            ProtectedFilePolicy::Secret => {
                if mode & 0o007 != 0 || mode & 0o020 != 0 {
                    return Err(());
                }
                if mode & 0o040 != 0 && metadata.gid() != gid {
                    return Err(());
                }
            }
            ProtectedFilePolicy::Integrity => {
                if mode & 0o022 != 0 {
                    return Err(());
                }
            }
        }
        Ok(())
    }
}

#[cfg(not(all(target_os = "linux", target_arch = "x86_64")))]
mod platform {
    use super::ProtectedFilePolicy;
    use latent_core::PlatformError;
    use std::fs::File;
    use std::io::Read;
    use std::path::Path;

    pub(super) fn read(
        path: &Path,
        maximum_bytes: u64,
        _policy: ProtectedFilePolicy,
        field: &'static str,
    ) -> Result<Vec<u8>, PlatformError> {
        let failure = || super::super::invalid(field);
        let mut file = File::open(path).map_err(|_| failure())?;
        let metadata = file.metadata().map_err(|_| failure())?;
        if !metadata.is_file() || metadata.len() > maximum_bytes {
            return Err(failure());
        }
        let mut bytes = Vec::new();
        (&mut file)
            .take(maximum_bytes.saturating_add(1))
            .read_to_end(&mut bytes)
            .map_err(|_| failure())?;
        if bytes.len() as u64 > maximum_bytes {
            return Err(failure());
        }
        Ok(bytes)
    }
}

#[cfg(all(test, target_os = "linux", target_arch = "x86_64"))]
mod tests {
    use super::*;
    use std::fs;
    use std::os::unix::fs::{symlink, PermissionsExt};
    use tempfile::TempDir;

    fn write(path: &Path, bytes: &[u8], mode: u32) {
        fs::write(path, bytes).expect("write protected fixture");
        fs::set_permissions(path, fs::Permissions::from_mode(mode)).expect("set protected mode");
    }

    #[test]
    fn secret_policy_accepts_owner_and_service_group_read_only_files() {
        let root = TempDir::new().unwrap();
        let owner = root.path().join("owner.json");
        let group = root.path().join("group.json");
        write(&owner, b"owner", 0o600);
        write(&group, b"group", 0o640);
        assert_eq!(
            read(&owner, 32, ProtectedFilePolicy::Secret, "test").unwrap(),
            b"owner"
        );
        assert_eq!(
            read(&group, 32, ProtectedFilePolicy::Secret, "test").unwrap(),
            b"group"
        );
    }

    #[test]
    fn secret_policy_rejects_public_or_writable_group_access() {
        let root = TempDir::new().unwrap();
        for (name, mode) in [("public", 0o604), ("group-write", 0o620)] {
            let path = root.path().join(name);
            write(&path, b"secret", mode);
            assert!(read(&path, 32, ProtectedFilePolicy::Secret, "test").is_err());
        }
    }

    #[test]
    fn integrity_policy_allows_public_reads_but_not_untrusted_writes() {
        let root = TempDir::new().unwrap();
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
        let root = TempDir::new().unwrap();
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
    fn fifo_is_rejected_without_waiting_for_a_writer() {
        let root = TempDir::new().unwrap();
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
        let root = TempDir::new().unwrap();
        let path = root.path().join("large");
        write(&path, b"12345", 0o600);
        assert!(read(&path, 4, ProtectedFilePolicy::Secret, "test").is_err());
    }
}
