//! Finite physical compaction on the original engine and file backend.
use super::{EmbeddedStore, ExpectedRow, FencedStoreError, StoreError, META, ROWS};
use redb::{Database, ReadableDatabase};
use std::sync::{atomic::Ordering, TryLockError};
use std::time::{Duration, Instant};

/// Installed host bounds, never a promise to interrupt a blocked native call.
/// The original worker/permit stays alive until that call physically returns.
#[derive(Clone, Copy, Debug)]
pub struct CompactionLimits {
    pub deadline: Instant,
    pub maximum_read_bytes: u64,
    pub maximum_write_bytes: u64,
    pub maximum_io_operations: u64,
    /// Caller reserves this entire allowance through the original worker.
    pub maximum_scratch_bytes: u64,
    /// Maximum additional space in this same database file; no scratch file.
    pub maximum_growth_bytes: u64,
}
impl CompactionLimits {
    pub(super) fn validate(self) -> Result<(), StoreError> {
        let now = Instant::now();
        if self.deadline <= now
            || self.deadline.duration_since(now) > Duration::from_secs(5)
            || self.maximum_read_bytes == 0
            || self.maximum_read_bytes > 256 * 1024 * 1024
            || self.maximum_write_bytes == 0
            || self.maximum_write_bytes > 256 * 1024 * 1024
            || self.maximum_io_operations == 0
            || self.maximum_io_operations > 8192
            || self.maximum_scratch_bytes < 256 * 1024
            || self.maximum_scratch_bytes > 64 * 1024 * 1024
            || self.maximum_growth_bytes > 64 * 1024 * 1024
        {
            return Err(StoreError::Invalid);
        }
        Ok(())
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum CompactionStop {
    PreflightRefusal,
    ReadBudget,
    WriteBudget,
    OperationBudget,
    GrowthBudget,
    Deadline,
    PhysicalFailure,
}

/// A fixed last observation. Bytes/operations charge attempted native I/O;
/// failed calls cannot claim how many bytes a device actually transferred.
/// File observations come from successful descriptor operations. Any failure
/// refuses normal engine use until the actual protected owner is recovered.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct CompactionReport {
    pub engine_started: bool,
    pub engine_completed: bool,
    /// Unknown after interruption; never infer unchanged from an error.
    pub changed: Option<bool>,
    pub stop: Option<CompactionStop>,
    pub read_bytes: u64,
    pub write_bytes: u64,
    pub io_operations: u64,
    pub file_bytes_before: u64,
    pub observed_file_bytes: u64,
    pub peak_file_bytes: u64,
    pub elapsed_micros: u64,
    /// Conservative source-derived requirement, not a measured allocation.
    pub scratch_requirement_bytes: u64,
    /// Descriptive bound; the actual worker supplies its retained reservation.
    pub scratch_limit_bytes: u64,
}

impl EmbeddedStore {
    /// Rechecks bounded exact rows and the host's short current-policy fence
    /// while retaining exclusive access to the same engine. Native views must
    /// actually be destroyed; their elapsed deadlines supply no retirement.
    /// The bounded backend refuses new I/O/growth at the declared limits.
    ///
    /// # Errors
    /// Refuses invalid bounds, an uninstrumented backend, live readers/writers,
    /// stale rows or failed host acceptance before compaction. An interrupted,
    /// failed or late physical operation quarantines this original engine and
    /// returns uncertain completion; no clean shutdown or logical GC is claimed.
    pub fn compact_fenced<E>(
        &self,
        limits: CompactionLimits,
        expectations: &[ExpectedRow],
        accept: impl FnOnce() -> Result<(), E>,
    ) -> Result<CompactionReport, FencedStoreError<E>> {
        limits.validate()?;
        if self.quarantined.load(Ordering::Acquire) {
            return Err(StoreError::Unavailable.into());
        }
        let status = self
            .file_status
            .as_ref()
            .ok_or(StoreError::UnsupportedFormat)?;
        if expectations.len() > 8 {
            return Err(StoreError::Capacity.into());
        }
        let mut bytes = 0usize;
        let mut keys = std::collections::BTreeSet::new();
        for expected in expectations {
            self.validate_row(
                &expected.key,
                expected.value.as_deref(),
                &mut keys,
                &mut bytes,
            )?;
            if bytes > 64 * 1024 {
                return Err(StoreError::Capacity.into());
            }
        }
        if self
            .reclamation
            .compare_exchange(false, true, Ordering::SeqCst, Ordering::SeqCst)
            .is_err()
        {
            return Err(StoreError::Capacity.into());
        }
        let _admission = super::ReclamationGate(&self.reclamation);
        if self.live_views() != 0 {
            return Err(StoreError::Capacity.into());
        }
        let mut database = match self.db.try_write() {
            Ok(database) => database,
            Err(TryLockError::WouldBlock) => return Err(StoreError::Capacity.into()),
            Err(TryLockError::Poisoned(_)) => return Err(StoreError::Unavailable.into()),
        };
        // The same I/O allowance includes the final engine-row/format checks;
        // do not hide cold-page reads outside the declared compaction budget.
        let mut lease = status.begin_compaction(limits)?;
        if let Err(error) = compaction_rows(&database, self.limits, expectations) {
            let report = lease.finish(false, Some(false));
            if error != StoreError::Conflict
                || report.stop != Some(CompactionStop::PreflightRefusal)
            {
                self.quarantined.store(true, Ordering::Release);
            }
            return Err(error.into());
        }
        if let Err(error) = accept() {
            lease.finish(false, Some(false));
            return Err(FencedStoreError::Fence(error));
        }
        lease.started();
        // A panic or interrupted engine return must also hold the engine. The
        // original worker catches panics; its live permit is never stolen.
        let mut completion = CompactionCompletion {
            quarantine: &self.quarantined,
            completed: false,
        };
        let result = database.compact();
        let report = lease.finish(result.is_ok(), result.as_ref().ok().copied());
        if result.is_err() || report.stop.is_some() {
            return Err(StoreError::CommitUncertain.into());
        }
        completion.completed = true;
        Ok(report)
    }
}

fn compaction_rows(
    database: &Database,
    limits: super::StoreLimits,
    expectations: &[ExpectedRow],
) -> Result<(), StoreError> {
    let transaction = database.begin_read().map_err(|_| StoreError::Unavailable)?;
    let meta = transaction
        .open_table(META)
        .map_err(|_| StoreError::Corrupt)?;
    if meta
        .get("schema")
        .map_err(|_| StoreError::Corrupt)?
        .is_none_or(|row| row.value() != super::FORMAT)
    {
        return Err(StoreError::UnsupportedFormat);
    }
    let table = transaction
        .open_table(ROWS)
        .map_err(|_| StoreError::Corrupt)?;
    for expected in expectations {
        let key = expected.key.encoded(limits)?;
        let actual = table.get(key.as_slice()).map_err(|_| StoreError::Corrupt)?;
        if actual.as_ref().map(redb::AccessGuard::value) != expected.value.as_deref() {
            return Err(StoreError::Conflict);
        }
    }
    Ok(())
}

struct CompactionCompletion<'a> {
    quarantine: &'a std::sync::atomic::AtomicBool,
    completed: bool,
}
impl Drop for CompactionCompletion<'_> {
    fn drop(&mut self) {
        if !self.completed {
            self.quarantine.store(true, Ordering::Release);
        }
    }
}
