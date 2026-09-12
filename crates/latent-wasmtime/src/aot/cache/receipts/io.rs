use super::{corrupt, failure, invalid, Result};
use latent_core::PlatformErrorCode;
use rustix::fs::{AtFlags, Mode, OFlags};
use std::fs::File;
use std::io::{Read, Write};
use std::path::{Component, Path};

pub(super) const MARKER_NAME: &str = "NATIVE_RECEIPTS";
pub(super) const MARKER_STAGE: &str = "NATIVE_RECEIPTS.next";
pub(super) const LOCK: &str = ".native-receipts.lock";
pub(super) const STAGE: &str = "RECEIPT.next";
pub(super) const MARKER: &[u8] = b"LSF native receipt cache v1\n";

pub(super) fn filesystem(_: impl std::fmt::Debug) -> latent_core::PlatformError {
    failure(
        PlatformErrorCode::Unavailable,
        "native-receipt-cache-filesystem-unavailable",
    )
}

/// Walk one component at a time. Even preexisting ancestor symlinks are rejected.
pub(super) fn root(path: &Path) -> Result<File> {
    if path.as_os_str().len() > 4096 {
        return Err(invalid());
    }
    let absolute = if path.is_absolute() {
        path.to_path_buf()
    } else {
        std::env::current_dir().map_err(filesystem)?.join(path)
    };
    if absolute.as_os_str().len() > 4096
        || absolute
            .components()
            .any(|part| matches!(part, Component::ParentDir))
    {
        return Err(invalid());
    }
    let mut directory =
        File::from(rustix::fs::open("/", directory_flags(), Mode::empty()).map_err(filesystem)?);
    for part in absolute.components() {
        let Component::Normal(name) = part else {
            continue;
        };
        let opened = match rustix::fs::openat(&directory, name, directory_flags(), Mode::empty()) {
            Ok(opened) => opened,
            Err(rustix::io::Errno::NOENT) => {
                rustix::fs::mkdirat(&directory, name, Mode::RUSR | Mode::WUSR | Mode::XUSR)
                    .map_err(filesystem)?;
                directory.sync_all().map_err(filesystem)?;
                rustix::fs::openat(&directory, name, directory_flags(), Mode::empty())
                    .map_err(filesystem)?
            }
            Err(_) => return Err(corrupt()),
        };
        directory = File::from(opened);
    }
    Ok(directory)
}

fn directory_flags() -> OFlags {
    OFlags::RDONLY | OFlags::DIRECTORY | OFlags::NOFOLLOW | OFlags::CLOEXEC
}

pub(super) fn size(root: &File, name: &str) -> Result<Option<u64>> {
    let metadata = match rustix::fs::statat(root, name, AtFlags::SYMLINK_NOFOLLOW) {
        Ok(value) => value,
        Err(rustix::io::Errno::NOENT) => return Ok(None),
        Err(value) => return Err(filesystem(value)),
    };
    if rustix::fs::FileType::from_raw_mode(metadata.st_mode) != rustix::fs::FileType::RegularFile
        || metadata.st_nlink != 1
    {
        return Err(corrupt());
    }
    u64::try_from(metadata.st_size)
        .map(Some)
        .map_err(|_| corrupt())
}

fn opened_regular(file: &File, expected: u64) -> Result<()> {
    use std::os::unix::fs::MetadataExt;
    let metadata = file.metadata().map_err(filesystem)?;
    if !metadata.is_file() || metadata.nlink() != 1 || metadata.len() != expected {
        return Err(corrupt());
    }
    Ok(())
}

pub(super) fn lock(root: &File) -> Result<File> {
    if size(root, LOCK)?.is_some_and(|length| length != 0) {
        return Err(corrupt());
    }
    let file = File::from(
        rustix::fs::openat(
            root,
            LOCK,
            OFlags::RDWR | OFlags::CREATE | OFlags::NOFOLLOW | OFlags::CLOEXEC | OFlags::NONBLOCK,
            Mode::RUSR | Mode::WUSR,
        )
        .map_err(filesystem)?,
    );
    opened_regular(&file, 0)?;
    file.try_lock().map_err(|_| {
        failure(
            PlatformErrorCode::Unavailable,
            "native-receipt-cache-root-owned",
        )
    })?;
    Ok(file)
}

pub(super) fn read(root: &File, name: &str, expected: usize) -> Result<Box<[u8]>> {
    let file = rustix::fs::openat(
        root,
        name,
        OFlags::RDONLY | OFlags::NOFOLLOW | OFlags::CLOEXEC | OFlags::NONBLOCK,
        Mode::empty(),
    )
    .map_err(filesystem)?;
    let mut file = File::from(file);
    opened_regular(&file, expected as u64)?;
    let mut bytes = vec![0; expected].into_boxed_slice();
    file.read_exact(&mut bytes).map_err(|_| corrupt())?;
    if file.read(&mut [0]).map_err(filesystem)? != 0 {
        return Err(corrupt());
    }
    opened_regular(&file, expected as u64)?;
    Ok(bytes)
}

pub(super) fn write(root: &File, name: &str, bytes: &[u8]) -> Result<()> {
    checkpoint(Cutpoint::Create)?;
    let mut file = File::from(
        rustix::fs::openat(
            root,
            name,
            OFlags::WRONLY | OFlags::CREATE | OFlags::EXCL | OFlags::NOFOLLOW | OFlags::CLOEXEC,
            Mode::RUSR | Mode::WUSR,
        )
        .map_err(filesystem)?,
    );
    let halfway = bytes.len() / 2;
    file.write_all(&bytes[..halfway]).map_err(filesystem)?;
    checkpoint(Cutpoint::PartialWrite)?;
    file.write_all(&bytes[halfway..]).map_err(filesystem)?;
    checkpoint(Cutpoint::FileSync)?;
    file.sync_all().map_err(filesystem)
}

pub(super) fn rename(root: &File, from: &str, to: &str) -> Result<()> {
    // Reject preexisting links/unknown file types before replacement.
    size(root, to)?;
    checkpoint(Cutpoint::Rename)?;
    rustix::fs::renameat(root, from, root, to).map_err(filesystem)
}

pub(super) fn remove(root: &File, name: &str) -> Result<()> {
    if size(root, name)?.is_none() {
        return Ok(());
    }
    checkpoint(Cutpoint::Unlink)?;
    rustix::fs::unlinkat(root, name, AtFlags::empty()).map_err(filesystem)
}

pub(super) fn sync(root: &File) -> Result<()> {
    checkpoint(Cutpoint::DirectorySync)?;
    root.sync_all().map_err(filesystem)
}

#[derive(Clone, Copy, PartialEq, Eq)]
pub(super) enum Cutpoint {
    Create,
    PartialWrite,
    FileSync,
    Rename,
    DirectorySync,
    Unlink,
}

#[cfg(test)]
thread_local! { pub(super) static FAIL: std::cell::Cell<Option<Cutpoint>> = const { std::cell::Cell::new(None) }; }

#[cfg_attr(
    not(test),
    expect(
        clippy::unnecessary_wraps,
        reason = "test fault injection requires the same fallible I/O checkpoint signature"
    )
)]
fn checkpoint(point: Cutpoint) -> Result<()> {
    #[cfg(test)]
    if FAIL.with(|value| {
        if value.get() == Some(point) {
            value.set(None);
            true
        } else {
            false
        }
    }) {
        return Err(filesystem("injected"));
    }
    let _ = point;
    Ok(())
}
