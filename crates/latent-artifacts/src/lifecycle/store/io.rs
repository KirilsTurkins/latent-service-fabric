use super::super::{corrupt, exhausted, unavailable};
use latent_core::PlatformError;
use std::{
    fs::{self, File, OpenOptions},
    io::{Read, Write},
    path::{Path, PathBuf},
};

fn regular(metadata: &fs::Metadata) -> bool {
    #[cfg(windows)]
    {
        use std::os::windows::fs::MetadataExt;
        if metadata.file_attributes() & 0x400 != 0 {
            return false;
        }
    }
    !metadata.file_type().is_symlink()
}
pub(super) fn root(path: &Path) -> Result<PathBuf, PlatformError> {
    if !path.is_absolute() {
        return Err(super::super::invalid());
    }
    let parent = path.parent().ok_or_else(corrupt)?;
    let parent = parent.canonicalize().map_err(|_| unavailable())?;
    let name = path.file_name().ok_or_else(corrupt)?;
    let checked = parent.join(name);
    if !checked.exists() {
        fs::create_dir(&checked).map_err(|_| unavailable())?;
        sync(&parent)?;
    }
    directory(&checked)?;
    Ok(checked)
}
pub(super) fn directory(path: &Path) -> Result<(), PlatformError> {
    let metadata = fs::symlink_metadata(path).map_err(|_| corrupt())?;
    if !regular(&metadata) || !metadata.is_dir() {
        return Err(corrupt());
    }
    Ok(())
}
pub(super) fn create_directory(path: &Path) -> Result<(), PlatformError> {
    match fs::create_dir(path) {
        Ok(()) => sync(path.parent().ok_or_else(corrupt)?)?,
        Err(error) if error.kind() == std::io::ErrorKind::AlreadyExists => {}
        Err(_) => return Err(unavailable()),
    }
    directory(path)
}
pub(super) fn sync(path: &Path) -> Result<(), PlatformError> {
    File::open(path)
        .and_then(|file| file.sync_all())
        .map_err(|_| unavailable())
}
pub(super) fn read(path: &Path, maximum: usize) -> Result<Option<Vec<u8>>, PlatformError> {
    let metadata = match fs::symlink_metadata(path) {
        Ok(value) => value,
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => return Ok(None),
        Err(_) => return Err(unavailable()),
    };
    if !regular(&metadata) || !metadata.is_file() {
        return Err(corrupt());
    }
    let size = usize::try_from(metadata.len()).map_err(|_| exhausted())?;
    if size > maximum {
        return Err(exhausted());
    }
    let mut file = File::open(path).map_err(|_| unavailable())?;
    let opened = file.metadata().map_err(|_| unavailable())?;
    if !regular(&opened) || !opened.is_file() || opened.len() != metadata.len() {
        return Err(corrupt());
    }
    let mut bytes = Vec::new();
    bytes.try_reserve_exact(size).map_err(|_| exhausted())?;
    (&mut file)
        .take(maximum as u64 + 1)
        .read_to_end(&mut bytes)
        .map_err(|_| unavailable())?;
    if bytes.len() != size {
        return Err(corrupt());
    }
    Ok(Some(bytes))
}
pub(super) fn required(path: &Path, maximum: usize) -> Result<Vec<u8>, PlatformError> {
    read(path, maximum)?.ok_or_else(corrupt)
}
pub(super) fn write(path: &Path, bytes: &[u8]) -> Result<(), PlatformError> {
    #[cfg(test)]
    WRITES.with(|value| {
        let (count, total) = value.get();
        value.set((count + 1, total + bytes.len()));
    });
    let temporary = path.with_extension("next");
    // A previous bounded write may have stopped before rename. It is never
    // interpreted as authority; only the explicit roll-forward intent is.
    if temporary.exists() {
        remove(&temporary)?;
    }
    let mut file = OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(&temporary)
        .map_err(|_| unavailable())?;
    file.write_all(bytes)
        .and_then(|()| file.sync_all())
        .map_err(|_| unavailable())?;
    drop(file);
    if path.exists() {
        let metadata = fs::symlink_metadata(path).map_err(|_| unavailable())?;
        if !regular(&metadata) || !metadata.is_file() {
            return Err(corrupt());
        }
    }
    fs::rename(&temporary, path).map_err(|_| unavailable())?;
    sync(path.parent().ok_or_else(corrupt)?)
}
#[cfg(test)]
thread_local! {pub(super) static WRITES:std::cell::Cell<(usize,usize)>=const{std::cell::Cell::new((0,0))};}
pub(super) fn remove(path: &Path) -> Result<(), PlatformError> {
    let metadata = fs::symlink_metadata(path).map_err(|_| unavailable())?;
    if !regular(&metadata) || !metadata.is_file() {
        return Err(corrupt());
    }
    fs::remove_file(path).map_err(|_| unavailable())?;
    sync(path.parent().ok_or_else(corrupt)?)
}
pub(super) fn files(path: &Path, maximum: usize) -> Result<Vec<String>, PlatformError> {
    directory(path)?;
    let mut names = Vec::new();
    for entry in fs::read_dir(path).map_err(|_| unavailable())? {
        if names.len() >= maximum {
            return Err(exhausted());
        }
        let entry = entry.map_err(|_| unavailable())?;
        let name = entry.file_name().into_string().map_err(|_| corrupt())?;
        names.push(name);
    }
    names.sort();
    Ok(names)
}
