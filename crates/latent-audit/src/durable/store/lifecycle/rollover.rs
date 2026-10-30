use super::super::Head;
use super::model::{
    AuditRolloverReceipt, Custody, EpochLink, Seal, MAX_ARCHIVES, MAX_CUSTODY_BYTES,
};
use super::{
    codec, corrupt, cut, epoch_state, failure, io, storage, Deadline, Mode, Result, Store,
};
use latent_core::PlatformErrorCode;
use serde::{Deserialize, Serialize};
use std::{fs, path::Path};

#[derive(Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct Transition {
    format_version: u32,
    archive_root: String,
    old_head: Head,
    new_head: Head,
    old_mode: Mode,
    new_mode: Mode,
    old_custody: Custody,
    new_custody: Custody,
    seal: Seal,
}

pub(super) fn run(
    journal: &Path,
    custody: &Path,
    expected_epoch: &str,
    operation: &str,
    deadline: Deadline,
) -> Result<AuditRolloverReceipt> {
    deadline.check()?;
    storage::separate(journal, custody)?;
    let root = storage::existing_root(journal)?;
    if io::present(&root.path.join("TRANSFER"))? {
        return Err(failure(
            PlatformErrorCode::Unavailable,
            "audit-maintenance-resume-required",
        ));
    }
    if io::present(&root.path.join("ROLLOVER"))? {
        let transition: Transition = storage::canonical(&root.path.join("ROLLOVER"), 16384)?;
        transition.validate()?;
        if transition.old_head.epoch != expected_epoch
            || transition.seal.operation_id != operation
            || storage::absolute(custody)?.to_str() != Some(transition.archive_root.as_str())
        {
            return Err(failure(
                PlatformErrorCode::StateConflict,
                "audit-maintenance-identity-mismatch",
            ));
        }
        return execute(root, storage::existing_root(custody)?, transition, deadline);
    }
    let (source, mode) = storage::active(root, deadline)?;
    if let Some(link) = &mode.lineage {
        if link.operation_id == operation && link.previous_epoch == expected_epoch {
            return Ok(AuditRolloverReceipt {
                operation_id: operation.into(),
                previous_epoch: expected_epoch.into(),
                epoch: mode.epoch.clone(),
                next_sequence: link.first_sequence,
                archive_seal: link.previous_seal.clone(),
                already_completed: true,
            });
        }
    }
    if mode.epoch != expected_epoch {
        return Err(failure(
            PlatformErrorCode::StateConflict,
            "audit-maintenance-epoch-mismatch",
        ));
    }
    if source.pending.is_some() {
        return Err(failure(
            PlatformErrorCode::ResourceExhausted,
            "audit-critical-pending",
        ));
    }
    if source.head.records == 0 {
        return Err(failure(
            PlatformErrorCode::StateConflict,
            "audit-empty-epoch",
        ));
    }
    let (archive_root, old_custody) = storage::custody_root(custody, &source, &mode)?;
    storage::verify_custody(&archive_root, &old_custody, deadline)?;
    if old_custody.archives.len() == MAX_ARCHIVES
        || old_custody
            .archives
            .iter()
            .map(|entry| entry.record_bytes)
            .sum::<usize>()
            .checked_add(source.head.bytes)
            .is_none_or(|bytes| bytes > MAX_CUSTODY_BYTES)
    {
        return Err(failure(
            PlatformErrorCode::ResourceExhausted,
            "audit-archive-capacity",
        ));
    }
    let transition = prepare(&source, mode, old_custody, &archive_root)?.identify(operation)?;
    transition.validate()?;
    deadline.check()?;
    io::atomic(
        &source.root.path.join("ROLLOVER"),
        &codec::encode(&transition, 16384)?,
    )?;
    cut(1)?;
    execute(source.root, archive_root, transition, deadline)
}

fn prepare(source: &Store, mode: Mode, custody: Custody, root: &io::Root) -> Result<Transition> {
    let epoch = io::epoch()?;
    let seal = Seal {
        format_version: 1,
        journal_id: custody.journal_id.clone(),
        epoch: mode.epoch.clone(),
        successor_epoch: epoch.clone(),
        operation_id: String::new(),
        first_sequence: source.first_sequence,
        next_sequence: source.head.next_sequence,
        records: source.head.records,
        record_bytes: source.head.bytes,
        head_digest: source.head.last_digest.clone(),
        mode_digest: codec::digest(&codec::encode(&mode, 1024)?),
        head_file_digest: codec::digest(&codec::encode(&source.head, 1024)?),
        predecessor_seal: mode
            .lineage
            .as_ref()
            .map_or_else(|| "0".repeat(64), |link| link.previous_seal.clone()),
        unknown_outcomes: source.unknown,
    };
    // The request identity is filled by the caller before durable preparation.
    Ok(Transition {
        format_version: 1,
        archive_root: root.path.to_str().ok_or_else(corrupt)?.into(),
        old_head: source.head.clone(),
        new_head: Head {
            format_version: 1,
            epoch: epoch.clone(),
            next_sequence: source.head.next_sequence,
            records: 0,
            bytes: 0,
            last_digest: source.head.last_digest.clone(),
        },
        old_mode: mode.clone(),
        new_mode: Mode {
            format_version: 2,
            epoch,
            retention: "reject-new".into(),
            initialized: true,
            sessions: mode.sessions,
            lineage: None,
        },
        old_custody: custody.clone(),
        new_custody: custody,
        seal,
    })
}

impl Transition {
    fn identify(mut self, operation: &str) -> Result<Self> {
        self.seal.operation_id = operation.into();
        self.new_mode.lineage = Some(EpochLink {
            journal_id: self.old_custody.journal_id.clone(),
            custody_id: self.old_custody.custody_id.clone(),
            first_sequence: self.old_head.next_sequence,
            previous_epoch: self.old_head.epoch.clone(),
            previous_head: self.old_head.last_digest.clone(),
            previous_seal: self.seal.digest()?,
            operation_id: operation.into(),
            unknown_outcomes_before: self.seal.unknown_outcomes,
        });
        self.new_custody.archives.push(self.seal.entry()?);
        Ok(self)
    }

    fn validate(&self) -> Result<()> {
        self.old_custody.validate()?;
        self.new_custody.validate()?;
        self.seal.validate()?;
        let (floor, _, _) = epoch_state(&self.old_mode)?;
        let (new_floor, new_seed, new_unknown) = epoch_state(&self.new_mode)?;
        let mut expected_custody = self.old_custody.clone();
        expected_custody.archives.push(self.seal.entry()?);
        let expected_link = EpochLink {
            journal_id: self.old_custody.journal_id.clone(),
            custody_id: self.old_custody.custody_id.clone(),
            first_sequence: self.old_head.next_sequence,
            previous_epoch: self.old_head.epoch.clone(),
            previous_head: self.old_head.last_digest.clone(),
            previous_seal: self.seal.digest()?,
            operation_id: self.seal.operation_id.clone(),
            unknown_outcomes_before: self.seal.unknown_outcomes,
        };
        if self.format_version != 1
            || !self.old_mode.initialized
            || self.old_head.format_version != 1
            || self.old_head.epoch != self.old_mode.epoch
            || self.old_head.epoch != self.seal.epoch
            || self.old_custody.journal_id != self.seal.journal_id
            || self.new_custody != expected_custody
            || self.old_custody.next_sequence()? != floor
            || self.old_head.records != self.seal.records
            || self.old_head.bytes != self.seal.record_bytes
            || floor != self.seal.first_sequence
            || self.old_head.next_sequence != self.seal.next_sequence
            || self.old_head.last_digest != self.seal.head_digest
            || codec::digest(&codec::encode(&self.old_mode, 1024)?) != self.seal.mode_digest
            || codec::digest(&codec::encode(&self.old_head, 1024)?) != self.seal.head_file_digest
            || self.new_mode.lineage.as_ref() != Some(&expected_link)
            || self.new_mode.epoch != self.seal.successor_epoch
            || self.new_mode.sessions != self.old_mode.sessions
            || new_floor != self.old_head.next_sequence
            || new_seed != self.old_head.last_digest
            || new_unknown != self.seal.unknown_outcomes
            || self.new_head
                != (Head {
                    format_version: 1,
                    epoch: self.new_mode.epoch.clone(),
                    next_sequence: self.old_head.next_sequence,
                    records: 0,
                    bytes: 0,
                    last_digest: self.old_head.last_digest.clone(),
                })
        {
            return Err(corrupt());
        }
        storage::absolute(Path::new(&self.archive_root))?;
        Ok(())
    }
    fn receipt(&self) -> Result<AuditRolloverReceipt> {
        Ok(AuditRolloverReceipt {
            operation_id: self.seal.operation_id.clone(),
            previous_epoch: self.old_head.epoch.clone(),
            epoch: self.new_head.epoch.clone(),
            next_sequence: self.new_head.next_sequence,
            archive_seal: self.seal.digest()?,
            already_completed: false,
        })
    }
}

fn validate_active(root: &io::Root, transition: &Transition) -> Result<()> {
    let allowed = [
        ".audit.lock",
        "HEAD",
        "HEAD.next",
        "MODE",
        "MODE.next",
        "records",
        "ROLLOVER",
        "ROLLOVER.next",
        "TRANSFER.next",
    ];
    if io::names(&root.path, allowed.len())?
        .iter()
        .any(|n| !allowed.contains(&n.as_str()))
    {
        return Err(corrupt());
    }
    let head: Head = storage::canonical(&root.path.join("HEAD"), 1024)?;
    let mode: Mode = storage::canonical(&root.path.join("MODE"), 1024)?;
    if (head != transition.old_head && head != transition.new_head)
        || (mode != transition.old_mode && mode != transition.new_mode)
    {
        return Err(corrupt());
    }
    for (name, bound) in [
        ("HEAD.next", 1024),
        ("MODE.next", 1024),
        ("ROLLOVER.next", 16384),
        ("TRANSFER.next", 16384),
    ] {
        if io::present(&root.path.join(name))? {
            io::read(&root.path.join(name), bound)?;
        }
    }
    Ok(())
}

fn publish(
    root: io::Root,
    custody: &io::Root,
    transition: &Transition,
    deadline: Deadline,
) -> Result<io::Root> {
    let stage = custody.path.join("stage");
    let published = custody.path.join(&transition.seal.epoch);
    if io::present(&published)? {
        if io::present(&stage)? {
            return Err(corrupt());
        }
        return Ok(root);
    }
    let (source, mode) = storage::active(root, deadline)?;
    if source.head != transition.old_head || mode != transition.old_mode || source.pending.is_some()
    {
        return Err(corrupt());
    }
    storage::copy(&source, &transition.seal, &stage, deadline)?;
    cut(2)?;
    fs::rename(&stage, &published).map_err(|_| super::super::super::unavailable())?;
    io::sync(&custody.path)?;
    cut(3)?;
    Ok(source.root)
}

fn execute(
    root: io::Root,
    custody: io::Root,
    transition: Transition,
    deadline: Deadline,
) -> Result<AuditRolloverReceipt> {
    transition.validate()?;
    validate_active(&root, &transition)?;
    let current = storage::read_custody(&custody)?;
    if current != transition.old_custody && current != transition.new_custody {
        return Err(corrupt());
    }
    storage::inventory(&custody, &transition.new_custody, true)?;
    storage::verify_retained(&custody, &transition.old_custody, deadline)?;
    let root = publish(root, &custody, &transition, deadline)?;
    let (verified, seal) = storage::archive(&custody.path.join(&transition.seal.epoch), deadline)?;
    if seal != transition.seal {
        return Err(corrupt());
    }
    let remaining = storage::remaining_records(&root.path, &verified, deadline)?;
    deadline.check()?;
    io::atomic(
        &custody.path.join("CUSTODY"),
        &codec::encode(&transition.new_custody, 4096)?,
    )?;
    cut(4)?;
    for name in remaining {
        deadline.check()?;
        io::remove(&root.path.join("records").join(name), 16384)?;
        cut(5)?;
    }
    io::sync(&root.path.join("records"))?;
    deadline.check()?;
    io::atomic(
        &root.path.join("HEAD"),
        &codec::encode(&transition.new_head, 1024)?,
    )?;
    cut(6)?;
    io::atomic(
        &root.path.join("MODE"),
        &codec::encode(&transition.new_mode, 1024)?,
    )?;
    cut(7)?;
    if storage::canonical::<Head>(&root.path.join("HEAD"), 1024)? != transition.new_head
        || storage::canonical::<Mode>(&root.path.join("MODE"), 1024)? != transition.new_mode
        || !io::names(&root.path.join("records"), 1)?.is_empty()
    {
        return Err(corrupt());
    }
    deadline.check()?;
    cut(8)?;
    io::remove(&root.path.join("ROLLOVER.next"), 16384)?;
    io::remove(&root.path.join("TRANSFER.next"), 16384)?;
    io::remove(&root.path.join("ROLLOVER"), 16384)?;
    cut(9)?;
    transition.receipt()
}
