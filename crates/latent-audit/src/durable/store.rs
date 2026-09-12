mod io;
mod query;
use super::{
    capacity, codec, corrupt,
    model::{
        AuditActorIdentity, AuditCursor, AuditOperationResult, AuditPageCoverage, AuditPageStop,
        AuditPendingAttempt, AuditQueryRequest, AuditRecordData, AuditScope, AuditStoredRecord,
        DurableAuditAck,
    },
    AuditLimits, Result,
};
use serde::{Deserialize, Serialize};
use std::{fs, path::Path};

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct Head {
    format_version: u32,
    epoch: String,
    next_sequence: u64,
    records: usize,
    bytes: usize,
    last_digest: String,
}
#[derive(Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct Mode {
    format_version: u32,
    epoch: String,
    retention: String,
    initialized: bool,
    sessions: u64,
}
#[derive(Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct Intent {
    old: Head,
    new: Head,
    size: usize,
    digest: String,
}
pub(super) struct Entry {
    sequence: u64,
    bytes: usize,
    digest: String,
    scope: AuditScope,
    actor: String,
    kind: Option<crate::Phase2AuditEventKind>,
    time: u64,
}
pub(super) struct Store {
    root: io::Root,
    head: Head,
    entries: Vec<Entry>,
    pub limits: AuditLimits,
    pub pending: Option<AuditPendingAttempt>,
    pub unknown: u64,
    pub unhealthy: bool,
    pub previous_session_loss_unknown: bool,
}
impl Store {
    pub fn open(path: &Path, limits: AuditLimits) -> Result<Self> {
        let limits = limits.validate()?;
        if limits.maximum_metadata_bytes < 128 * 1024 + limits.maximum_records * 1536 {
            return Err(capacity());
        }
        let root = io::root(path)?;
        let allowed = [
            ".audit.lock",
            "MODE",
            "MODE.next",
            "HEAD",
            "HEAD.next",
            "INTENT",
            "INTENT.next",
            "record.next",
            "records",
        ];
        let names = io::names(&root.path, 10)?;
        if names.iter().any(|s| !allowed.contains(&s.as_str())) {
            return Err(corrupt());
        }
        let records = root.path.join("records");
        if !io::present(&records)? {
            io::create_directory(&records)?;
        }
        io::directory(&records)?;
        let mode_path = root.path.join("MODE");
        let mut mode: Mode = if io::present(&mode_path)? {
            codec::decode(&io::read(&mode_path, 1024)?, 1024)?
        } else {
            if !io::names(&records, 1)?.is_empty()
                || names
                    .iter()
                    .any(|n| !matches!(n.as_str(), ".audit.lock" | "records" | "MODE.next"))
            {
                return Err(corrupt());
            }
            let mode = Mode {
                format_version: 1,
                epoch: io::epoch()?,
                retention: "reject-new".into(),
                initialized: false,
                sessions: 0,
            };
            io::atomic(&mode_path, &codec::encode(&mode, 1024)?)?;
            mode
        };
        if mode.format_version != 1
            || mode.retention != "reject-new"
            || !codec::hex(&mode.epoch, 32)
        {
            return Err(corrupt());
        }
        let initial = Head {
            format_version: 1,
            epoch: mode.epoch.clone(),
            next_sequence: 1,
            records: 0,
            bytes: 0,
            last_digest: "0".repeat(64),
        };
        let head_path = root.path.join("HEAD");
        let mut head: Head = if io::present(&head_path)? {
            codec::decode(&io::read(&head_path, 1024)?, 1024)?
        } else {
            if mode.initialized
                || !io::names(&records, 1)?.is_empty()
                || io::present(&root.path.join("INTENT"))?
            {
                return Err(corrupt());
            }
            io::atomic(&head_path, &codec::encode(&initial, 1024)?)?;
            initial
        };
        if head.epoch != mode.epoch || head.format_version != 1 {
            return Err(corrupt());
        }
        if !mode.initialized
            && (head.records != 0
                || head.next_sequence != 1
                || io::present(&root.path.join("INTENT"))?)
        {
            return Err(corrupt());
        }
        recover(&root, &mut head, limits)?;
        let mut store = Self {
            root,
            head,
            entries: Vec::new(),
            limits,
            pending: None,
            unknown: 0,
            unhealthy: false,
            previous_session_loss_unknown: mode.sessions > 0,
        };
        store.scan()?;
        mode.initialized = true;
        mode.sessions = mode.sessions.checked_add(1).ok_or_else(corrupt)?;
        io::atomic(&mode_path, &codec::encode(&mode, 1024)?)?;
        Ok(store)
    }
    pub fn summary(&self) -> (usize, usize, u64) {
        (self.head.records, self.head.bytes, self.head.next_sequence)
    }
    fn scan(&mut self) -> Result<()> {
        let names = io::names(&self.root.path.join("records"), self.limits.maximum_records)?;
        if names.len() != self.head.records
            || self.head.next_sequence != names.len() as u64 + 1
            || self.head.bytes > self.limits.maximum_disk_bytes
        {
            return Err(corrupt());
        }
        let mut previous = "0".repeat(64);
        let mut total = 0usize;
        self.entries
            .try_reserve_exact(names.len())
            .map_err(|_| capacity())?;
        for (i, name) in names.iter().enumerate() {
            if name != &filename(i as u64 + 1) {
                return Err(corrupt());
            }
            let bytes = io::read(
                &self.root.path.join("records").join(name),
                self.limits.maximum_record_bytes,
            )?;
            total = total.checked_add(bytes.len()).ok_or_else(capacity)?;
            if total > self.limits.maximum_disk_bytes {
                return Err(capacity());
            }
            let record: AuditStoredRecord =
                codec::decode(&bytes, self.limits.maximum_record_bytes)?;
            codec::record(&record)?;
            if record.epoch != self.head.epoch
                || record.sequence != i as u64 + 1
                || record.previous_digest != previous
                || codec::encode(&record, self.limits.maximum_record_bytes)?.as_slice() != bytes
            {
                return Err(corrupt());
            }
            previous = codec::digest(&bytes);
            self.adopt(&record, bytes.len(), previous.clone())?;
        }
        if total != self.head.bytes || previous != self.head.last_digest {
            return Err(corrupt());
        }
        Ok(())
    }
    fn adopt(&mut self, r: &AuditStoredRecord, bytes: usize, digest: String) -> Result<()> {
        let kind = match &r.data {
            AuditRecordData::Attempt(a) => {
                if self.pending.is_some() {
                    return Err(corrupt());
                }
                self.pending = Some(AuditPendingAttempt {
                    sequence: r.sequence,
                    attempt: a.clone(),
                });
                None
            }
            AuditRecordData::Outcome {
                attempt_sequence,
                conclusion,
            } => {
                let p = self.pending.take().ok_or_else(corrupt)?;
                if p.sequence != *attempt_sequence
                    || p.attempt.scope != r.scope
                    || p.attempt.actor != r.actor
                {
                    return Err(corrupt());
                }
                if conclusion.result == AuditOperationResult::Unknown {
                    self.unknown = self.unknown.saturating_add(1);
                }
                None
            }
            AuditRecordData::Observation(o) => Some(o.kind),
        };
        self.entries.push(Entry {
            sequence: r.sequence,
            bytes,
            digest,
            scope: r.scope.clone(),
            actor: r.actor.subject.clone(),
            kind,
            time: r.accepted_at_unix_millis,
        });
        Ok(())
    }
    pub fn append(
        &mut self,
        scope: AuditScope,
        actor: AuditActorIdentity,
        data: AuditRecordData,
    ) -> Result<DurableAuditAck> {
        if self.unhealthy {
            return Err(super::unavailable());
        }
        let sequence = self.head.next_sequence;
        let record = AuditStoredRecord {
            format_version: 1,
            epoch: self.head.epoch.clone(),
            sequence,
            previous_digest: self.head.last_digest.clone(),
            accepted_at_unix_millis: now(),
            scope,
            actor,
            data,
        };
        codec::record(&record)?;
        let bytes = codec::encode(&record, self.limits.maximum_record_bytes)?;
        if self.head.records >= self.limits.maximum_records
            || bytes.len() > self.limits.maximum_disk_bytes - self.head.bytes
        {
            return Err(capacity());
        }
        let digest = codec::digest(&bytes);
        let new = Head {
            next_sequence: sequence.checked_add(1).ok_or_else(capacity)?,
            records: self.head.records + 1,
            bytes: self.head.bytes + bytes.len(),
            last_digest: digest.clone(),
            ..self.head.clone()
        };
        let intent = Intent {
            old: self.head.clone(),
            new: new.clone(),
            size: bytes.len(),
            digest: digest.clone(),
        };
        // Any failure after filesystem work begins requires exact recovery.
        self.unhealthy = true;
        io::stage(&self.root.path.join("record.next"), &bytes)?;
        cut(1)?;
        io::atomic(
            &self.root.path.join("INTENT"),
            &codec::encode(&intent, 16384)?,
        )?;
        cut(2)?;
        promote(&self.root, &intent)?;
        cut(3)?;
        io::atomic(&self.root.path.join("HEAD"), &codec::encode(&new, 1024)?)?;
        cut(4)?;
        self.head = new;
        self.adopt(&record, bytes.len(), digest)?;
        // After HEAD is durable the acknowledgement remains true even if cleanup
        // fails; retain unhealthy/stage charge and prevent subsequent writes.
        if cleanup(&self.root).is_ok() {
            self.unhealthy = false;
        }
        Ok(DurableAuditAck {
            epoch: self.head.epoch.clone(),
            sequence,
            digest: codec::blob(&bytes),
        })
    }
}
fn filename(sequence: u64) -> String {
    format!("r-{sequence:016x}")
}
#[cfg(test)]
pub(super) fn written_bytes() -> usize {
    io::WRITTEN.with(std::cell::Cell::get)
}
#[cfg(test)]
pub(super) fn expire_after_query_read(value: bool) {
    query::EXPIRE_AFTER_READ.with(|f| f.set(value));
    query::EXPIRED.with(|f| f.set(false));
}
fn promote(root: &io::Root, i: &Intent) -> Result<()> {
    let dest = root
        .path
        .join("records")
        .join(filename(i.old.next_sequence));
    if io::present(&dest)? {
        let bytes = io::read(&dest, i.size)?;
        if bytes.len() != i.size || codec::digest(&bytes) != i.digest {
            return Err(corrupt());
        }
    } else {
        let source = root.path.join("record.next");
        let bytes = io::read(&source, i.size)?;
        if bytes.len() != i.size || codec::digest(&bytes) != i.digest {
            return Err(corrupt());
        }
        fs::rename(source, dest).map_err(|_| super::unavailable())?;
    }
    io::sync(&root.path.join("records"))
}
fn cleanup(root: &io::Root) -> Result<()> {
    for (name, maximum) in [
        ("INTENT", 16384),
        ("INTENT.next", 16384),
        ("record.next", 16384),
        ("HEAD.next", 1024),
        ("MODE.next", 1024),
    ] {
        io::remove(&root.path.join(name), maximum)?;
    }
    Ok(())
}
fn recover(root: &io::Root, head: &mut Head, limits: AuditLimits) -> Result<()> {
    let path = root.path.join("INTENT");
    if io::present(&path)? {
        let i: Intent = codec::decode(&io::read(&path, 16384)?, 16384)?;
        if i.old.epoch != head.epoch
            || i.new.epoch != head.epoch
            || i.new.next_sequence != i.old.next_sequence.checked_add(1).ok_or_else(corrupt)?
            || i.new.records != i.old.records.checked_add(1).ok_or_else(corrupt)?
            || i.new.bytes != i.old.bytes.checked_add(i.size).ok_or_else(corrupt)?
            || i.size > limits.maximum_record_bytes
            || i.new.records > limits.maximum_records
            || i.new.bytes > limits.maximum_disk_bytes
            || i.new.format_version != 1
            || i.old.format_version != 1
            || i.new.last_digest != i.digest
            || (!(*head == i.old || *head == i.new))
        {
            return Err(corrupt());
        }
        let final_path = root
            .path
            .join("records")
            .join(filename(i.old.next_sequence));
        let candidate = if io::present(&final_path)? {
            final_path
        } else {
            root.path.join("record.next")
        };
        let bytes = io::read(&candidate, limits.maximum_record_bytes)?;
        let record: AuditStoredRecord = codec::decode(&bytes, limits.maximum_record_bytes)?;
        codec::record(&record)?;
        if record.epoch != i.old.epoch
            || record.sequence != i.old.next_sequence
            || record.previous_digest != i.old.last_digest
            || bytes.len() != i.size
            || codec::digest(&bytes) != i.digest
            || codec::encode(&record, limits.maximum_record_bytes)? != bytes
        {
            return Err(corrupt());
        }
        promote(root, &i)?;
        io::atomic(&root.path.join("HEAD"), &codec::encode(&i.new, 1024)?)?;
        *head = i.new;
    }
    cleanup(root)
}
pub(super) fn now() -> u64 {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap_or_default()
        .as_millis()
        .try_into()
        .unwrap_or(u64::MAX)
}
#[cfg_attr(
    not(test),
    expect(
        clippy::unnecessary_wraps,
        reason = "Test failure injection preserves the production transaction call sites"
    )
)]
fn cut(point: u8) -> Result<()> {
    #[cfg(not(test))]
    let _ = point;
    #[cfg(test)]
    if FAIL.with(|f| {
        if f.get() == point {
            f.set(0);
            true
        } else {
            false
        }
    }) {
        return Err(super::unavailable());
    }
    Ok(())
}
#[cfg(test)]
thread_local! {pub(super) static FAIL:std::cell::Cell<u8>=const{std::cell::Cell::new(0)};}
