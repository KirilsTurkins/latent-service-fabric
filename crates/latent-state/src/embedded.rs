//! Host-internal atomic record storage. This is neither a guest API nor a
//! multi-backend abstraction. A caller supplies an already protected descriptor.
use redb::{
    Database, Durability, ReadTransaction, ReadableDatabase, ReadableTable, TableDefinition,
};
use std::{
    collections::BTreeSet,
    fs::File,
    sync::{
        atomic::{AtomicBool, AtomicUsize, Ordering},
        Arc,
    },
    time::{Duration, Instant},
};

const FORMAT: &[u8] = b"latent.transaction-store.v1";
const META: TableDefinition<&str, &[u8]> = TableDefinition::new("format");
const ROWS: TableDefinition<&[u8], &[u8]> = TableDefinition::new("records-v1");

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum StoreError {
    Invalid,
    Capacity,
    Conflict,
    Corrupt,
    UnsupportedFormat,
    Unavailable,
    CommitUncertain,
    SnapshotExpired,
}

#[derive(Debug, Clone, Copy)]
pub struct StoreLimits {
    pub cache_bytes: usize,
    pub maximum_rows: usize,
    pub maximum_logical_bytes: usize,
    pub maximum_key_bytes: usize,
    pub maximum_value_bytes: usize,
    pub maximum_batch_rows: usize,
    pub maximum_read_views: usize,
    pub maximum_view_age: Duration,
}
impl Default for StoreLimits {
    fn default() -> Self {
        Self {
            cache_bytes: 8 * 1024 * 1024,
            maximum_rows: 16_384,
            maximum_logical_bytes: 32 * 1024 * 1024,
            maximum_key_bytes: 1024,
            maximum_value_bytes: 1024 * 1024,
            maximum_batch_rows: 256,
            maximum_read_views: 8,
            maximum_view_age: Duration::from_secs(30),
        }
    }
}
impl StoreLimits {
    fn validate(self) -> Result<Self, StoreError> {
        if self.cache_bytes < 1024 * 1024
            || self.cache_bytes > 64 * 1024 * 1024
            || self.maximum_rows == 0
            || self.maximum_rows > 65_536
            || self.maximum_logical_bytes == 0
            || self.maximum_logical_bytes > 128 * 1024 * 1024
            || self.maximum_key_bytes == 0
            || self.maximum_key_bytes > 4096
            || self.maximum_value_bytes == 0
            || self.maximum_value_bytes > 4 * 1024 * 1024
            || self.maximum_batch_rows == 0
            || self.maximum_batch_rows > 1024
            || self.maximum_read_views == 0
            || self.maximum_read_views > 32
            || self.maximum_view_age.is_zero()
            || self.maximum_view_age > Duration::from_mins(1)
        {
            return Err(StoreError::Invalid);
        }
        Ok(self)
    }
}

/// Fixed families share one engine transaction. The first byte is a closed tag,
/// never an application-selected engine table name or filesystem path.
#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord)]
#[repr(u8)]
pub enum Family {
    Namespace = 1,
    State = 2,
    Tombstone = 3,
    Command = 4,
    Result = 5,
    Outbox = 6,
    Attempt = 7,
    Inbox = 8,
    PayloadReference = 9,
    Maintenance = 10,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct RowKey {
    pub family: Family,
    pub key: Vec<u8>,
}
impl RowKey {
    fn encoded(&self, limits: StoreLimits) -> Result<Vec<u8>, StoreError> {
        if self.key.is_empty() || self.key.len() > limits.maximum_key_bytes {
            return Err(StoreError::Invalid);
        }
        let mut out = Vec::with_capacity(self.key.len() + 1);
        out.push(self.family as u8);
        out.extend_from_slice(&self.key);
        Ok(out)
    }
}
#[derive(Debug, Clone)]
pub struct ExpectedRow {
    pub key: RowKey,
    pub value: Option<Vec<u8>>,
}
#[derive(Debug, Clone)]
pub struct RowMutation {
    pub key: RowKey,
    pub value: Option<Vec<u8>>,
}
#[derive(Debug, Clone, Default)]
pub struct AtomicBatch {
    pub expectations: Vec<ExpectedRow>,
    pub mutations: Vec<RowMutation>,
}

pub struct EmbeddedStore {
    db: Database,
    limits: StoreLimits,
    views: Arc<AtomicUsize>,
    quarantined: AtomicBool,
}
impl EmbeddedStore {
    /// Must run on the node's bounded physical I/O owner. Never truncate or reset
    /// an existing file on any error. redb owns the descriptor and exclusive lock.
    pub fn open_file(file: File, limits: StoreLimits) -> Result<Self, StoreError> {
        let limits = limits.validate()?;
        let was_empty = file.metadata().map_err(|_| StoreError::Unavailable)?.len() == 0;
        let mut builder = Database::builder();
        builder.set_cache_size(limits.cache_bytes);
        let db = builder.create_file(file).map_err(|_| StoreError::Corrupt)?;
        if was_empty {
            let mut tx = db.begin_write().map_err(|_| StoreError::Unavailable)?;
            tx.set_durability(Durability::Immediate)
                .map_err(|_| StoreError::Unavailable)?;
            {
                let mut meta = tx.open_table(META).map_err(|_| StoreError::Corrupt)?;
                meta.insert("schema", FORMAT)
                    .map_err(|_| StoreError::Unavailable)?;
            }
            {
                tx.open_table(ROWS).map_err(|_| StoreError::Corrupt)?;
            }
            tx.commit().map_err(|_| StoreError::CommitUncertain)?;
        }
        let store = Self {
            db,
            limits,
            views: Arc::new(AtomicUsize::new(0)),
            quarantined: AtomicBool::new(false),
        };
        store.verify()?;
        Ok(store)
    }
    fn verify(&self) -> Result<(), StoreError> {
        let tx = self.db.begin_read().map_err(|_| StoreError::Unavailable)?;
        let meta = tx
            .open_table(META)
            .map_err(|_| StoreError::UnsupportedFormat)?;
        if meta
            .get("schema")
            .map_err(|_| StoreError::Corrupt)?
            .map(|v| v.value().to_vec())
            .as_deref()
            != Some(FORMAT)
        {
            return Err(StoreError::UnsupportedFormat);
        }
        let table = tx.open_table(ROWS).map_err(|_| StoreError::Corrupt)?;
        self.charge_table(&table)?;
        Ok(())
    }
    fn charge_table(
        &self,
        table: &impl ReadableTable<&'static [u8], &'static [u8]>,
    ) -> Result<(), StoreError> {
        let mut count = 0usize;
        let mut bytes = 0usize;
        for row in table.iter().map_err(|_| StoreError::Corrupt)? {
            let (k, v) = row.map_err(|_| StoreError::Corrupt)?;
            let k = k.value();
            let v = v.value();
            if k.len() < 2
                || k.len() > self.limits.maximum_key_bytes + 1
                || !(1..=10).contains(&k[0])
                || v.len() > self.limits.maximum_value_bytes
            {
                return Err(StoreError::Corrupt);
            }
            count = count.checked_add(1).ok_or(StoreError::Capacity)?;
            bytes = bytes
                .checked_add(k.len() + v.len())
                .ok_or(StoreError::Capacity)?;
            if count > self.limits.maximum_rows || bytes > self.limits.maximum_logical_bytes {
                return Err(StoreError::Capacity);
            }
        }
        Ok(())
    }
    pub fn snapshot(&self) -> Result<ReadView, StoreError> {
        if self.quarantined.load(Ordering::Acquire) {
            return Err(StoreError::Unavailable);
        }
        self.views
            .fetch_update(Ordering::AcqRel, Ordering::Acquire, |v| {
                (v < self.limits.maximum_read_views).then_some(v + 1)
            })
            .map_err(|_| StoreError::Capacity)?;
        if let Ok(tx) = self.db.begin_read() {
            Ok(ReadView {
                tx: Some(tx),
                limits: self.limits,
                views: Arc::clone(&self.views),
                opened: Instant::now(),
            })
        } else {
            self.views.fetch_sub(1, Ordering::AcqRel);
            Err(StoreError::Unavailable)
        }
    }
    /// Checks and every family mutation commit together. Pre-commit failures
    /// abort; a commit I/O error is uncertain and requires original-key recovery.
    pub fn apply(&self, batch: AtomicBatch) -> Result<(), StoreError> {
        self.apply_with_checkpoint(batch, |_| {})
    }
    fn apply_with_checkpoint(
        &self,
        batch: AtomicBatch,
        mut checkpoint: impl FnMut(bool),
    ) -> Result<(), StoreError> {
        if self.quarantined.load(Ordering::Acquire) {
            return Err(StoreError::Unavailable);
        }
        let maximum = self.limits.maximum_batch_rows;
        if batch.expectations.len() > maximum || batch.mutations.len() > maximum {
            return Err(StoreError::Capacity);
        }
        let mut checks = BTreeSet::new();
        let mut mutations = BTreeSet::new();
        let mut bytes = 0usize;
        for check in &batch.expectations {
            self.validate_row(&check.key, check.value.as_deref(), &mut checks, &mut bytes)?;
        }
        for mutation in &batch.mutations {
            self.validate_row(
                &mutation.key,
                mutation.value.as_deref(),
                &mut mutations,
                &mut bytes,
            )?;
        }
        let mut tx = self.db.begin_write().map_err(|_| StoreError::Unavailable)?;
        tx.set_durability(Durability::Immediate)
            .map_err(|_| StoreError::Unavailable)?;
        {
            let mut table = tx.open_table(ROWS).map_err(|_| StoreError::Corrupt)?;
            for check in batch.expectations {
                let key = check.key.encoded(self.limits)?;
                let actual = table
                    .get(key.as_slice())
                    .map_err(|_| StoreError::Corrupt)?
                    .map(|v| v.value().to_vec());
                if actual != check.value {
                    return Err(StoreError::Conflict);
                }
            }
            for mutation in batch.mutations {
                let key = mutation.key.encoded(self.limits)?;
                if let Some(value) = mutation.value {
                    table
                        .insert(key.as_slice(), value.as_slice())
                        .map_err(|_| StoreError::Unavailable)?;
                } else {
                    table
                        .remove(key.as_slice())
                        .map_err(|_| StoreError::Unavailable)?;
                }
            }
            self.charge_table(&table)?;
        }
        checkpoint(false);
        if tx.commit().is_err() {
            self.quarantined.store(true, Ordering::Release);
            return Err(StoreError::CommitUncertain);
        }
        checkpoint(true);
        Ok(())
    }
    fn validate_row(
        &self,
        key: &RowKey,
        value: Option<&[u8]>,
        seen: &mut BTreeSet<Vec<u8>>,
        bytes: &mut usize,
    ) -> Result<(), StoreError> {
        let encoded = key.encoded(self.limits)?;
        if !seen.insert(encoded) || value.is_some_and(|v| v.len() > self.limits.maximum_value_bytes)
        {
            return Err(StoreError::Invalid);
        }
        *bytes = bytes
            .checked_add(key.key.len() + value.map_or(0, <[u8]>::len))
            .ok_or(StoreError::Capacity)?;
        if *bytes > self.limits.maximum_logical_bytes {
            return Err(StoreError::Capacity);
        }
        Ok(())
    }
    #[must_use]
    pub fn live_views(&self) -> usize {
        self.views.load(Ordering::Acquire)
    }
    pub fn compact(&mut self) -> Result<bool, StoreError> {
        if self.quarantined.load(Ordering::Acquire) {
            return Err(StoreError::Unavailable);
        }
        if self.live_views() != 0 {
            return Err(StoreError::Capacity);
        }
        self.db.compact().map_err(|_| StoreError::Unavailable)
    }
}
pub struct ReadView {
    tx: Option<ReadTransaction>,
    limits: StoreLimits,
    views: Arc<AtomicUsize>,
    opened: Instant,
}
impl ReadView {
    pub fn get(&self, key: &RowKey) -> Result<Option<Vec<u8>>, StoreError> {
        if self.opened.elapsed() > self.limits.maximum_view_age {
            return Err(StoreError::SnapshotExpired);
        }
        let key = key.encoded(self.limits)?;
        let table = self
            .tx
            .as_ref()
            .expect("retained view")
            .open_table(ROWS)
            .map_err(|_| StoreError::Corrupt)?;
        let value = table.get(key.as_slice()).map_err(|_| StoreError::Corrupt)?;
        if value
            .as_ref()
            .is_some_and(|v| v.value().len() > self.limits.maximum_value_bytes)
        {
            return Err(StoreError::Corrupt);
        }
        Ok(value.map(|v| v.value().to_vec()))
    }
    pub fn scan(
        &self,
        family: Family,
        prefix: &[u8],
        maximum_rows: usize,
        maximum_bytes: usize,
    ) -> Result<Vec<(RowKey, Vec<u8>)>, StoreError> {
        if self.opened.elapsed() > self.limits.maximum_view_age {
            return Err(StoreError::SnapshotExpired);
        }
        if prefix.len() > self.limits.maximum_key_bytes
            || maximum_rows == 0
            || maximum_rows > 256
            || maximum_bytes == 0
            || maximum_bytes > 4 * 1024 * 1024
        {
            return Err(StoreError::Invalid);
        }
        let mut start = vec![family as u8];
        start.extend_from_slice(prefix);
        let table = self
            .tx
            .as_ref()
            .expect("retained view")
            .open_table(ROWS)
            .map_err(|_| StoreError::Corrupt)?;
        let mut out = Vec::new();
        let mut bytes = 0usize;
        for row in table
            .range(start.as_slice()..)
            .map_err(|_| StoreError::Corrupt)?
        {
            let (key, value) = row.map_err(|_| StoreError::Corrupt)?;
            if !key.value().starts_with(&start) {
                break;
            }
            let amount = key.value().len() + value.value().len();
            if out.len() == maximum_rows || amount > maximum_bytes.saturating_sub(bytes) {
                break;
            }
            bytes += amount;
            out.push((
                RowKey {
                    family,
                    key: key.value()[1..].to_vec(),
                },
                value.value().to_vec(),
            ));
        }
        Ok(out)
    }
}
impl Drop for ReadView {
    fn drop(&mut self) {
        drop(self.tx.take());
        self.views.fetch_sub(1, Ordering::AcqRel);
    }
}

#[cfg(test)]
mod tests;
