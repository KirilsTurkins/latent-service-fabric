use super::super::super::unavailable;
use super::super::codec::corrupt;
use latent_core::PlatformError;
use rustix::fs::{openat, Mode, OFlags, CWD};
use std::{
    fs::{self, DirBuilder, File},
    os::unix::fs::{DirBuilderExt, MetadataExt},
    path::{Component, Path, PathBuf},
};

pub(super) fn root(path: &Path) -> Result<File, PlatformError> {
    let path = std::path::absolute(path).map_err(|_| unavailable())?;
    if path.components().count() > 128 {
        return Err(corrupt());
    }
    let uid = rustix::process::geteuid().as_raw();
    let mut current = PathBuf::new();
    for component in path.components() {
        if !matches!(component, Component::RootDir | Component::Normal(_)) {
            return Err(corrupt());
        }
        current.push(component);
        let metadata = match fs::symlink_metadata(&current) {
            Ok(m) => m,
            Err(e) if e.kind() == std::io::ErrorKind::NotFound => {
                DirBuilder::new()
                    .mode(0o700)
                    .create(&current)
                    .map_err(|_| unavailable())?;
                File::open(current.parent().ok_or_else(corrupt)?)
                    .and_then(|f| f.sync_all())
                    .map_err(|_| unavailable())?;
                fs::symlink_metadata(&current).map_err(|_| unavailable())?
            }
            Err(_) => return Err(corrupt()),
        };
        if !metadata.is_dir()
            || (metadata.uid() != uid && metadata.uid() != 0)
            || (metadata.mode() & 0o022 != 0
                && !(metadata.uid() == 0 && metadata.mode() & 0o1000 != 0))
        {
            return Err(corrupt());
        }
    }
    let root: File = openat(
        CWD,
        &path,
        OFlags::RDONLY | OFlags::DIRECTORY | OFlags::NOFOLLOW | OFlags::CLOEXEC,
        Mode::empty(),
    )
    .map_err(|_| unavailable())?
    .into();
    let m = root.metadata().map_err(|_| unavailable())?;
    if m.mode() & 0o077 != 0 || m.uid() != uid {
        return Err(corrupt());
    }
    Ok(root)
}
pub(super) fn open(root: &File, name: &str, create: bool) -> Result<Option<File>, PlatformError> {
    let mut flags = OFlags::CLOEXEC | OFlags::NOFOLLOW | OFlags::NONBLOCK;
    if create {
        flags |= OFlags::RDWR | OFlags::CREATE;
        if name != ".owner.lock" {
            flags |= OFlags::EXCL;
        }
    } else {
        flags |= OFlags::RDONLY;
    }
    let file: File = match openat(root, name, flags, Mode::from_raw_mode(0o600)) {
        Ok(fd) => fd.into(),
        Err(rustix::io::Errno::NOENT) if !create => return Ok(None),
        Err(_) => return Err(corrupt()),
    };
    let m = file.metadata().map_err(|_| unavailable())?;
    if !m.is_file()
        || m.nlink() != 1
        || m.uid() != rustix::process::geteuid().as_raw()
        || m.mode() & 0o077 != 0
    {
        return Err(corrupt());
    }
    Ok(Some(file))
}
pub(super) fn remove(root: &File, name: &str) -> Result<(), PlatformError> {
    if open(root, name, false)?.is_some() {
        rustix::fs::unlinkat(root, name, rustix::fs::AtFlags::empty())
            .map_err(|_| unavailable())?;
        root.sync_all().map_err(|_| unavailable())?;
    }
    Ok(())
}
pub(super) fn unchanged(before: &fs::Metadata, after: &fs::Metadata) -> Result<(), PlatformError> {
    if before.len() != after.len()
        || before.mode() != after.mode()
        || before.uid() != after.uid()
        || before.gid() != after.gid()
        || after.nlink() != 1
        || before.mtime() != after.mtime()
        || before.mtime_nsec() != after.mtime_nsec()
        || before.ctime() != after.ctime()
        || before.ctime_nsec() != after.ctime_nsec()
    {
        return Err(corrupt());
    }
    Ok(())
}
pub(super) fn rename(root: &File, from: &str, to: &str) -> Result<(), PlatformError> {
    open(root, from, false)?.ok_or_else(corrupt)?;
    open(root, to, false)?;
    rustix::fs::renameat(root, from, root, to).map_err(|_| unavailable())
}
