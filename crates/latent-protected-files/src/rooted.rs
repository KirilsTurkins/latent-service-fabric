//! Stricter reload semantics layered on the bootstrap permission checks: every
//! retained ancestor and the leaf name must still identify the opened object.
use crate::{platform, ProtectedFilePolicy};
use latent_core::{PlatformError, PlatformErrorCode};
use rustix::fs::{self, AtFlags, Mode, OFlags};
use std::{ffi::OsString, fs::File, io::Read, os::unix::fs::MetadataExt, path::Path};
use zeroize::Zeroizing;

struct Anchor {
    file: File,
    name: OsString,
    identity: (u64, u64),
}

/// Trusted control-path owner. It creates no directory or worker and exposes no
/// guest path lookup. The caller must bound the number of roots and file reads.
pub struct ProtectedRoot {
    chain: Vec<Anchor>,
    uid: u32,
    gid: u32,
}

/// Named mutable file identity owned by the same protected root. The engine
/// takes the descriptor; its control owner retains this fence and checks it on
/// every storage job. This value never permits opening a different root/name.
pub struct ProtectedMutableFile {
    name: String,
    root_identity: (u64, u64),
    file_identity: (u64, u64),
    maximum_bytes: u64,
}

impl ProtectedRoot {
    pub fn open(path: &Path) -> Result<Self, PlatformError> {
        if !path.is_absolute() {
            return Err(failure());
        }
        let absolute = platform::absolute(path).map_err(|()| failure())?;
        let parts = platform::normal_components(&absolute).map_err(|()| failure())?;
        if parts.is_empty() || parts.len() > 64 {
            return Err(failure());
        }
        let uid = rustix::process::geteuid().as_raw();
        let gid = rustix::process::getegid().as_raw();
        let mut chain = Vec::with_capacity(parts.len() + 1);
        let file = File::from(
            fs::open("/", platform::directory_flags(), Mode::empty()).map_err(|_| failure())?,
        );
        platform::validate_directory(&file, uid, gid).map_err(|()| failure())?;
        let metadata = file.metadata().map_err(|_| failure())?;
        chain.push(Anchor {
            file,
            name: OsString::new(),
            identity: (metadata.dev(), metadata.ino()),
        });
        for name in parts {
            let file = File::from(
                fs::openat(
                    &chain.last().expect("root anchor").file,
                    &name,
                    platform::directory_flags(),
                    Mode::empty(),
                )
                .map_err(|_| failure())?,
            );
            platform::validate_directory(&file, uid, gid).map_err(|()| failure())?;
            let metadata = file.metadata().map_err(|_| failure())?;
            chain.push(Anchor {
                file,
                name,
                identity: (metadata.dev(), metadata.ino()),
            });
        }
        let root = Self { chain, uid, gid };
        root.check()?;
        Ok(root)
    }

    /// Identity metadata only; never derives a public digest from secret bytes.
    #[must_use]
    pub fn identity(&self) -> (u64, u64) {
        self.chain.last().expect("root anchor").identity
    }

    /// Open an explicitly configured engine file without truncation, following
    /// links or creating parent directories. Initialization is create-new only;
    /// an existing failed database is never replaced by an empty descriptor.
    /// Runs on the fixed storage control worker, not an async/guest poller.
    pub fn open_mutable_file(
        &self,
        name: &str,
        maximum_bytes: u64,
        create: bool,
    ) -> Result<(File, ProtectedMutableFile), PlatformError> {
        if !valid_leaf(name) || maximum_bytes == 0 || maximum_bytes > 1_073_741_824 {
            return Err(state_failure());
        }
        self.check().map_err(|_| state_failure())?;
        let directory = &self.chain.last().expect("root anchor").file;
        let flags = OFlags::RDWR | OFlags::NOFOLLOW | OFlags::CLOEXEC | OFlags::NONBLOCK;
        let file = match fs::openat(directory, name, flags, Mode::empty()) {
            Ok(descriptor) => File::from(descriptor),
            Err(rustix::io::Errno::NOENT) if create => {
                let descriptor = fs::openat(
                    directory,
                    name,
                    flags | OFlags::CREATE | OFlags::EXCL,
                    Mode::RUSR | Mode::WUSR,
                )
                .map_err(|_| state_failure())?;
                let file = File::from(descriptor);
                file.sync_all().map_err(|_| state_failure())?;
                directory.sync_all().map_err(|_| state_failure())?;
                file
            }
            Err(_) => return Err(state_failure()),
        };
        platform::require_mode_only_permissions(&file).map_err(|()| state_failure())?;
        let metadata = file.metadata().map_err(|_| state_failure())?;
        mutable_metadata(&metadata, self.uid, maximum_bytes)?;
        let fence = ProtectedMutableFile {
            name: name.into(),
            root_identity: self.identity(),
            file_identity: (metadata.dev(), metadata.ino()),
            maximum_bytes,
        };
        self.check_mutable_file(&fence)?;
        Ok((file, fence))
    }

    /// Validate permissions, type, bounded file length and the current named
    /// inode/ancestor chain before accepting a storage operation. Engine locking
    /// and qualified filesystem/durability selection belong to the store owner.
    pub fn check_mutable_file(&self, fence: &ProtectedMutableFile) -> Result<(), PlatformError> {
        self.check().map_err(|_| state_failure())?;
        if fence.root_identity != self.identity() {
            return Err(state_failure());
        }
        let directory = &self.chain.last().expect("root anchor").file;
        let file = File::from(
            fs::openat(
                directory,
                &fence.name,
                OFlags::RDONLY | OFlags::NOFOLLOW | OFlags::CLOEXEC | OFlags::NONBLOCK,
                Mode::empty(),
            )
            .map_err(|_| state_failure())?,
        );
        platform::require_mode_only_permissions(&file).map_err(|()| state_failure())?;
        let metadata = file.metadata().map_err(|_| state_failure())?;
        mutable_metadata(&metadata, self.uid, fence.maximum_bytes)?;
        if (metadata.dev(), metadata.ino()) != fence.file_identity {
            return Err(state_failure());
        }
        let named = fs::statat(directory, &fence.name, AtFlags::SYMLINK_NOFOLLOW)
            .map_err(|_| state_failure())?;
        if (named.st_dev, named.st_ino) != fence.file_identity {
            return Err(state_failure());
        }
        self.check().map_err(|_| state_failure())
    }

    fn check(&self) -> Result<(), PlatformError> {
        if rustix::process::geteuid().as_raw() != self.uid
            || rustix::process::getegid().as_raw() != self.gid
        {
            return Err(failure());
        }
        for (index, anchor) in self.chain.iter().enumerate() {
            let private = platform::validate_directory(&anchor.file, self.uid, self.gid)
                .map_err(|()| failure())?;
            let metadata = anchor.file.metadata().map_err(|_| failure())?;
            if metadata.nlink() == 0
                || (metadata.dev(), metadata.ino()) != anchor.identity
                || (index + 1 == self.chain.len() && (!private || metadata.mode() & 0o022 != 0))
            {
                return Err(failure());
            }
            if index > 0 {
                let actual = fs::statat(
                    &self.chain[index - 1].file,
                    &anchor.name,
                    AtFlags::SYMLINK_NOFOLLOW,
                )
                .map_err(|_| failure())?;
                if (actual.st_dev, actual.st_ino) != anchor.identity {
                    return Err(failure());
                }
            }
        }
        Ok(())
    }

    /// Read one explicitly configured leaf. This runs on a bounded blocking
    /// control worker, never on an activation or async executor thread.
    pub fn read(
        &self,
        name: &str,
        maximum_bytes: usize,
    ) -> Result<Zeroizing<Vec<u8>>, PlatformError> {
        self.read_with_checkpoint(name, maximum_bytes, || {})
    }

    fn read_with_checkpoint(
        &self,
        name: &str,
        maximum_bytes: usize,
        checkpoint: impl FnOnce(),
    ) -> Result<Zeroizing<Vec<u8>>, PlatformError> {
        if name.is_empty()
            || name.len() > 255
            || name == "."
            || name == ".."
            || !name
                .bytes()
                .all(|b| b.is_ascii_alphanumeric() || b"._-".contains(&b))
            || maximum_bytes == 0
            || maximum_bytes > 1024 * 1024
        {
            return Err(failure());
        }
        self.check()?;
        let directory = &self.chain.last().expect("root anchor").file;
        let mut file = File::from(
            fs::openat(
                directory,
                name,
                OFlags::RDONLY | OFlags::NOFOLLOW | OFlags::CLOEXEC | OFlags::NONBLOCK,
                Mode::empty(),
            )
            .map_err(|_| failure())?,
        );
        platform::require_mode_only_permissions(&file).map_err(|()| failure())?;
        let before = file.metadata().map_err(|_| failure())?;
        platform::validate_file(
            &before,
            ProtectedFilePolicy::Secret,
            self.uid,
            self.gid,
            maximum_bytes as u64,
            true,
        )
        .map_err(|()| failure())?;
        let snapshot = platform::Snapshot::from(&before);
        checkpoint();
        // Allocate once within the advertised bound, including an overflow
        // sentinel. Every error path wipes the initialized secret bytes.
        let mut bytes = Zeroizing::new(vec![
            0;
            usize::try_from(before.len()).map_err(|_| failure())?
                + 1
        ]);
        let mut length = 0;
        while length < bytes.len() {
            let count = file.read(&mut bytes[length..]).map_err(|_| failure())?;
            if count == 0 {
                break;
            }
            length += count;
        }
        if length > maximum_bytes || before.len() != length as u64 {
            return Err(failure());
        }
        self.check()?;
        platform::require_mode_only_permissions(&file).map_err(|()| failure())?;
        let after = file.metadata().map_err(|_| failure())?;
        let named =
            fs::statat(directory, name, AtFlags::SYMLINK_NOFOLLOW).map_err(|_| failure())?;
        if snapshot != platform::Snapshot::from(&after)
            || (named.st_dev, named.st_ino) != (before.dev(), before.ino())
        {
            return Err(failure());
        }
        bytes.truncate(length);
        Ok(bytes)
    }
}

fn valid_leaf(name: &str) -> bool {
    !name.is_empty()
        && name.len() <= 255
        && name != "."
        && name != ".."
        && name
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || b"._-".contains(&byte))
}

fn mutable_metadata(
    metadata: &std::fs::Metadata,
    uid: u32,
    maximum_bytes: u64,
) -> Result<(), PlatformError> {
    if !metadata.is_file()
        || metadata.nlink() != 1
        || metadata.uid() != uid
        || metadata.mode() & 0o7777 != 0o600
        || metadata.len() > maximum_bytes
    {
        return Err(state_failure());
    }
    Ok(())
}

fn state_failure() -> PlatformError {
    PlatformError {
        code: PlatformErrorCode::PermissionDenied,
        message: "protected-state-root".into(),
        retryable: false,
        details: Vec::new(),
    }
}

fn failure() -> PlatformError {
    PlatformError {
        code: PlatformErrorCode::PermissionDenied,
        message: "protected-secret-source".into(),
        retryable: false,
        details: Vec::new(),
    }
}

#[cfg(test)]
mod tests;
