use super::{
    Arc, AtomicBool, AtomicUsize, BlobError, Directory, Entry, Mutex, Path, Phase, ProviderPools,
    Record, Result, S3Config, S3Inventory, State, RECORD_BYTES,
};
use crate::s3::local;

pub(super) fn open(
    path: &Path,
    pools: &ProviderPools,
    config: S3Config,
) -> Result<Arc<S3Inventory>> {
    // Prepay every retained record, sidecar decoder/copy and finite map entry.
    let mut metadata = Vec::with_capacity(config.limits.maximum_records + 1);
    for _ in 0..=config.limits.maximum_records {
        metadata.push(pools.reserve_protocol_metadata(4 * RECORD_BYTES)?);
    }
    let root = Directory::root(path).map_err(local)?;
    let lock = root
        .open_file("LOCK", true, !root.present("LOCK").map_err(local)?, 0)
        .map_err(local)?;
    lock.try_lock().map_err(|_| BlobError::Unavailable)?;
    let names = root.names(3).map_err(local)?;
    if names
        .iter()
        .any(|n| !["LOCK", "OWNER.json", "records"].contains(&n.as_str()))
    {
        return Err(BlobError::ChecksumMismatch);
    }
    let identity = config.identity()?;
    if !root.present("OWNER.json").map_err(local)? {
        if names.iter().any(|n| n != "LOCK") {
            return Err(BlobError::ChecksumMismatch);
        }
        root.write_new("OWNER.json", identity.as_bytes())
            .map_err(local)?;
        root.sync().map_err(local)?;
    }
    if root.small("OWNER.json", 64).map_err(local)? != identity.as_bytes() {
        return Err(BlobError::PermissionDenied);
    }
    let directory = root
        .child("records", !root.present("records").map_err(local)?)
        .map_err(local)?;
    let maximum = config.limits.maximum_records;
    let names = directory.names(maximum * 2).map_err(local)?;
    for name in &names {
        let key = name
            .strip_suffix(".json")
            .or_else(|| name.strip_suffix(".pending"))
            .ok_or(BlobError::ChecksumMismatch)?;
        if !crate::s3::hex(key, 64) {
            return Err(BlobError::ChecksumMismatch);
        }
    }
    for name in names.iter().filter(|n| n.ends_with(".pending")) {
        let bytes = directory.small(name, RECORD_BYTES).map_err(local)?;
        let parsed: std::result::Result<Record, _> = serde_json::from_slice(&bytes);
        match parsed {
            Ok(record) => {
                record.validate(&config)?;
                if name != &format!("{}.pending", record.key()) {
                    return Err(BlobError::ChecksumMismatch);
                }
                directory
                    .replace(name, &format!("{}.json", record.key()), RECORD_BYTES as u64)
                    .map_err(local)?;
            }
            // A torn pending write never crossed its durability fence and could
            // not start the next remote mutation. The previous record survives.
            Err(error) if error.is_eof() => directory.unlink(name, false).map_err(local)?,
            Err(_) => return Err(BlobError::ChecksumMismatch),
        }
        directory.sync().map_err(local)?;
    }
    let mut state = State::default();
    let mut bytes = 0u64;
    for name in directory.names(maximum).map_err(local)? {
        let record: Record =
            serde_json::from_slice(&directory.small(&name, RECORD_BYTES).map_err(local)?)
                .map_err(|_| BlobError::ChecksumMismatch)?;
        record.validate(&config)?;
        if name != format!("{}.json", record.key()) {
            return Err(BlobError::ChecksumMismatch);
        }
        if record.phase == Phase::Aborted && record.quiescent {
            directory.unlink(&name, false).map_err(local)?;
            continue;
        }
        bytes += record.size;
        if bytes > config.limits.maximum_remote_bytes {
            return Err(BlobError::BudgetExhausted);
        }
        state.records.insert(
            record.key(),
            Entry {
                record,
                active: Arc::new(AtomicBool::new(false)),
            },
        );
    }
    directory.sync().map_err(local)?;
    Ok(Arc::new(S3Inventory {
        config,
        directory,
        state: Mutex::new(state),
        poisoned: AtomicBool::new(false),
        stages: AtomicUsize::new(0),
        staging: AtomicUsize::new(0),
        handles: AtomicUsize::new(0),
        _lock: lock,
        _metadata: metadata,
    }))
}
