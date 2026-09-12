use super::{
    capacity, corrupt, io,
    store::{key, ReceiptCache, State},
    AotReceiptCacheLimits, Result, BASE_METADATA, ENTRY_METADATA,
};
use std::fs::File;
use std::path::Path;
use std::sync::Arc;

pub(super) fn open(path: &Path, limits: AotReceiptCacheLimits) -> Result<Arc<ReceiptCache>> {
    // Include owner bookkeeping and marker staging before creating any directory.
    if limits.maximum_metadata_bytes < BASE_METADATA
        || limits.maximum_disk_bytes < 2 * io::MARKER.len() as u64
        || limits.maximum_recovery_entries < 2
    {
        return Err(capacity());
    }
    let root = io::root(path)?;
    let initial = scan(&root, limits)?;
    if !initial.lock && initial.count >= limits.maximum_recovery_entries {
        return Err(capacity());
    }
    drop(initial);
    let lock = io::lock(&root)?;
    let inventory = scan(&root, limits)?;
    initialize(&root, &inventory, limits)?;
    let mut state = inventory.state;
    state.resident = io::MARKER.len() as u64 + inventory.receipt_bytes;
    // Registered incomplete stages are discarded only after the entire bounded
    // inventory passed validation, with the root owner held.
    if inventory.receipt_stage.is_some() {
        io::remove(&root, io::STAGE)?;
        io::sync(&root)?;
    }
    Ok(ReceiptCache::recovered(root, lock, limits, state))
}

#[derive(Default)]
struct Inventory {
    state: State,
    lock: bool,
    marker: bool,
    marker_stage: Option<u64>,
    receipt_stage: Option<u64>,
    receipt_bytes: u64,
    count: usize,
    bytes: u64,
}

fn scan(root: &File, limits: AotReceiptCacheLimits) -> Result<Inventory> {
    let mut inventory = Inventory::default();
    let directory = rustix::fs::Dir::read_from(root).map_err(io::filesystem)?;
    for entry in directory {
        let entry = entry.map_err(io::filesystem)?;
        let bytes = entry.file_name().to_bytes();
        if bytes == b"." || bytes == b".." {
            continue;
        }
        inventory.count += 1;
        if inventory.count > limits.maximum_recovery_entries {
            return Err(capacity());
        }
        let name = std::str::from_utf8(bytes).map_err(|_| corrupt())?;
        let size = io::size(root, name)?.ok_or_else(corrupt)?;
        inventory.bytes = inventory.bytes.checked_add(size).ok_or_else(capacity)?;
        if inventory.bytes > limits.maximum_disk_bytes {
            return Err(capacity());
        }
        match name {
            io::LOCK if size == 0 => inventory.lock = true,
            io::MARKER_NAME if size == io::MARKER.len() as u64 => inventory.marker = true,
            io::MARKER_STAGE if size <= io::MARKER.len() as u64 => {
                inventory.marker_stage = Some(size);
            }
            io::STAGE if size <= limits.maximum_receipt_bytes as u64 => {
                inventory.receipt_stage = Some(size);
            }
            _ => add_receipt(name, size, &mut inventory, limits)?,
        }
    }
    if !inventory.marker
        && (!inventory.state.entries.is_empty() || inventory.receipt_stage.is_some())
    {
        return Err(corrupt());
    }
    Ok(inventory)
}

fn add_receipt(
    name: &str,
    size: u64,
    inventory: &mut Inventory,
    limits: AotReceiptCacheLimits,
) -> Result<()> {
    let hex = name
        .strip_prefix("r-")
        .and_then(|name| name.strip_suffix(".json"))
        .ok_or_else(corrupt)?;
    if hex.len() != 64 || size == 0 || size > limits.maximum_receipt_bytes as u64 {
        return Err(corrupt());
    }
    let digest = format!("sha256:{hex}").parse().map_err(|_| corrupt())?;
    if inventory.state.entries.len() >= limits.maximum_entries
        || BASE_METADATA + (inventory.state.entries.len() + 1) * ENTRY_METADATA
            > limits.maximum_metadata_bytes
    {
        return Err(capacity());
    }
    inventory.state.insert(key(&digest), size);
    inventory.receipt_bytes += size;
    Ok(())
}

fn initialize(root: &File, inventory: &Inventory, limits: AotReceiptCacheLimits) -> Result<()> {
    if inventory.marker && io::read(root, io::MARKER_NAME, io::MARKER.len())?.as_ref() != io::MARKER
    {
        return Err(corrupt());
    }
    if let Some(size) = inventory.marker_stage {
        let bytes = io::read(
            root,
            io::MARKER_STAGE,
            usize::try_from(size).map_err(|_| corrupt())?,
        )?;
        if !io::MARKER.starts_with(&bytes) {
            return Err(corrupt());
        }
        io::remove(root, io::MARKER_STAGE)?;
        io::sync(root)?;
    }
    if !inventory.marker {
        if inventory.count + usize::from(inventory.marker_stage.is_none())
            > limits.maximum_recovery_entries
            || inventory.bytes + io::MARKER.len() as u64 > limits.maximum_disk_bytes
        {
            return Err(capacity());
        }
        io::write(root, io::MARKER_STAGE, io::MARKER)?;
        io::rename(root, io::MARKER_STAGE, io::MARKER_NAME)?;
    }
    io::sync(root)
}
