//! Exclusive stopped-owner maintenance. No worker, replay or ordinary audit
//! reservation is created here. Archive custody is separate from mutation authority.
mod model;
mod rollover;
mod storage;
mod transfer;
#[cfg(all(test, unix))]
mod tests;

use super::{codec, corrupt, io, AuditLimits, AuditQueryRequest, Mode, Result, Store};
use latent_core::PlatformErrorCode;
use std::{path::Path, time::{Duration, Instant}};
pub(super) use model::EpochLink;
pub use model::{AuditArchiveCoverage, AuditRolloverReceipt, AuditTransferReceipt};

/// All maintenance is synchronous and holds the actual filesystem owners until
/// I/O returns. A deadline does not pretend a blocked physical owner has stopped.
/// The caller must be the journal's effective-UID filesystem operator. These
/// APIs are not a tenant RPC and do not derive authorization from archive bytes.
pub struct AuditMaintenance;

/// One bounded, explicitly selected sealed epoch. It is not complete history.
/// Records and cursors confer no management or mutation authority.
pub struct AuditArchivePage {
    pub records: Vec<super::AuditStoredRecord>,
    pub coverage: super::AuditPageCoverage,
    pub next_cursor: Option<super::AuditCursor>,
    pub archive: AuditArchiveCoverage,
}

impl AuditMaintenance {
    /// Seal and verify the old epoch before switching the existing locked root.
    /// Reuse the original operation and expected epoch after an interrupted call.
    pub fn rollover(
        journal: &Path,
        custody: &Path,
        expected_epoch: &str,
        operation_id: &str,
        timeout: Duration,
    ) -> Result<AuditRolloverReceipt> {
        let deadline = Deadline::new(timeout)?;
        identity(expected_epoch)?;
        identity(operation_id)?;
        rollover::run(journal, custody, expected_epoch, operation_id, deadline)
    }

    /// Transfer the oldest local archive into one explicit operator-held target.
    /// Local capacity is released only after the target is durably verified.
    pub fn transfer(
        journal: &Path,
        custody: &Path,
        destination: &Path,
        epoch: &str,
        expected_seal: &str,
        operation_id: &str,
        timeout: Duration,
    ) -> Result<AuditTransferReceipt> {
        let deadline = Deadline::new(timeout)?;
        identity(epoch)?;
        identity(operation_id)?;
        if !codec::hex(expected_seal, 64) { return Err(super::super::invalid()); }
        transfer::run(journal, custody, destination, epoch, expected_seal, operation_id, deadline)
    }

    /// Verify a single explicitly selected archive, without changing its bytes.
    pub fn verify_archive(
        archive: &Path,
        expected_epoch: &str,
        timeout: Duration,
    ) -> Result<AuditArchiveCoverage> {
        let deadline = Deadline::new(timeout)?;
        identity(expected_epoch)?;
        let (store, seal) = storage::archive(archive, deadline)?;
        if seal.epoch != expected_epoch { return Err(super::super::invalid()); }
        deadline.check()?;
        let _owner = store;
        seal.coverage()
    }

    /// Filesystem-operator history query. The existing authenticated live audit
    /// service remains scoped separately; this method never supplies RPC claims.
    pub fn query_archive(
        archive: &Path,
        expected_epoch: &str,
        query: &AuditQueryRequest,
        timeout: Duration,
    ) -> Result<AuditArchivePage> {
        let deadline = Deadline::new(timeout)?;
        identity(expected_epoch)?;
        validate_query(query)?;
        let (store, seal) = storage::archive(archive, deadline)?;
        if seal.epoch != expected_epoch { return Err(super::super::invalid()); }
        let (records, coverage, next_cursor) = store.query_with_custody(
            query, deadline.0, 0, |_| Ok(()),
        )?;
        deadline.check()?;
        Ok(AuditArchivePage { records, coverage, next_cursor, archive: seal.coverage()? })
    }
}

fn validate_query(query: &AuditQueryRequest) -> Result<()> {
    codec::scope(&query.scope)?;
    if let Some(actor) = &query.filter.actor { codec::token(actor, 512)?; }
    if query.limit == 0 || query.limit > 128
        || !(32768..=262144).contains(&query.maximum_bytes)
        || query.cursor.as_ref().is_some_and(|c| c.0.len() > 256)
        || query.filter.from_unix_millis.zip(query.filter.to_unix_millis).is_some_and(|(a,b)| a > b)
    { return Err(super::super::invalid()); }
    Ok(())
}

#[derive(Clone, Copy)]
struct Deadline(Instant);
impl Deadline {
    fn new(timeout: Duration) -> Result<Self> {
        if timeout.is_zero() || timeout > Duration::from_secs(120) {
            return Err(super::super::invalid());
        }
        Ok(Self(Instant::now().checked_add(timeout).ok_or_else(corrupt)?))
    }
    fn check(self) -> Result<()> {
        if Instant::now() >= self.0 {
            return Err(failure(PlatformErrorCode::DeadlineExceeded, "audit-maintenance-deadline"));
        }
        Ok(())
    }
}
fn failure(code: PlatformErrorCode, reason: &'static str) -> latent_core::PlatformError {
    super::super::error(code, reason)
}
fn identity(value: &str) -> Result<()> {
    if !codec::hex(value, 32) { return Err(super::super::invalid()); }
    Ok(())
}
fn archive_limits() -> Result<AuditLimits> {
    AuditLimits {
        maximum_records: 16384,
        maximum_disk_bytes: 256 * 1024 * 1024,
        maximum_metadata_bytes: 32 * 1024 * 1024,
        ..AuditLimits::default()
    }.validate()
}

pub(super) fn epoch_state(mode: &Mode) -> Result<(u64, String, u64)> {
    if !codec::hex(&mode.epoch, 32) || mode.retention != "reject-new" {
        return Err(corrupt());
    }
    match (mode.format_version, &mode.lineage) {
        (1, None) => Ok((1, "0".repeat(64), 0)),
        (2, Some(link)) => {
            link.validate(&mode.epoch)?;
            if !mode.initialized { return Err(corrupt()); }
            Ok((link.first_sequence, link.previous_head.clone(), link.unknown_outcomes_before))
        }
        _ => Err(corrupt()),
    }
}

pub(super) fn guard_open(root: &io::Root) -> Result<()> {
    if io::present(&root.path.join("ROLLOVER"))? || io::present(&root.path.join("TRANSFER"))? {
        return Err(failure(PlatformErrorCode::Unavailable, "audit-maintenance-resume-required"));
    }
    Ok(())
}

#[cfg(test)]
thread_local! { static FAIL: std::cell::Cell<u8> = const { std::cell::Cell::new(0) }; }
#[cfg_attr(not(test), expect(clippy::unnecessary_wraps, reason = "Production cutpoints are fallible only in interruption qualification"))]
fn cut(point: u8) -> Result<()> {
    #[cfg(not(test))]
    let _ = point;
    #[cfg(test)]
    if FAIL.with(|f| { if f.get() == point { f.set(0); true } else { false } }) {
        return Err(super::super::unavailable());
    }
    Ok(())
}
