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
