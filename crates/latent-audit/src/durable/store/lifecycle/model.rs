use super::{codec, corrupt, Result};
use serde::{Deserialize, Serialize};

pub(super) const MAX_ARCHIVES: usize = 4;
pub(super) const MAX_CUSTODY_BYTES: usize = 1024 * 1024 * 1024;

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub(in crate::durable::store) struct EpochLink {
    pub journal_id: String,
    pub custody_id: String,
    pub first_sequence: u64,
    pub previous_epoch: String,
    pub previous_head: String,
    pub previous_seal: String,
    pub operation_id: String,
    pub unknown_outcomes_before: u64,
}
impl EpochLink {
    pub(super) fn validate(&self, epoch: &str) -> Result<()> {
        if self.first_sequence < 2
            || self.previous_epoch == epoch
            || [
                &self.journal_id,
                &self.custody_id,
                &self.previous_epoch,
                &self.operation_id,
            ]
            .iter()
            .any(|v| !codec::hex(v, 32))
            || [&self.previous_head, &self.previous_seal]
                .iter()
                .any(|v| !codec::hex(v, 64))
        {
            return Err(corrupt());
        }
        Ok(())
    }
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub(super) struct Seal {
    pub format_version: u32,
    pub journal_id: String,
    pub epoch: String,
    pub successor_epoch: String,
    pub operation_id: String,
    pub first_sequence: u64,
    pub next_sequence: u64,
    pub records: usize,
    pub record_bytes: usize,
    pub head_digest: String,
    pub mode_digest: String,
    pub head_file_digest: String,
    pub predecessor_seal: String,
    pub unknown_outcomes: u64,
}
impl Seal {
    pub(super) fn validate(&self) -> Result<()> {
        if self.format_version != 1
            || self.records == 0
            || self.records > 16384
            || self.record_bytes > 256 * 1024 * 1024
            || self.first_sequence == 0
            || self.first_sequence.checked_add(self.records as u64) != Some(self.next_sequence)
            || self.epoch == self.successor_epoch
            || [
                &self.journal_id,
                &self.epoch,
                &self.successor_epoch,
                &self.operation_id,
            ]
            .iter()
            .any(|v| !codec::hex(v, 32))
            || [
                &self.head_digest,
                &self.mode_digest,
                &self.head_file_digest,
                &self.predecessor_seal,
            ]
            .iter()
            .any(|v| !codec::hex(v, 64))
        {
            return Err(corrupt());
        }
        Ok(())
    }
    pub(super) fn digest(&self) -> Result<String> {
        self.validate()?;
        Ok(codec::digest(&codec::encode(self, 4096)?))
    }
    pub(super) fn entry(&self) -> Result<ArchiveEntry> {
        Ok(ArchiveEntry {
            epoch: self.epoch.clone(),
            seal: self.digest()?,
            first_sequence: self.first_sequence,
            next_sequence: self.next_sequence,
            record_bytes: self.record_bytes,
        })
    }
    pub(super) fn coverage(&self) -> Result<AuditArchiveCoverage> {
        Ok(AuditArchiveCoverage {
            journal_id: self.journal_id.clone(),
            epoch: self.epoch.clone(),
            successor_epoch: self.successor_epoch.clone(),
            operation_id: self.operation_id.clone(),
            first_sequence: self.first_sequence,
            high_watermark: self.next_sequence - 1,
            records: self.records,
            record_bytes: self.record_bytes,
            head_digest: self.head_digest.clone(),
            seal_digest: self.digest()?,
            predecessor_seal_digest: self.predecessor_seal.clone(),
            unknown_outcomes: self.unknown_outcomes,
            previous_session_loss_unknown: true,
        })
    }
}

/// Verified coverage of exactly one epoch, not a claim of complete observations.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct AuditArchiveCoverage {
    pub journal_id: String,
    pub epoch: String,
    pub successor_epoch: String,
    pub operation_id: String,
    pub first_sequence: u64,
    pub high_watermark: u64,
    pub records: usize,
    pub record_bytes: usize,
    pub head_digest: String,
    pub seal_digest: String,
    pub predecessor_seal_digest: String,
    pub unknown_outcomes: u64,
    pub previous_session_loss_unknown: bool,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct AuditRolloverReceipt {
    pub operation_id: String,
    pub previous_epoch: String,
    pub epoch: String,
    pub next_sequence: u64,
    pub archive_seal: String,
    pub already_completed: bool,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct AuditTransferReceipt {
    pub operation_id: String,
    pub epoch: String,
    pub archive_seal: String,
    pub transferred_through: u64,
    pub destination_digest: String,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub(super) struct ArchiveEntry {
    pub epoch: String,
    pub seal: String,
    pub first_sequence: u64,
    pub next_sequence: u64,
    pub record_bytes: usize,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub(super) struct Custody {
    pub format_version: u32,
    pub journal_id: String,
    pub custody_id: String,
    pub archives: Vec<ArchiveEntry>,
    pub transferred_through: u64,
    pub transferred_head: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub last_transfer: Option<AuditTransferReceipt>,
}
impl Custody {
    pub(super) fn validate(&self) -> Result<()> {
        if self.format_version != 1
            || !codec::hex(&self.journal_id, 32)
            || !codec::hex(&self.custody_id, 32)
            || !codec::hex(&self.transferred_head, 64)
            || self.archives.len() > MAX_ARCHIVES
        {
            return Err(corrupt());
        }
        let mut next = self
            .transferred_through
            .checked_add(1)
            .ok_or_else(corrupt)?;
        let mut bytes = 0usize;
        for (position, entry) in self.archives.iter().enumerate() {
            if !codec::hex(&entry.epoch, 32)
                || !codec::hex(&entry.seal, 64)
                || entry.first_sequence != next
                || entry.next_sequence <= next
                || entry.next_sequence - next > 16384
                || entry.record_bytes > 256 * 1024 * 1024
                || self.archives[..position]
                    .iter()
                    .any(|old| old.epoch == entry.epoch)
            {
                return Err(corrupt());
            }
            next = entry.next_sequence;
            bytes = bytes.checked_add(entry.record_bytes).ok_or_else(corrupt)?;
        }
        if bytes > MAX_CUSTODY_BYTES {
            return Err(corrupt());
        }
        match &self.last_transfer {
            Some(receipt)
                if codec::hex(&receipt.operation_id, 32)
                    && codec::hex(&receipt.epoch, 32)
                    && codec::hex(&receipt.destination_digest, 64)
                    && receipt.archive_seal == self.transferred_head
                    && receipt.transferred_through == self.transferred_through
                    && self.transferred_through > 0 => {}
            None if self.transferred_through == 0 && self.transferred_head == "0".repeat(64) => {}
            _ => return Err(corrupt()),
        }
        Ok(())
    }
    pub(super) fn next_sequence(&self) -> Result<u64> {
        self.archives.last().map_or_else(
            || self.transferred_through.checked_add(1).ok_or_else(corrupt),
            |entry| Ok(entry.next_sequence),
        )
    }
}
