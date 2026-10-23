use super::{codec, corrupt, cut, failure, io, storage, Deadline, Mode, Result, Store};
use super::model::{AuditTransferReceipt, ArchiveEntry, Custody};
use latent_core::PlatformErrorCode;
use serde::{Deserialize, Serialize};
use std::{fs, path::Path};

#[derive(Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct Transfer {
    format_version: u32,
    destination: String,
    active_head: String,
    active_mode: String,
    old_custody: Custody,
    new_custody: Custody,
    archive: ArchiveEntry,
}
impl Transfer {
    fn receipt(&self) -> Result<&AuditTransferReceipt> { self.new_custody.last_transfer.as_ref().ok_or_else(corrupt) }
    fn validate(&self) -> Result<()> {
        self.old_custody.validate()?;
        self.new_custody.validate()?;
        let receipt = self.receipt()?;
        let mut expected = self.old_custody.clone();
        if expected.archives.first() != Some(&self.archive) { return Err(corrupt()); }
        expected.archives.remove(0);
        expected.transferred_through = self.archive.next_sequence - 1;
        expected.transferred_head.clone_from(&self.archive.seal);
        expected.last_transfer = Some(receipt.clone());
        if self.format_version != 1 || expected != self.new_custody
            || receipt.epoch != self.archive.epoch || receipt.archive_seal != self.archive.seal
            || !codec::hex(&self.active_head, 64) || !codec::hex(&self.active_mode, 64)
            || receipt.destination_digest != codec::digest(self.destination.as_bytes())
        { return Err(corrupt()); }
        storage::absolute(Path::new(&self.destination))?;
        Ok(())
    }
    fn matches(&self, epoch: &str, seal: &str, operation: &str, destination: &Path) -> Result<()> {
        let receipt = self.receipt()?;
        if receipt.epoch != epoch || receipt.archive_seal != seal || receipt.operation_id != operation
            || storage::absolute(destination)?.to_str() != Some(self.destination.as_str()) {
            return Err(failure(PlatformErrorCode::StateConflict, "audit-maintenance-identity-mismatch"));
        }
        Ok(())
    }
}

#[expect(clippy::too_many_arguments, reason = "Every exact original operation selector is required for stopped-owner recovery")]
pub(super) fn run(journal: &Path, custody: &Path, destination: &Path, epoch: &str, seal_digest: &str, operation: &str, deadline: Deadline) -> Result<AuditTransferReceipt> {
    deadline.check()?;
    storage::separate(journal, custody)?;
    storage::separate(journal, destination)?;
    storage::separate(custody, destination)?;
    let root = storage::existing_root(journal)?;
    if io::present(&root.path.join("ROLLOVER"))? { return Err(failure(PlatformErrorCode::Unavailable, "audit-maintenance-resume-required")); }
    let marker = root.path.join("TRANSFER");
    if io::present(&marker)? {
        let transfer: Transfer = storage::canonical(&marker, 16384)?;
        transfer.validate()?;
        transfer.matches(epoch, seal_digest, operation, destination)?;
        let (active, mode) = storage::active(root, deadline)?;
        if codec::digest(&codec::encode(&active.head, 1024)?) != transfer.active_head
            || codec::digest(&codec::encode(&mode, 1024)?) != transfer.active_mode { return Err(corrupt()); }
        return finish(&active, storage::existing_root(custody)?, transfer, deadline);
    }
    let (active, mode) = storage::active(root, deadline)?;
    if active.pending.is_some() { return Err(failure(PlatformErrorCode::ResourceExhausted, "audit-critical-pending")); }
    let (custody, old_custody) = storage::custody_root(custody, &active, &mode)?;
    let destination = storage::absolute(destination)?;
    let destination_text = destination.to_str().ok_or_else(corrupt)?;
    let destination_digest = codec::digest(destination_text.as_bytes());
    if let Some(receipt) = &old_custody.last_transfer {
        if receipt.operation_id == operation {
            if receipt.epoch != epoch || receipt.archive_seal != seal_digest || receipt.destination_digest != destination_digest {
                return Err(failure(PlatformErrorCode::StateConflict, "audit-maintenance-identity-mismatch"));
            }
            return Ok(receipt.clone());
        }
    }
    storage::verify_custody(&custody, &old_custody, deadline)?;
    let entry = old_custody.archives.first().filter(|entry| entry.epoch == epoch && entry.seal == seal_digest)
        .ok_or_else(|| failure(PlatformErrorCode::StateConflict, "audit-oldest-archive-required"))?.clone();
    let (archive, seal) = storage::archive(&custody.path.join(epoch), deadline)?;
    storage::copy(&archive, &seal, &destination, deadline)?;
    drop(archive);
    let mut new_custody = old_custody.clone();
    new_custody.archives.remove(0);
    new_custody.transferred_through = entry.next_sequence - 1;
    new_custody.transferred_head.clone_from(&entry.seal);
    new_custody.last_transfer = Some(AuditTransferReceipt { operation_id: operation.into(), epoch: epoch.into(),
        archive_seal: seal_digest.into(), transferred_through: entry.next_sequence - 1, destination_digest });
    let transfer = Transfer { format_version: 1, destination: destination_text.into(),
        active_head: codec::digest(&codec::encode(&active.head, 1024)?),
        active_mode: codec::digest(&codec::encode(&mode, 1024)?), old_custody, new_custody, archive: entry };
    transfer.validate()?;
    deadline.check()?;
    io::atomic(&marker, &codec::encode(&transfer, 16384)?)?;
    cut(20)?;
    finish(&active, custody, transfer, deadline)
}

fn validate_source(path: &Path, target: &Store, deadline: Deadline) -> Result<Vec<String>> {
    let allowed = [".audit.lock", "HEAD", "MODE", "SEAL", "records"];
    if io::names(path, allowed.len())?.iter().any(|n| !allowed.contains(&n.as_str())) { return Err(corrupt()); }
    for (name, maximum) in [("HEAD", 1024), ("MODE", 1024), ("SEAL", 4096)] {
        if io::present(&path.join(name))?
            && io::read(&path.join(name), maximum)? != io::read(&target.root.path.join(name), maximum)? { return Err(corrupt()); }
    }
    if io::present(&path.join("records"))? { storage::remaining_records(path, target, deadline) }
    else { Ok(Vec::new()) }
}

fn remove_source(path: &Path, target: &Store, deadline: Deadline) -> Result<()> {
    if !io::present(path)? { return Ok(()); }
    // Custody and active locks remain held. Recreating a zero-byte lock after a
    // crash in the final cleanup step cannot admit a second maintenance writer.
    let root = io::root(path)?;
    let names = validate_source(&root.path, target, deadline)?;
    for name in names {
        deadline.check()?;
        io::remove(&root.path.join("records").join(name), 16384)?;
        cut(22)?;
    }
    if io::present(&root.path.join("records"))? {
        io::directory(&root.path.join("records"))?;
        fs::remove_dir(root.path.join("records")).map_err(|_| super::super::super::unavailable())?;
        io::sync(&root.path)?;
    }
    for (name, maximum) in [("HEAD", 1024), ("MODE", 1024), ("SEAL", 4096)] {
        deadline.check()?;
        io::remove(&root.path.join(name), maximum)?;
    }
    cut(23)?;
    io::remove(&root.path.join(".audit.lock"), 0)?;
    fs::remove_dir(&root.path).map_err(|_| super::super::super::unavailable())?;
    io::sync(root.path.parent().ok_or_else(corrupt)?)?;
    cut(24)?;
    Ok(())
}

fn finish(active: &Store, custody: io::Root, transfer: Transfer, deadline: Deadline) -> Result<AuditTransferReceipt> {
    transfer.validate()?;
    let current = storage::read_custody(&custody)?;
    if current != transfer.old_custody && current != transfer.new_custody { return Err(corrupt()); }
    storage::inventory(&custody, &transfer.old_custody, false)?;
    storage::verify_retained(&custody, &transfer.new_custody, deadline)?;
    // A retained proof alone is not permission to delete a local copy when the
    // actual transfer target is unavailable. Reverify it on every resume.
    let (target, seal) = storage::archive(Path::new(&transfer.destination), deadline)?;
    if seal.entry()? != transfer.archive || seal.journal_id != transfer.old_custody.journal_id { return Err(corrupt()); }
    let source = custody.path.join(&transfer.archive.epoch);
    if io::present(&source)? { validate_source(&source, &target, deadline)?; }
    deadline.check()?;
    io::atomic(&custody.path.join("CUSTODY"), &codec::encode(&transfer.new_custody, 4096)?)?;
    cut(21)?;
    remove_source(&source, &target, deadline)?;
    deadline.check()?;
    cut(25)?;
    io::remove(&active.root.path.join("TRANSFER.next"), 16384)?;
    io::remove(&active.root.path.join("TRANSFER"), 16384)?;
    cut(26)?;
    Ok(transfer.receipt()?.clone())
}
