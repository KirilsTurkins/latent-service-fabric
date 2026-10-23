use super::{archive_limits, codec, corrupt, epoch_state, failure, io, Deadline, Mode, Result, Store};
use super::model::{Custody, Seal};
use super::super::{filename, Head};
use latent_core::{node_metadata::NodeMetadataLease, PlatformErrorCode};
use serde::{de::DeserializeOwned, Serialize};
use std::{fs, path::{Component, Path, PathBuf}};

pub(super) fn canonical<T: DeserializeOwned + Serialize>(path: &Path, maximum: usize) -> Result<T> {
    let bytes = io::read(path, maximum)?;
    let value = codec::decode(&bytes, maximum)?;
    if codec::encode(&value, maximum)? != bytes { return Err(corrupt()); }
    Ok(value)
}

pub(super) fn absolute(path: &Path) -> Result<PathBuf> {
    let value = std::path::absolute(path).map_err(|_| corrupt())?;
    if value.as_os_str().len() > 4096 || value.components().count() > 128
        || value.components().any(|p| !matches!(p, Component::RootDir | Component::Normal(_)))
        || value.to_str().is_none_or(|s| s.chars().any(char::is_control))
    { return Err(corrupt()); }
    Ok(value)
}

pub(super) fn separate(left: &Path, right: &Path) -> Result<()> {
    let left = absolute(left)?;
    let right = absolute(right)?;
    if left.starts_with(&right) || right.starts_with(&left) { return Err(super::super::super::invalid()); }
    Ok(())
}

pub(super) fn existing_root(path: &Path) -> Result<io::Root> {
    io::directory(path)?;
    // Query and maintenance must not initialize a missing history root.
    if !io::present(&path.join(".audit.lock"))? { return Err(corrupt()); }
    io::root(path)
}

pub(super) fn active(root: io::Root, deadline: Deadline) -> Result<(Store, Mode)> {
    let allowed = [".audit.lock", "MODE", "HEAD", "records", "ROLLOVER", "ROLLOVER.next", "TRANSFER", "TRANSFER.next"];
    if io::names(&root.path, allowed.len())?.iter().any(|name| !allowed.contains(&name.as_str())) {
        return Err(failure(PlatformErrorCode::Unavailable, "audit-maintenance-reopen-required"));
    }
    let mode: Mode = canonical(&root.path.join("MODE"), 1024)?;
    let head: Head = canonical(&root.path.join("HEAD"), 1024)?;
    let store = snapshot(root, &mode, head, deadline)?;
    Ok((store, mode))
}

fn snapshot(root: io::Root, mode: &Mode, head: Head, deadline: Deadline) -> Result<Store> {
    let (first_sequence, seed_digest, unknown) = epoch_state(mode)?;
    if !mode.initialized || head.epoch != mode.epoch || head.format_version != 1 {
        return Err(corrupt());
    }
    let mut store = Store { root, head, first_sequence, seed_digest, entries: Vec::new(),
        limits: archive_limits()?, pending: None, unknown, unhealthy: false,
        previous_session_loss_unknown: true, _native: NodeMetadataLease::default() };
    store.scan_with_deadline(Some(deadline.0))?;
    deadline.check()?;
    Ok(store)
}

pub(super) fn archive(path: &Path, deadline: Deadline) -> Result<(Store, Seal)> {
    archive_locked(existing_root(path)?, deadline)
}

fn archive_locked(root: io::Root, deadline: Deadline) -> Result<(Store, Seal)> {
    deadline.check()?;
    let names = io::names(&root.path, 5)?;
    if names != [".audit.lock", "HEAD", "MODE", "SEAL", "records"] { return Err(corrupt()); }
    let seal: Seal = canonical(&root.path.join("SEAL"), 4096)?;
    seal.validate()?;
    let mode_bytes = io::read(&root.path.join("MODE"), 1024)?;
    let head_bytes = io::read(&root.path.join("HEAD"), 1024)?;
    if codec::digest(&mode_bytes) != seal.mode_digest || codec::digest(&head_bytes) != seal.head_file_digest {
        return Err(corrupt());
    }
    let mode: Mode = canonical(&root.path.join("MODE"), 1024)?;
    let head: Head = canonical(&root.path.join("HEAD"), 1024)?;
    let journal = mode.lineage.as_ref().map_or(&mode.epoch, |link| &link.journal_id);
    let predecessor = mode.lineage.as_ref().map_or_else(|| "0".repeat(64), |link| link.previous_seal.clone());
    if seal.journal_id != *journal || seal.epoch != head.epoch || seal.records != head.records
        || seal.record_bytes != head.bytes || seal.next_sequence != head.next_sequence
        || seal.head_digest != head.last_digest || seal.predecessor_seal != predecessor
    { return Err(corrupt()); }
    let store = snapshot(root, &mode, head, deadline)?;
    if store.first_sequence != seal.first_sequence || store.unknown != seal.unknown_outcomes || store.pending.is_some() {
        return Err(corrupt());
    }
    Ok((store, seal))
}

pub(super) fn custody_root(path: &Path, source: &Store, mode: &Mode) -> Result<(io::Root, Custody)> {
    separate(&source.root.path, path)?;
    let root = io::root(path)?;
    let file = root.path.join("CUSTODY");
    if !io::present(&file)? {
        if mode.lineage.is_some() || io::names(&root.path, 2)?.iter().any(|n| !matches!(n.as_str(), ".audit.lock" | "CUSTODY.next")) {
            return Err(failure(PlatformErrorCode::Unavailable, "audit-archive-custody-unavailable"));
        }
        let value = Custody { format_version: 1, journal_id: mode.epoch.clone(), custody_id: io::epoch()?,
            archives: Vec::new(), transferred_through: 0, transferred_head: "0".repeat(64), last_transfer: None };
        io::atomic(&file, &codec::encode(&value, 4096)?)?;
    }
    let value = read_custody(&root)?;
    match &mode.lineage {
        Some(link) if value.journal_id == link.journal_id && value.custody_id == link.custody_id
            && value.next_sequence()? == source.first_sequence
            && value.archives.last().map_or(&value.transferred_head, |entry| &entry.seal) == &link.previous_seal => {}
        None if value.journal_id == mode.epoch && value.archives.is_empty() && value.transferred_through == 0 => {}
        _ => return Err(corrupt()),
    }
    Ok((root, value))
}

pub(super) fn read_custody(root: &io::Root) -> Result<Custody> {
    let value: Custody = canonical(&root.path.join("CUSTODY"), 4096)?;
    value.validate()?;
    Ok(value)
}

pub(super) fn inventory(root: &io::Root, value: &Custody, allow_stage: bool) -> Result<()> {
    for name in io::names(&root.path, 8)? {
        if matches!(name.as_str(), ".audit.lock" | "CUSTODY" | "CUSTODY.next")
            || allow_stage && name == "stage" || value.archives.iter().any(|entry| entry.epoch == name) { continue; }
        return Err(corrupt());
    }
    Ok(())
}

pub(super) fn verify_custody(root: &io::Root, value: &Custody, deadline: Deadline) -> Result<()> {
    inventory(root, value, false)?;
    let mut previous = value.transferred_head.clone();
    let mut successor = None;
    for entry in &value.archives {
        deadline.check()?;
        let (store, seal) = archive(&root.path.join(&entry.epoch), deadline)?;
        if seal.entry()? != *entry || seal.journal_id != value.journal_id || seal.predecessor_seal != previous
            || successor.as_ref().is_some_and(|epoch| epoch != &seal.epoch) { return Err(corrupt()); }
        previous = entry.seal.clone();
        successor = Some(seal.successor_epoch.clone());
        drop(store);
    }
    deadline.check()
}

fn put(path: &Path, bytes: &[u8], maximum: usize) -> Result<()> {
    if io::present(path)? {
        if io::read(path, maximum)? != bytes { return Err(corrupt()); }
    } else { io::atomic(path, bytes)?; }
    io::remove(&path.with_extension("next"), maximum)
}

/// Only incomplete, unsealed staging can be resumed. A sealed archive with a
/// missing or altered file is corruption, never an invitation to repair it.
pub(super) fn copy(source: &Store, seal: &Seal, destination: &Path, deadline: Deadline) -> Result<()> {
    deadline.check()?;
    let root = io::root(destination)?;
    if io::present(&root.path.join("SEAL"))? {
        let (verified, existing) = archive_locked(root, deadline)?;
        if existing != *seal { return Err(corrupt()); }
        drop(verified);
        return Ok(());
    }
    let allowed = [".audit.lock", "MODE", "MODE.next", "HEAD", "HEAD.next", "SEAL.next", "records", "record.next"];
    if io::names(&root.path, allowed.len())?.iter().any(|n| !allowed.contains(&n.as_str())) { return Err(corrupt()); }
    let records = root.path.join("records");
    if !io::present(&records)? { io::create_directory(&records)?; }
    io::directory(&records)?;
    let mode = io::read(&source.root.path.join("MODE"), 1024)?;
    let head = io::read(&source.root.path.join("HEAD"), 1024)?;
    if codec::digest(&mode) != seal.mode_digest || codec::digest(&head) != seal.head_file_digest { return Err(corrupt()); }
    // Validate all retained staging files before writing any new file.
    for name in io::names(&records, source.limits.maximum_records)? {
        deadline.check()?;
        let original = source.root.path.join("records").join(&name);
        if !source.entries.iter().any(|entry| filename(entry.sequence) == name)
            || io::read(&records.join(&name), 16384)? != io::read(&original, 16384)? { return Err(corrupt()); }
    }
    put(&root.path.join("MODE"), &mode, 1024)?;
    put(&root.path.join("HEAD"), &head, 1024)?;
    for entry in &source.entries {
        deadline.check()?;
        let name = filename(entry.sequence);
        let bytes = io::read(&source.root.path.join("records").join(&name), 16384)?;
        if bytes.len() != entry.bytes || codec::digest(&bytes) != entry.digest { return Err(corrupt()); }
        let target = records.join(name);
        if io::present(&target)? {
            if io::read(&target, 16384)? != bytes { return Err(corrupt()); }
        } else {
            io::stage(&root.path.join("record.next"), &bytes)?;
            fs::rename(root.path.join("record.next"), &target).map_err(|_| super::super::super::unavailable())?;
            io::sync(&records)?;
        }
    }
    io::remove(&root.path.join("record.next"), 16384)?;
    put(&root.path.join("SEAL"), &codec::encode(seal, 4096)?, 4096)?;
    io::sync(&records)?;
    io::sync(&root.path)?;
    let (verified, actual) = archive_locked(root, deadline)?;
    if actual != *seal { return Err(corrupt()); }
    drop(verified);
    deadline.check()
}

/// Check every remaining record against the verified copy before deletion.
/// Missing source records are permitted only for the explicit durable transition.
pub(super) fn remaining_records(source: &Path, verified: &Store, deadline: Deadline) -> Result<Vec<String>> {
    let names = io::names(&source.join("records"), 16384)?;
    for name in &names {
        deadline.check()?;
        if !verified.entries.iter().any(|entry| filename(entry.sequence) == *name)
            || io::read(&source.join("records").join(name), 16384)?
                != io::read(&verified.root.path.join("records").join(name), 16384)? { return Err(corrupt()); }
    }
    Ok(names)
}
