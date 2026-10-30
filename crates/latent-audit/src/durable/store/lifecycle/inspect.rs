use super::{
    codec, corrupt, guard_open, io, storage, AuditArchiveCoverage, AuditMaintenance, Deadline,
    Result,
};
use std::{path::Path, time::Duration};

/// A verified observation of the active epoch under exclusive filesystem
/// ownership. It reserves no capacity for a later operation.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct AuditJournalStatus {
    pub journal_id: String,
    pub epoch: String,
    pub retained_floor: u64,
    pub high_watermark: u64,
    pub next_sequence: u64,
    pub head_digest: String,
    pub retained_records: usize,
    pub retained_bytes: usize,
    pub pending_attempts: usize,
    pub unknown_outcomes: u64,
    pub previous_epoch: Option<String>,
    pub previous_seal: Option<String>,
}

/// Finite locally retained suffix. Transferred history is explicitly outside
/// this verified coverage; the operator's external custody remains independent.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct AuditCustodyStatus {
    pub journal_id: String,
    pub custody_id: String,
    pub archives: Vec<AuditArchiveCoverage>,
    pub transferred_through: u64,
    pub transferred_head: String,
}

impl AuditMaintenance {
    /// Inspect an existing stopped journal without initializing or rewriting it.
    /// An interrupted transition requires its original command, not a new plan.
    pub fn status(journal: &Path, timeout: Duration) -> Result<AuditJournalStatus> {
        let deadline = Deadline::new(timeout)?;
        deadline.check()?;
        let root = storage::existing_root(journal)?;
        guard_open(&root)?;
        let (store, mode) = storage::active(root, deadline)?;
        let status = AuditJournalStatus {
            journal_id: mode
                .lineage
                .as_ref()
                .map_or_else(|| mode.epoch.clone(), |link| link.journal_id.clone()),
            epoch: mode.epoch,
            retained_floor: store.first_sequence,
            high_watermark: store.head.next_sequence - 1,
            next_sequence: store.head.next_sequence,
            head_digest: store.head.last_digest.clone(),
            retained_records: store.head.records,
            retained_bytes: store.head.bytes,
            pending_attempts: usize::from(store.pending.is_some()),
            unknown_outcomes: store.unknown,
            previous_epoch: mode
                .lineage
                .as_ref()
                .map(|link| link.previous_epoch.clone()),
            previous_seal: mode.lineage.as_ref().map(|link| link.previous_seal.clone()),
        };
        deadline.check()?;
        Ok(status)
    }

    /// Verify and list at most four local archives for one explicitly selected
    /// journal. Neither an unavailable archive nor transferred history is
    /// silently counted as complete coverage.
    pub fn custody_status(
        archives: &Path,
        expected_journal_id: &str,
        timeout: Duration,
    ) -> Result<AuditCustodyStatus> {
        let deadline = Deadline::new(timeout)?;
        if !codec::hex(expected_journal_id, 32) {
            return Err(super::super::super::invalid());
        }
        deadline.check()?;
        let root = storage::existing_root(archives)?;
        let custody = storage::read_custody(&root)?;
        if custody.journal_id != expected_journal_id {
            return Err(corrupt());
        }
        storage::verify_custody(&root, &custody, deadline)?;
        let mut selected = Vec::with_capacity(custody.archives.len());
        for entry in &custody.archives {
            deadline.check()?;
            let seal: super::model::Seal =
                storage::canonical(&root.path.join(&entry.epoch).join("SEAL"), 4096)?;
            if seal.entry()? != *entry {
                return Err(corrupt());
            }
            selected.push(seal.coverage()?);
        }
        // Keep the real custody lock until every selected descriptor is read.
        io::directory(&root.path)?;
        deadline.check()?;
        Ok(AuditCustodyStatus {
            journal_id: custody.journal_id,
            custody_id: custody.custody_id,
            archives: selected,
            transferred_through: custody.transferred_through,
            transferred_head: custody.transferred_head,
        })
    }
}
