use super::{corrupt, error, RawArtifactKey, Result};
use latent_core::PlatformErrorCode;
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use std::fs::{self, File, OpenOptions};
use std::io::{Read, Write};
use std::path::Path;

pub(super) const MARKER: &[u8] = b"LSF raw artifact cache v1\n";
const MAX_RECORD: usize = 256;

#[derive(Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct Record {
    format_version: u8,
    key: String,
    size_bytes: u64,
}

pub(super) fn failure(failure: std::io::Error) -> latent_core::PlatformError {
    let kind = failure.kind();
    drop(failure);
    match kind {
        std::io::ErrorKind::NotFound => {
            error(PlatformErrorCode::NotFound, "raw-cache-file-missing")
        }
        std::io::ErrorKind::UnexpectedEof => corrupt("raw-cache-file-truncated"),
        _ => error(
            PlatformErrorCode::Unavailable,
            "raw-cache-filesystem-unavailable",
        ),
    }
}

/// Presence never follows a link; dangling links are present and unsafe too.
pub(super) fn present(path: &Path) -> Result<bool> {
    match fs::symlink_metadata(path) {
        Ok(_) => Ok(true),
        Err(failure) if failure.kind() == std::io::ErrorKind::NotFound => Ok(false),
        Err(value) => Err(failure(value)),
    }
}

pub(super) fn directory(path: &Path) -> Result<()> {
    let metadata = fs::symlink_metadata(path).map_err(failure)?;
    if !metadata.is_dir() || metadata.file_type().is_symlink() {
        return Err(corrupt("raw-cache-unsafe-directory"));
    }
    Ok(())
}

fn regular(path: &Path, maximum: u64) -> Result<u64> {
    let metadata = fs::symlink_metadata(path).map_err(failure)?;
    if !metadata.is_file() || metadata.file_type().is_symlink() || metadata.len() > maximum {
        return Err(corrupt("raw-cache-unsafe-file"));
    }
    Ok(metadata.len())
}

pub(super) fn names(path: &Path, allowed: &[&str], maximum: usize) -> Result<()> {
    directory(path)?;
    for (index, entry) in fs::read_dir(path).map_err(failure)?.enumerate() {
        if index >= maximum {
            return Err(corrupt("raw-cache-extra-files"));
        }
        let entry = entry.map_err(failure)?;
        let name = entry.file_name();
        if !allowed.iter().any(|value| name == *value) {
            return Err(corrupt("raw-cache-extra-files"));
        }
        if entry.file_type().map_err(failure)?.is_symlink() {
            return Err(corrupt("raw-cache-symlink"));
        }
    }
    Ok(())
}

pub(super) fn small(path: &Path, maximum: usize) -> Result<Vec<u8>> {
    let length = usize::try_from(regular(path, maximum as u64)?)
        .map_err(|_| corrupt("raw-cache-file-size"))?;
    let mut file = File::open(path).map_err(failure)?;
    let metadata = file.metadata().map_err(failure)?;
    if !metadata.is_file() || metadata.len() != length as u64 {
        return Err(corrupt("raw-cache-file-changed"));
    }
    let mut bytes = vec![0; length];
    file.read_exact(&mut bytes).map_err(failure)?;
    if file.read(&mut [0]).map_err(failure)? != 0 {
        return Err(corrupt("raw-cache-file-changed"));
    }
    Ok(bytes)
}

pub(super) fn record(path: &Path, key: &RawArtifactKey, maximum: u64) -> Result<u64> {
    names(path, &["ENTRY.json", "data"], 2)?;
    let record: Record = serde_json::from_slice(&small(&path.join("ENTRY.json"), MAX_RECORD)?)
        .map_err(|_| corrupt("raw-cache-record-invalid"))?;
    if record.format_version != 1 || record.key != key.name() || record.size_bytes > maximum {
        return Err(corrupt("raw-cache-record-invalid"));
    }
    Ok(record.size_bytes)
}

pub(super) fn verify_bytes(key: &RawArtifactKey, bytes: &[u8]) -> Result<()> {
    if format!("sha256:{:x}", Sha256::digest(bytes)) != key.digest() {
        return Err(corrupt("raw-cache-digest-mismatch"));
    }
    Ok(())
}

pub(super) fn read_data(path: &Path, key: &RawArtifactKey, output: &mut [u8]) -> Result<()> {
    if record(path, key, output.len() as u64)? != output.len() as u64 {
        return Err(corrupt("raw-cache-size-mismatch"));
    }
    let data = path.join("data");
    if regular(&data, output.len() as u64)? != output.len() as u64 {
        return Err(corrupt("raw-cache-size-mismatch"));
    }
    let mut file = File::open(data).map_err(failure)?;
    let metadata = file.metadata().map_err(failure)?;
    if !metadata.is_file() || metadata.len() != output.len() as u64 {
        return Err(corrupt("raw-cache-size-mismatch"));
    }
    file.read_exact(output).map_err(failure)?;
    if file.read(&mut [0]).map_err(failure)? != 0 {
        return Err(corrupt("raw-cache-size-mismatch"));
    }
    verify_bytes(key, output)
}

pub(super) fn verify_file(path: &Path, key: &RawArtifactKey, size: u64) -> Result<()> {
    let data = path.join("data");
    if regular(&data, size)? != size {
        return Err(corrupt("raw-cache-size-mismatch"));
    }
    let mut file = File::open(data).map_err(failure)?;
    let metadata = file.metadata().map_err(failure)?;
    if !metadata.is_file() || metadata.len() != size {
        return Err(corrupt("raw-cache-size-mismatch"));
    }
    #[cfg(test)]
    HASH_BYTES.with(|value| value.set(value.get().saturating_add(size)));
    let mut hash = Sha256::new();
    let mut remaining = size;
    let mut scratch = [0u8; 8192];
    while remaining != 0 {
        let count = usize::try_from(remaining.min(scratch.len() as u64)).expect("scratch bound");
        file.read_exact(&mut scratch[..count]).map_err(failure)?;
        hash.update(&scratch[..count]);
        remaining -= count as u64;
    }
    if file.read(&mut [0]).map_err(failure)? != 0
        || format!("sha256:{:x}", hash.finalize()) != key.digest()
    {
        return Err(corrupt("raw-cache-digest-mismatch"));
    }
    Ok(())
}

pub(super) fn payload_size(path: &Path, maximum: u64) -> Result<u64> {
    names(path, &["ENTRY.json", "data"], 2)?;
    let data = path.join("data");
    if present(&data)? {
        regular(&data, maximum)
    } else {
        Ok(0)
    }
}

pub(super) fn sync(path: &Path) -> Result<()> {
    checkpoint(FailPoint::BeforeDirectorySync)?;
    directory(path)?;
    File::open(path)
        .and_then(|file| file.sync_all())
        .map_err(failure)
}

pub(super) fn write(path: &Path, bytes: &[u8]) -> Result<()> {
    let mut file = OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(path)
        .map_err(failure)?;
    file.write_all(bytes).map_err(failure)?;
    file.sync_all().map_err(failure)
}

pub(super) fn publish(root: &Path, key: &RawArtifactKey, bytes: &[u8]) -> Result<()> {
    let stage_root = root.join("staging");
    let objects = root.join("objects");
    directory(&stage_root)?;
    directory(&objects)?;
    let name = key.name();
    let stage = stage_root.join(&name);
    let target = objects.join(&name);
    if present(&target)? {
        return Err(corrupt("raw-cache-unindexed-object"));
    }
    fs::create_dir(&stage).map_err(failure)?;
    let record = serde_json::to_vec(&Record {
        format_version: 1,
        key: name,
        size_bytes: bytes.len() as u64,
    })
    .map_err(|_| corrupt("raw-cache-record-encoding"))?;
    write(&stage.join("ENTRY.json"), &record)?;
    sync(&stage)?;
    write(&stage.join("data"), bytes)?;
    sync(&stage)?;
    checkpoint(FailPoint::BeforePublishRename)?;
    fs::rename(&stage, &target).map_err(failure)?;
    checkpoint(FailPoint::AfterPublishRename)?;
    sync(&objects)?;
    sync(&stage_root)
}

/// Deletes only the two known ordinary files and their now-empty owned directory.
/// Missing/corrupt ordinary cache files are disposable within this canonical
/// owned namespace. Extra files and all symlinks are preserved and reject cleanup.
pub(super) fn remove(path: &Path, key: &RawArtifactKey, maximum: u64) -> Result<()> {
    let Some(parent) = path.parent() else {
        return Err(corrupt("raw-cache-parent-missing"));
    };
    directory(parent)?;
    if path
        .file_name()
        .is_none_or(|name| name != key.name().as_str())
    {
        return Err(corrupt("raw-cache-object-name"));
    }
    if !present(path)? {
        return sync(parent);
    }
    names(path, &["ENTRY.json", "data"], 2)?;
    let descriptor = path.join("ENTRY.json");
    let data = path.join("data");
    // The versioned root, canonical typed namespace and exact ordinary-file
    // inventory establish cache ownership. A corrupt raw record is not authority.
    if present(&descriptor)? {
        regular(&descriptor, MAX_RECORD as u64)?;
    }
    checkpoint(FailPoint::BeforeRemove)?;
    if present(&data)? {
        regular(&data, maximum)?;
        fs::remove_file(&data).map_err(failure)?;
    }
    checkpoint(FailPoint::AfterRemoveData)?;
    if present(&descriptor)? {
        fs::remove_file(descriptor).map_err(failure)?;
    }
    fs::remove_dir(path).map_err(failure)?;
    sync(parent)
}

#[derive(Clone, Copy, PartialEq, Eq)]
pub(super) enum FailPoint {
    BeforePublishRename,
    AfterPublishRename,
    BeforeRemove,
    AfterRemoveData,
    BeforeDirectorySync,
    BeforeRootMarkerRename,
    AfterRootMarkerRename,
}

#[cfg(test)]
thread_local! { static FAILURE: std::cell::Cell<Option<FailPoint>> = const { std::cell::Cell::new(None) }; }
#[cfg(test)]
thread_local! { static HASH_BYTES: std::cell::Cell<u64> = const { std::cell::Cell::new(0) }; }
#[cfg(test)]
pub(super) fn take_hash_bytes() -> u64 {
    HASH_BYTES.with(|value| value.replace(0))
}
#[cfg(test)]
pub(super) fn fail_next(point: FailPoint) {
    FAILURE.with(|value| value.set(Some(point)));
}
#[cfg_attr(not(test), allow(clippy::unnecessary_wraps))]
pub(super) fn checkpoint(point: FailPoint) -> Result<()> {
    #[cfg(test)]
    if FAILURE.with(|value| {
        if value.get() == Some(point) {
            value.set(None);
            true
        } else {
            false
        }
    }) {
        return Err(error(
            PlatformErrorCode::Unavailable,
            "raw-cache-injected-failure",
        ));
    }
    let _ = point;
    Ok(())
}
