use super::{
    capacity, corrupt, error, io, ownership::Memory, Entry, OwnerLock, RawArtifactCache,
    RawArtifactCacheLimits, RawArtifactKey, Result, State, ENTRY_METADATA, HANDLE_METADATA,
    OWNER_METADATA,
};
use latent_core::PlatformErrorCode;
use std::fs::{self, OpenOptions};
use std::path::{Path, PathBuf};
use std::sync::{Arc, Mutex};

pub(super) fn open(path: PathBuf, limits: RawArtifactCacheLimits) -> Result<Arc<RawArtifactCache>> {
    #[cfg(not(unix))]
    {
        let _ = (path, limits);
        Err(error(
            PlatformErrorCode::IncompatibleContract,
            "raw-cache-platform-unsupported",
        ))
    }
    #[cfg(unix)]
    open_unix(path, limits)
}

#[cfg(unix)]
fn open_unix(path: PathBuf, limits: RawArtifactCacheLimits) -> Result<Arc<RawArtifactCache>> {
    let absolute = bounded_root(path, 4096)?;
    fs::create_dir_all(&absolute).map_err(io::failure)?;
    let mut root = fs::canonicalize(absolute).map_err(io::failure)?;
    if root.as_os_str().len() > 4096 {
        return Err(super::invalid("raw-cache-root-path-limit"));
    }
    root.shrink_to_fit();
    io::names(
        &root,
        &[
            "RAW_CACHE",
            "RAW_CACHE.next",
            ".raw-cache.lock",
            "objects",
            "staging",
        ],
        5,
    )?;
    let lock_path = root.join(".raw-cache.lock");
    if io::present(&lock_path)?
        && !fs::symlink_metadata(&lock_path)
            .map_err(io::failure)?
            .is_file()
    {
        return Err(corrupt("raw-cache-owner-file-invalid"));
    }
    let lock = OpenOptions::new()
        .read(true)
        .write(true)
        .create(true)
        .truncate(false)
        .open(lock_path)
        .map_err(io::failure)?;
    lock.try_lock()
        .map_err(|_| error(PlatformErrorCode::Unavailable, "raw-cache-root-owned"))?;
    let lock = OwnerLock(lock);
    initialize(&root)?;
    // Preserve the same durable-root reachability boundary as local catalogs.
    for ancestor in root.ancestors() {
        io::sync(ancestor)?;
    }
    let mut state = State {
        owner_metadata: OWNER_METADATA
            + (limits.maximum_reads + limits.maximum_work) * HANDLE_METADATA,
        ..State::default()
    };
    let mut scan = Scan::default();
    recover_objects(&root, &mut state, limits, &mut scan)?;
    recover_staging(&root, limits, &mut scan)?;
    Ok(Arc::new(RawArtifactCache {
        root,
        limits,
        state: Mutex::new(state),
        memory: Arc::new(Memory::new(limits.maximum_read_bytes, limits.maximum_reads)),
        _lock: lock,
    }))
}

/// Resolve the existing ancestor before creating any missing leaf. This charges
/// symlink expansion as well as the caller's spelling against the path ceiling.
#[cfg(unix)]
pub(super) fn bounded_root(path: PathBuf, maximum: usize) -> Result<PathBuf> {
    let absolute = if path.is_absolute() {
        path
    } else {
        std::env::current_dir().map_err(io::failure)?.join(path)
    };
    if absolute.as_os_str().len() > maximum
        || absolute
            .components()
            .any(|part| matches!(part, std::path::Component::ParentDir))
    {
        return Err(super::invalid("raw-cache-root-path-limit"));
    }
    let mut existing = absolute.as_path();
    while !io::present(existing)? {
        existing = existing
            .parent()
            .ok_or_else(|| super::invalid("raw-cache-root-path-limit"))?;
    }
    if existing == absolute {
        io::directory(existing)?;
    }
    let ancestor = fs::canonicalize(existing).map_err(io::failure)?;
    io::directory(&ancestor)?;
    let suffix = absolute
        .strip_prefix(existing)
        .map_err(|_| super::invalid("raw-cache-root-path-limit"))?;
    let mut resolved = ancestor.join(suffix);
    if resolved.as_os_str().len() > maximum {
        return Err(super::invalid("raw-cache-root-path-limit"));
    }
    resolved.shrink_to_fit();
    Ok(resolved)
}

#[derive(Default)]
struct Scan {
    entries: usize,
    payload_bytes: u64,
}
impl Scan {
    fn charge(&mut self, path: &Path, limits: RawArtifactCacheLimits) -> Result<u64> {
        self.entries = self.entries.checked_add(1).ok_or_else(capacity)?;
        if self.entries > limits.maximum_recovery_entries {
            return Err(capacity());
        }
        let bytes = io::payload_size(path, limits.maximum_object_bytes)?;
        self.payload_bytes = self.payload_bytes.checked_add(bytes).ok_or_else(capacity)?;
        if self.payload_bytes > limits.maximum_disk_bytes {
            return Err(capacity());
        }
        Ok(bytes)
    }
}

#[cfg(unix)]
fn initialize(root: &Path) -> Result<()> {
    let marker = root.join("RAW_CACHE");
    let initialized = io::present(&marker)?;
    if initialized && io::small(&marker, io::MARKER.len())? != io::MARKER {
        return Err(corrupt("raw-cache-root-marker"));
    }
    for name in ["objects", "staging"] {
        let path = root.join(name);
        if io::present(&path)? {
            io::directory(&path)?;
            if !initialized && fs::read_dir(&path).map_err(io::failure)?.next().is_some() {
                return Err(corrupt("raw-cache-root-uninitialized"));
            }
        } else {
            fs::create_dir(&path).map_err(io::failure)?;
        }
        io::sync(&path)?;
    }
    let next = root.join("RAW_CACHE.next");
    if io::present(&next)? {
        // A bounded partial marker is an owned interrupted atomic initialization.
        let _ = io::small(&next, io::MARKER.len())?;
        fs::remove_file(&next).map_err(io::failure)?;
    }
    if !initialized {
        io::write(&next, io::MARKER)?;
        io::checkpoint(io::FailPoint::BeforeRootMarkerRename)?;
        fs::rename(&next, &marker).map_err(io::failure)?;
        io::checkpoint(io::FailPoint::AfterRootMarkerRename)?;
    }
    io::sync(root)
}

#[cfg(unix)]
fn recover_objects(
    root: &Path,
    state: &mut State,
    limits: RawArtifactCacheLimits,
    scan: &mut Scan,
) -> Result<()> {
    let objects = root.join("objects");
    for entry in fs::read_dir(&objects).map_err(io::failure)? {
        let entry = entry.map_err(io::failure)?;
        let name = entry.file_name();
        let key = RawArtifactKey::from_name(
            name.to_str()
                .ok_or_else(|| corrupt("raw-cache-object-name"))?,
        )?;
        io::directory(&entry.path())?;
        scan.charge(&entry.path(), limits)?;
        // An empty owned directory is a possible cut after deleting ENTRY.json.
        if fs::read_dir(entry.path())
            .map_err(io::failure)?
            .next()
            .is_none()
        {
            io::remove(&entry.path(), &key, limits.maximum_object_bytes)?;
            continue;
        }
        let checked =
            io::record(&entry.path(), &key, limits.maximum_object_bytes).and_then(|size| {
                if state.entries.len() >= limits.maximum_entries
                    || state
                        .resident
                        .checked_add(size)
                        .is_none_or(|bytes| bytes > limits.maximum_disk_bytes)
                    || state
                        .metadata_bytes()?
                        .checked_add(ENTRY_METADATA)
                        .is_none_or(|bytes| bytes > limits.maximum_metadata_bytes)
                {
                    return Err(capacity());
                }
                io::verify_file(&entry.path(), &key, size).map(|()| size)
            });
        let size = match checked {
            Ok(size) => size,
            Err(failure)
                if matches!(
                    failure.code,
                    PlatformErrorCode::NotFound | PlatformErrorCode::CorruptArtifact
                ) =>
            {
                io::remove(&entry.path(), &key, limits.maximum_object_bytes)?;
                state.corruptions = state.corruptions.saturating_add(1);
                continue;
            }
            Err(failure) => return Err(failure),
        };
        state.resident += size;
        state.entries.insert(
            key,
            Entry {
                size,
                incarnation: 0,
                recency: 0,
                pins: 0,
                valid: true,
                deleting: false,
            },
        );
    }
    // The retained BTreeMap provides a deterministic digest-order restart seed.
    for (key, entry) in &mut state.entries {
        state.sequence += 1;
        entry.incarnation = state.sequence;
        entry.recency = state.sequence;
        state.recency.insert((state.sequence, key.clone()));
    }
    Ok(())
}

#[cfg(unix)]
fn recover_staging(root: &Path, limits: RawArtifactCacheLimits, scan: &mut Scan) -> Result<()> {
    let mut staged = 0;
    let mut bytes = 0u64;
    for entry in fs::read_dir(root.join("staging")).map_err(io::failure)? {
        staged += 1;
        if staged > limits.maximum_staging_entries {
            return Err(capacity());
        }
        let entry = entry.map_err(io::failure)?;
        let name = entry.file_name();
        let key = RawArtifactKey::from_name(
            name.to_str()
                .ok_or_else(|| corrupt("raw-cache-object-name"))?,
        )?;
        io::directory(&entry.path())?;
        bytes = bytes
            .checked_add(scan.charge(&entry.path(), limits)?)
            .ok_or_else(capacity)?;
        if bytes > limits.maximum_staging_bytes {
            return Err(capacity());
        }
        if io::present(&entry.path().join("ENTRY.json"))? {
            match io::record(&entry.path(), &key, limits.maximum_object_bytes) {
                Ok(_) => (),
                Err(failure)
                    if matches!(
                        failure.code,
                        PlatformErrorCode::NotFound | PlatformErrorCode::CorruptArtifact
                    ) => {}
                Err(failure) => return Err(failure),
            }
        }
        io::remove(&entry.path(), &key, limits.maximum_object_bytes)?;
    }
    Ok(())
}
