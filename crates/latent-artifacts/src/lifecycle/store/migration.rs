//! The v1 reader is restricted to a root-owned offline migration.

use super::*;
use sha2::{Digest, Sha256};

pub(crate) struct LegacyLifecycleSnapshot {
    root: PathBuf,
    limits: LifecycleLimits,
    state: State,
    order: Vec<PublicationId>,
    mode: persistence::Mode,
    fingerprint: [u8; 32],
}

impl LegacyLifecycleSnapshot {
    /// Test fixture encoder for the frozen v1 MODE/HEAD/receipt layout. Rows and
    /// COMPLETE bytes are unchanged; production has no downgrade operation.
    #[cfg(all(test, unix))]
    pub(crate) fn write_legacy_fixture(
        root: &Path,
        limits: LifecycleLimits,
    ) -> Result<(), PlatformError> {
        let mut mode: persistence::Mode = decode(&io::required(&root.join("MODE"), 4096)?, 4096)?;
        if mode.format_version != 2 || mode.baseline_count != 0 {
            return Err(corrupt());
        }
        mode.format_version = 1;
        mode.baseline_digest = digest(b"lsf-lifecycle-baseline-v1\0");
        let mode_bytes = encode(&mode, 4096)?;
        std::fs::write(root.join("MODE"), &mode_bytes).map_err(|_| corrupt())?;
        std::fs::write(root.join("INITIALIZED"), encode(&digest(&mode_bytes), 128)?)
            .map_err(|_| corrupt())?;
        let mut head: Head = decode(&io::required(&root.join("HEAD"), 4096)?, 4096)?;
        head.format_version = 1;
        head.mode = digest(&mode_bytes);
        for name in io::files(&root.join("records"), limits.max_records)? {
            let path = root.join("records").join(name);
            let row: StoredRow = decode(
                &io::required(&path, limits.max_record_bytes)?,
                limits.max_record_bytes,
            )?;
            let legacy = root
                .join("records")
                .join(format!("{}.json", &row.identity.release.0[7..]));
            if legacy.exists() {
                return Err(corrupt());
            }
            std::fs::rename(&path, &legacy).map_err(|_| corrupt())?;
        }
        for name in io::files(&root.join("receipts"), limits.max_recent_operations)? {
            let path = root.join("receipts").join(name);
            let mut receipt: StoredReceipt = decode(
                &io::required(&path, limits.max_receipt_bytes + 256)?,
                limits.max_receipt_bytes + 256,
            )?;
            receipt.publication = None;
            let bytes = encode(&receipt, limits.max_receipt_bytes + 256)?;
            if receipt.sequence == head.sequence {
                head.receipt_digest = Some(digest(&bytes));
            }
            std::fs::write(path, bytes).map_err(|_| corrupt())?;
        }
        std::fs::write(root.join("HEAD"), encode(&head, 4096)?).map_err(|_| corrupt())?;
        Ok(())
    }
    pub(crate) fn open(
        root: &Path,
        limits: LifecycleLimits,
        enforced: bool,
        baseline: &[LifecycleIdentity],
    ) -> Result<Self, PlatformError> {
        let state = persistence::open_version(root, limits, enforced, baseline, 1)?;
        let mut source_hash = Sha256::new();
        source_hash.update(b"lsf-v1-migration-source\0");
        for name in ["MODE", "INITIALIZED", "HEAD"] {
            let bytes = io::required(&root.join(name), 4096)?;
            frame(&mut source_hash, &bytes);
        }
        let mut baseline_hash = Sha256::new();
        baseline_hash.update(b"lsf-lifecycle-baseline-v2\0");
        let mut evidence_bytes = 0usize;
        for entry in state.entries.values() {
            let bytes = encode(&entry.stored, limits.max_record_bytes)?;
            frame(&mut source_hash, &bytes);
            frame(
                &mut baseline_hash,
                &encode(&entry.stored.identity, limits.max_record_bytes)?,
            );
            if let Some(revision) = &entry.stored.record.evidence_revision_digest {
                let path = root.join("evidence").join(&revision.as_str()[7..]);
                let (selected, _, bytes) = evidence::read_revision(&path, limits, false)?;
                evidence_bytes = evidence_bytes
                    .checked_add(bytes)
                    .filter(|n| *n <= limits.max_total_evidence_bytes)
                    .ok_or_else(exhausted)?;
                if selected.identity != entry.stored.identity {
                    return Err(corrupt());
                }
                frame(&mut source_hash, revision.as_str().as_bytes());
            }
        }
        for value in state.receipts.values() {
            frame(
                &mut source_hash,
                &encode(value, limits.max_receipt_bytes + 256)?,
            );
        }
        let mode = persistence::Mode {
            format_version: 2,
            enforced,
            receipt_capacity: limits.max_recent_operations,
            baseline_digest: baseline_hash.finalize().into(),
            baseline_count: state.entries.len(),
        };
        let order = state.entries.keys().cloned().collect();
        Ok(Self {
            root: root.to_owned(),
            limits,
            state,
            order,
            mode,
            fingerprint: source_hash.finalize().into(),
        })
    }

    pub(crate) fn fingerprint(&self) -> [u8; 32] {
        self.fingerprint
    }
    pub(crate) fn len(&self) -> usize {
        self.state.entries.len()
    }
    pub(crate) fn receipts(&self) -> usize {
        self.state.receipts.len()
    }
    pub(crate) fn identities(&self) -> impl Iterator<Item = &LifecycleIdentity> {
        self.state
            .entries
            .values()
            .map(|entry| &entry.stored.identity)
    }
    pub(crate) fn retained_bytes(&self) -> Result<usize, PlatformError> {
        self.state
            .head
            .row_bytes
            .checked_mul(3)
            .and_then(|n| n.checked_add(self.state.entries.len().checked_mul(4096)?))
            .and_then(|n| {
                n.checked_add(
                    self.limits
                        .max_recent_operations
                        .checked_mul(self.limits.max_receipt_bytes + 256)?,
                )
            })
            .ok_or_else(exhausted)
    }

    pub(crate) fn begin(&self, target: &Path) -> Result<(), PlatformError> {
        io::create_directory(target)?;
        for name in ["records", "receipts", "evidence"] {
            io::create_directory(&target.join(name))?;
        }
        exact_write(&target.join("MODE"), &encode(&self.mode, 4096)?, 4096)
    }

    pub(crate) fn stage_rows(
        &self,
        target: &Path,
        start: usize,
        count: usize,
    ) -> Result<(), PlatformError> {
        if count == 0 || count > 1024 || start > self.len() {
            return Err(invalid());
        }
        for id in &self.order[start..start.saturating_add(count).min(self.len())] {
            let entry = self.state.entries.get(id).ok_or_else(corrupt)?;
            let identity = &entry.stored.identity;
            exact_write(
                &persistence::row_path(target, &identity.publication()?.id)?,
                &encode(&entry.stored, self.limits.max_record_bytes)?,
                self.limits.max_record_bytes,
            )?;
            if let Some(revision) = &entry.stored.record.evidence_revision_digest {
                let original = self.root.join("evidence").join(&revision.as_str()[7..]);
                let destination = target.join("evidence").join(&revision.as_str()[7..]);
                let (selected, files, _) = evidence::read_revision(&original, self.limits, false)?;
                if selected.identity != *identity {
                    return Err(corrupt());
                }
                io::create_directory(&destination)?;
                for (index, bytes) in files.into_iter().enumerate() {
                    exact_write(
                        &destination.join(format!("{index:03}.bin")),
                        &bytes,
                        self.limits.max_evidence_revision_bytes,
                    )?;
                }
                let record = io::required(&original.join("revision.json"), 16 * 1024)?;
                exact_write(&destination.join("revision.json"), &record, 16 * 1024)?;
                io::sync(&destination)?;
            }
        }
        io::sync(&target.join("records"))?;
        io::sync(&target.join("evidence"))
    }

    pub(crate) fn stage_receipts(
        &self,
        target: &Path,
        start: usize,
        count: usize,
    ) -> Result<(), PlatformError> {
        if count == 0 || count > 1024 || start > self.receipts() {
            return Err(invalid());
        }
        for (slot, receipt) in self.state.receipts.iter().skip(start).take(count) {
            let bytes = encode(receipt, self.limits.max_receipt_bytes + 256)?;
            exact_write(
                &persistence::slot_path(target, *slot),
                &bytes,
                self.limits.max_receipt_bytes + 256,
            )?;
        }
        io::sync(&target.join("receipts"))
    }

    pub(crate) fn finish(&self, target: &Path) -> Result<(), PlatformError> {
        let mode = digest(&encode(&self.mode, 4096)?);
        let receipt_digest = if self.state.head.sequence == 0 {
            None
        } else {
            let slot = ((self.state.head.sequence - 1) % self.limits.max_recent_operations as u64)
                as usize;
            Some(digest(&encode(
                self.state.receipts.get(&slot).ok_or_else(corrupt)?,
                self.limits.max_receipt_bytes + 256,
            )?))
        };
        let head = Head {
            format_version: 2,
            mode,
            receipt_digest,
            ..self.state.head.clone()
        };
        exact_write(&target.join("HEAD"), &encode(&head, 4096)?, 4096)?;
        exact_write(&target.join("INITIALIZED"), &encode(&mode, 128)?, 128)?;
        let baseline: Vec<_> = self.identities().cloned().collect();
        let recovered = persistence::open(target, self.limits, self.mode.enforced, &baseline)?;
        if recovered.head != head
            || recovered.entries.len() != self.len()
            || recovered.receipts != self.state.receipts
        {
            return Err(corrupt());
        }
        io::sync(target)
    }
}

fn frame(hash: &mut Sha256, bytes: &[u8]) {
    hash.update((bytes.len() as u64).to_le_bytes());
    hash.update(bytes);
}

fn exact_write(path: &Path, bytes: &[u8], maximum: usize) -> Result<(), PlatformError> {
    persistence::replace_checked(path, None, bytes, maximum)
}
