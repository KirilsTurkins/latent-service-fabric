use cap_fs_ext::{DirExt, FollowSymlinks, OpenOptionsFollowExt, OpenOptionsSyncExt};
use cap_std::fs::{Dir, OpenOptions};
use latent_artifacts::package::{validate_package_path, PackageLimits};
use latent_core::PlatformError;
use std::io::{Read, Write};

use super::io_error;

pub(super) fn parent(
    root: &Dir,
    path: &str,
    limits: PackageLimits,
    create: bool,
) -> Result<(Dir, String), PlatformError> {
    validate_package_path(path, limits)?;
    let mut parts = path.split('/').peekable();
    let mut current = root.try_clone().map_err(io_error)?;
    while let Some(part) = parts.next() {
        if parts.peek().is_none() {
            return Ok((current, part.to_owned()));
        }
        if create {
            match current.create_dir(part) {
                Ok(()) => (),
                Err(error) if error.kind() == std::io::ErrorKind::AlreadyExists => (),
                Err(error) => return Err(io_error(error)),
            }
        }
        current = current.open_dir_nofollow(part).map_err(io_error)?;
    }
    Err(crate::invalid("invalid-package-path"))
}

pub(super) fn read(
    root: &Dir,
    path: &str,
    maximum: u64,
    limits: PackageLimits,
) -> Result<Vec<u8>, PlatformError> {
    let (parent, name) = parent(root, path, limits, false)?;
    let mut options = OpenOptions::new();
    options.read(true).follow(FollowSymlinks::No).nonblock(true);
    let mut file = parent.open_with(name, &options).map_err(io_error)?;
    let before = file.metadata().map_err(io_error)?;
    if !before.is_file() {
        return Err(crate::invalid("package-input-not-regular"));
    }
    if before.len() > maximum {
        return Err(crate::exceeded("package-file-byte-limit"));
    }
    let capacity =
        usize::try_from(before.len()).map_err(|_| crate::exceeded("package-file-byte-limit"))?;
    let mut bytes = Vec::new();
    bytes
        .try_reserve_exact(capacity)
        .map_err(|_| crate::exceeded("package-file-allocation-limit"))?;
    let mut buffer = [0_u8; 8192];
    loop {
        let count = file.read(&mut buffer).map_err(io_error)?;
        if count == 0 {
            break;
        }
        let next = bytes
            .len()
            .checked_add(count)
            .filter(|size| *size as u64 <= before.len())
            .ok_or_else(|| crate::invalid("package-input-changed-during-read"))?;
        if next > capacity {
            return Err(crate::invalid("package-input-changed-during-read"));
        }
        bytes.extend_from_slice(&buffer[..count]);
    }
    let after = file.metadata().map_err(io_error)?;
    if bytes.len() as u64 != before.len()
        || after.len() != before.len()
        || before.modified().ok() != after.modified().ok()
    {
        return Err(crate::invalid("package-input-changed-during-read"));
    }
    Ok(bytes)
}

pub(super) fn write(
    root: &Dir,
    path: &str,
    bytes: &[u8],
    limits: PackageLimits,
) -> Result<(), PlatformError> {
    let (parent, name) = parent(root, path, limits, true)?;
    let mut options = OpenOptions::new();
    options
        .write(true)
        .create_new(true)
        .follow(FollowSymlinks::No);
    let mut file = parent.open_with(name, &options).map_err(io_error)?;
    file.write_all(bytes).map_err(io_error)?;
    file.sync_all().map_err(io_error)
}
