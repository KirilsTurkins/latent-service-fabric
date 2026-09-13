use latent_core::PlatformError;
use std::path::Path;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(super) enum ProtectedFilePolicy {
    Secret,
    Integrity,
}

pub(super) fn read(
    path: &Path,
    maximum_bytes: u64,
    policy: ProtectedFilePolicy,
    field: &'static str,
) -> Result<Vec<u8>, PlatformError> {
    platform::read(path, maximum_bytes, policy, field)
}

pub(super) fn execution_profile_marker(root: &Path, create: bool) -> Result<bool, PlatformError> {
    platform::execution_profile_marker(root, create)
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

    const EXECUTION_MARKER: &str = "EXECUTION_PROFILE";
    const EXTERNAL_PROFILE: &[u8] = b"lsf-external-capsule-profile-v1\n";

    fn marker_failure() -> PlatformError {
        super::super::invalid("securityProfile.markerProtection")
    }

    fn marker_directory(path: &Path, create: bool) -> Result<Option<File>, PlatformError> {
        let absolute = absolute(path).map_err(|()| marker_failure())?;
        let parts = normal_components(&absolute).map_err(|()| marker_failure())?;
        if parts.is_empty() || parts.len() > 256 {
            return Err(marker_failure());
        }
        let uid = rustix::process::geteuid().as_raw();
        let gid = rustix::process::getegid().as_raw();
        let mut directory = File::from(
            rustix::fs::open("/", directory_flags(), Mode::empty())
                .map_err(|_| marker_failure())?,
        );
        validate_directory(&directory, uid, gid).map_err(|()| marker_failure())?;
        for part in parts {
            let next = match rustix::fs::openat(&directory, &part, directory_flags(), Mode::empty())
            {
                Ok(fd) => fd,
                Err(rustix::io::Errno::NOENT) if !create => return Ok(None),
                Err(rustix::io::Errno::NOENT) => {
                    match rustix::fs::mkdirat(&directory, &part, Mode::from_raw_mode(0o700)) {
                        Ok(()) | Err(rustix::io::Errno::EXIST) => (),
                        Err(_) => return Err(marker_failure()),
                    }
                    directory.sync_all().map_err(|_| marker_failure())?;
                    rustix::fs::openat(&directory, &part, directory_flags(), Mode::empty())
                        .map_err(|_| marker_failure())?
                }
                Err(_) => return Err(marker_failure()),
            };
            directory = File::from(next);
            validate_directory(&directory, uid, gid).map_err(|()| marker_failure())?;
        }
        // A mutable shared temporary directory may be an ancestor, never the
        // external-capsule data root itself.
        if directory.metadata().map_err(|_| marker_failure())?.mode() & 0o022 != 0 {
            return Err(marker_failure());
        }
        Ok(Some(directory))
    }

    pub(super) fn execution_profile_marker(
        root: &Path,
        create: bool,
    ) -> Result<bool, PlatformError> {
        use std::io::Write as _;
        let Some(directory) = marker_directory(root, create)? else {
            return Ok(false);
        };
        let flags = OFlags::RDONLY | OFlags::NOFOLLOW | OFlags::CLOEXEC | OFlags::NONBLOCK;
        let mut file = match rustix::fs::openat(&directory, EXECUTION_MARKER, flags, Mode::empty())
        {
            Ok(fd) => File::from(fd),
            Err(rustix::io::Errno::NOENT) if !create => return Ok(false),
            Err(rustix::io::Errno::NOENT) => {
                let flags = OFlags::WRONLY
                    | OFlags::CREATE
                    | OFlags::EXCL
                    | OFlags::NOFOLLOW
                    | OFlags::CLOEXEC;
                match rustix::fs::openat(
                    &directory,
                    EXECUTION_MARKER,
                    flags,
                    Mode::from_raw_mode(0o600),
                ) {
                    Ok(fd) => {
                        let mut file = File::from(fd);
                        require_mode_only_permissions(&file).map_err(|()| marker_failure())?;
                        validate_file(
                            &file.metadata().map_err(|_| marker_failure())?,
                            ProtectedFilePolicy::Integrity,
                            rustix::process::geteuid().as_raw(),
                            rustix::process::getegid().as_raw(),
                            64,
                            false,
                        )
                        .map_err(|()| marker_failure())?;
                        file.write_all(EXTERNAL_PROFILE)
                            .map_err(|_| marker_failure())?;
                        file.sync_all().map_err(|_| marker_failure())?;
                        directory.sync_all().map_err(|_| marker_failure())?;
                        return Ok(true);
                    }
                    Err(rustix::io::Errno::EXIST) => File::from(
                        rustix::fs::openat(
                            &directory,
                            EXECUTION_MARKER,
                            OFlags::RDONLY | OFlags::NOFOLLOW | OFlags::CLOEXEC | OFlags::NONBLOCK,
                            Mode::empty(),
                        )
                        .map_err(|_| marker_failure())?,
                    ),
                    Err(_) => return Err(marker_failure()),
                }
            }
            Err(_) => return Err(marker_failure()),
        };
        require_mode_only_permissions(&file).map_err(|()| marker_failure())?;
        let before = file.metadata().map_err(|_| marker_failure())?;
        validate_file(
            &before,
            ProtectedFilePolicy::Integrity,
            rustix::process::geteuid().as_raw(),
            rustix::process::getegid().as_raw(),
            64,
            false,
        )
        .map_err(|()| marker_failure())?;
        let snapshot = Snapshot::from(&before);
        let mut bytes = Vec::with_capacity(64);
        (&mut file)
            .take(65)
            .read_to_end(&mut bytes)
            .map_err(|_| marker_failure())?;
        require_mode_only_permissions(&file).map_err(|()| marker_failure())?;
        if snapshot != Snapshot::from(&file.metadata().map_err(|_| marker_failure())?)
            || bytes != EXTERNAL_PROFILE
        {
            return Err(marker_failure());
        }
        Ok(true)
    }

    #[derive(Clone, Copy, Debug, PartialEq, Eq)]
    pub(super) enum ReadCheckpoint {
        OpenedLeaf,
        SnapshottedLeaf,
    }

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
        read_with_checkpoint(path, maximum_bytes, policy, field, |_| Ok(()))
    }

    pub(super) fn read_with_checkpoint<F>(
        path: &Path,
        maximum_bytes: u64,
        policy: ProtectedFilePolicy,
        field: &'static str,
        mut checkpoint: F,
    ) -> Result<Vec<u8>, PlatformError>
    where
        F: FnMut(ReadCheckpoint) -> Result<(), PlatformError>,
    {
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
        let mut private_path = validate_directory(&directory, uid, gid).map_err(|()| failure())?;
        for ancestor in ancestors {
            directory = File::from(
                rustix::fs::openat(&directory, ancestor, directory_flags(), Mode::empty())
                    .map_err(|_| failure())?,
            );
            private_path |= validate_directory(&directory, uid, gid).map_err(|()| failure())?;
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
        checkpoint(ReadCheckpoint::OpenedLeaf)?;
        require_mode_only_permissions(&file).map_err(|()| failure())?;
        let before = file.metadata().map_err(|_| failure())?;
        validate_file(&before, policy, uid, gid, maximum_bytes, private_path)
            .map_err(|()| failure())?;
        let before = Snapshot::from(&before);
        checkpoint(ReadCheckpoint::SnapshottedLeaf)?;

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
        require_mode_only_permissions(&file).map_err(|()| failure())?;
        validate_file(&after, policy, uid, gid, maximum_bytes, private_path)
            .map_err(|()| failure())?;
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

    // POSIX group mode bits represent the ACL mask when a named-user/group ACL
    // exists. A trusted owning GID alone cannot prove who can read or traverse.
    // A one-byte probe rejects any extended ACL without allocating its payload.
    // Unknown/unsupported inspection fails closed rather than assuming privacy.
    fn require_mode_only_permissions(file: &File) -> Result<(), ()> {
        let mut probe = [0_u8; 1];
        match rustix::fs::fgetxattr(file, "system.posix_acl_access", &mut probe) {
            Err(rustix::io::Errno::NODATA) => Ok(()),
            Ok(_) | Err(_) => Err(()),
        }
    }

    /// Returns whether this directory blocks traversal by accounts outside the
    /// effective user/service group. Sticky root-owned world-writable ancestors
    /// such as `/tmp` are accepted for name stability but do not make a secret
    /// leaf private.
    fn validate_directory(directory: &File, uid: u32, gid: u32) -> Result<bool, ()> {
        require_mode_only_permissions(directory)?;
        let metadata = directory.metadata().map_err(|_| ())?;
        if !metadata.is_dir() || (metadata.uid() != 0 && metadata.uid() != uid) {
            return Err(());
        }
        let mode = metadata.mode();
        let group_writable = mode & 0o020 != 0;
        let other_writable = mode & 0o002 != 0;
        let sticky_shared = metadata.uid() == 0 && other_writable && mode & 0o1000 != 0;
        if group_writable && metadata.gid() != gid && !sticky_shared {
            return Err(());
        }
        if other_writable && !sticky_shared {
            return Err(());
        }
        let untrusted_group_can_traverse = metadata.gid() != gid && mode & 0o010 != 0;
        let untrusted_can_traverse = mode & 0o001 != 0 || untrusted_group_can_traverse;
        Ok(!untrusted_can_traverse)
    }

    fn validate_file(
        metadata: &std::fs::Metadata,
        policy: ProtectedFilePolicy,
        uid: u32,
        gid: u32,
        maximum_bytes: u64,
        private_path: bool,
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
                if mode & 0o022 != 0 {
                    return Err(());
                }
                let untrusted_read =
                    mode & 0o004 != 0 || (mode & 0o040 != 0 && metadata.gid() != gid);
                if untrusted_read && !private_path {
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

    pub(super) fn execution_profile_marker(
        _root: &Path,
        _create: bool,
    ) -> Result<bool, PlatformError> {
        Err(super::super::invalid(
            "securityProfile.markerPlatformUnsupported",
        ))
    }

    /// Compatibility-only loader. It preserves bounded regular-file behavior on
    /// unsupported hosts, but it is not evidence for `external-capsule-v1`.
    /// #280 must reject that profile where the Linux protected-file primitive is
    /// unavailable rather than treating this fallback as equivalent protection.
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
mod tests;
