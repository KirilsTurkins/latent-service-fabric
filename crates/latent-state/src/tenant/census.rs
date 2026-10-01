//! One bounded accumulator over the original producer-validated startup scan.
//! It contains no native owner, host grant, alternate scan or business bytes.
use super::{codec, guard_key, quota_key, row_charge, TenantDelta, TenantQuota, TenantUsage};
use crate::embedded::{Family, ReadView, RowKey, StoreError};
use latent_core::TenantId;
use std::time::{Duration, Instant};

/// Reviewed node metadata capacity, separate from every explicit tenant quota.
/// Only the five closed singleton control keys can consume this allowance.
#[derive(Clone, Copy, Debug)]
pub struct GlobalMetadataAllowance {
    pub rows: u64,
    pub bytes: u64,
}

/// Descriptive codec-owner output, never permission or a replacement ledger.
/// Covered rows are already charged by their original upper reservation/usage
/// ledger; charging them again would erase the meaning of the promised space.
#[derive(Debug)]
pub enum TenantCensusContribution {
    Usage {
        tenant: TenantId,
        usage: TenantUsage,
    },
    Covered {
        tenant: TenantId,
    },
    Global,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct TenantCensusReport {
    pub configuration_digest: [u8; 32],
    pub rows: u64,
    pub logical_bytes: u64,
    pub global_rows: u64,
    pub global_bytes: u64,
}
struct Counter {
    tenant: TenantId,
    original: Vec<u8>,
    expected: TenantUsage,
    observed: TenantUsage,
    seen: bool,
}
pub struct TenantCensus {
    counters: Vec<Counter>,
    guard: Vec<u8>,
    guard_seen: bool,
    allowance: GlobalMetadataAllowance,
    report: TenantCensusReport,
    previous: Option<RowKey>,
    deadline: Instant,
    failed: bool,
}
impl TenantCensus {
    pub fn capture(
        view: &ReadView,
        quotas: &[TenantQuota],
        allowance: GlobalMetadataAllowance,
        deadline: Instant,
    ) -> Result<Self, StoreError> {
        let remaining = deadline.saturating_duration_since(Instant::now());
        if remaining.is_zero()
            || remaining > Duration::from_mins(1)
            || allowance.rows == 0
            || allowance.rows > 5
            || allowance.bytes == 0
            || allowance.bytes > 256 * 1024
        {
            return Err(StoreError::Invalid);
        }
        let configuration_digest = super::require_installation(view, quotas)?;
        let guard = view
            .get_bounded(&guard_key(), super::GUARD_BYTES)?
            .ok_or(StoreError::UnsupportedFormat)?;
        let counters = quotas
            .iter()
            .map(|quota| {
                let captured = codec::capture(view, &quota.tenant)?.ok_or(StoreError::Corrupt)?;
                Ok(Counter {
                    tenant: quota.tenant.clone(),
                    original: captured.bytes,
                    expected: captured.record.usage,
                    observed: TenantUsage::default(),
                    seen: false,
                })
            })
            .collect::<Result<Vec<_>, StoreError>>()?;
        Ok(Self {
            counters,
            guard,
            guard_seen: false,
            allowance,
            report: TenantCensusReport {
                configuration_digest,
                rows: 0,
                logical_bytes: 0,
                global_rows: 0,
                global_bytes: 0,
            },
            previous: None,
            deadline,
            failed: false,
        })
    }

    /// Call exactly once for every row, after that row's installed codec/link
    /// validator succeeds. Any error makes the entire census unusable.
    pub fn observe(
        &mut self,
        key: &RowKey,
        bytes: &[u8],
        contribution: TenantCensusContribution,
    ) -> Result<(), StoreError> {
        if self.failed {
            return Err(StoreError::Corrupt);
        }
        let result = self.observe_inner(key, bytes, contribution);
        if result.is_err() {
            self.failed = true;
        }
        result
    }
    fn observe_inner(
        &mut self,
        key: &RowKey,
        bytes: &[u8],
        contribution: TenantCensusContribution,
    ) -> Result<(), StoreError> {
        self.checkpoint()?;
        if key.key.is_empty() || key.key.len() > 1024 || bytes.len() > 2 * 1024 * 1024 {
            return Err(StoreError::Capacity);
        }
        if self.previous.as_ref().is_some_and(|prior| {
            (prior.family, prior.key.as_slice()) >= (key.family, key.key.as_slice())
        }) {
            return Err(StoreError::Corrupt);
        }
        self.report.rows = self
            .report
            .rows
            .checked_add(1)
            .ok_or(StoreError::Capacity)?;
        self.report.logical_bytes = self
            .report
            .logical_bytes
            .checked_add(row_charge(key, bytes)?)
            .ok_or(StoreError::Capacity)?;
        if self.report.rows > 65_536 || self.report.logical_bytes > 128 * 1024 * 1024 {
            return Err(StoreError::Capacity);
        }
        match contribution {
            TenantCensusContribution::Global => self.global(key, bytes)?,
            TenantCensusContribution::Usage { tenant, usage } => {
                let counter = self.counter(&tenant)?;
                if *key == quota_key(&tenant)? {
                    if counter.seen || counter.original != bytes {
                        return Err(StoreError::Corrupt);
                    }
                    counter.seen = true;
                }
                counter.observed = TenantDelta {
                    added: counter.observed,
                    ..TenantDelta::default()
                }
                .combined(TenantDelta {
                    added: usage,
                    ..TenantDelta::default()
                })?
                .added;
                if !counter.observed.within(counter.expected) {
                    return Err(StoreError::Corrupt);
                }
            }
            TenantCensusContribution::Covered { tenant } => {
                self.counter(&tenant)?;
            }
        }
        self.previous = Some(key.clone());
        Ok(())
    }
    fn counter(&mut self, tenant: &TenantId) -> Result<&mut Counter, StoreError> {
        self.counters
            .iter_mut()
            .find(|counter| counter.tenant == *tenant)
            .ok_or(StoreError::UnsupportedFormat)
    }
    fn global(&mut self, key: &RowKey, bytes: &[u8]) -> Result<(), StoreError> {
        if key.family != Family::Maintenance
            || ![
                super::GUARD_PREFIX,
                crate::recovery::GUARD_KEY,
                b"result-retention-v1\0",
                b"dispatch-owner-v1\0",
                b"dispatch-control-v1\0",
            ]
            .contains(&key.key.as_slice())
        {
            return Err(StoreError::UnsupportedFormat);
        }
        if *key == guard_key() {
            if self.guard_seen || bytes != self.guard {
                return Err(StoreError::Corrupt);
            }
            self.guard_seen = true;
        }
        self.report.global_rows += 1;
        self.report.global_bytes = self
            .report
            .global_bytes
            .checked_add(row_charge(key, bytes)?)
            .ok_or(StoreError::Capacity)?;
        if self.report.global_rows > self.allowance.rows
            || self.report.global_bytes > self.allowance.bytes
        {
            return Err(StoreError::Capacity);
        }
        Ok(())
    }
    fn checkpoint(&self) -> Result<(), StoreError> {
        if Instant::now() >= self.deadline {
            Err(StoreError::Unavailable)
        } else {
            Ok(())
        }
    }
    pub fn finish(self) -> Result<TenantCensusReport, StoreError> {
        self.checkpoint()?;
        if self.failed
            || !self.guard_seen
            || self
                .counters
                .iter()
                .any(|counter| !counter.seen || counter.observed != counter.expected)
        {
            return Err(StoreError::Corrupt);
        }
        Ok(self.report)
    }
}
