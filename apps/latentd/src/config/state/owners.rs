//! Explicit finite node ceilings. None of these declarations grants authority.
use std::{path::PathBuf, time::Duration};

use latent_core::{
    native_capacity::{
        NativeCapacityLimits, NativeCapacityPartition, NATIVE_RESERVATION_METADATA_BYTES,
    },
    PlatformError,
};
use latent_effects::runtime::{DispatchOrdering, DispatcherConfig};
use latent_state::{
    protected_store::ProtectedStoreConfig,
    store_io::{StoreIoLimits, StoreIoRecoveryLimits},
};

const MIB: u64 = 1024 * 1024;

configuration_object! {
#[derive(Clone)]
pub struct StorageWorkerConfig {
    pub workers: usize,
    pub queued_jobs: usize,
    pub accepted_jobs: usize,
    pub active_reads: usize,
    pub retained_bytes: u64,
    pub maximum_job_bytes: u64,
}
}

configuration_object! {
#[derive(Clone)]
pub struct StorageRecoveryConfig {
    pub workers: usize,
    pub queued_jobs: usize,
    pub accepted_jobs: usize,
    pub retained_bytes: u64,
    pub maximum_job_bytes: u64,
}
}

configuration_object! {
#[derive(Clone)]
pub struct StorageLimitsConfig {
    pub maximum_file_bytes: u64,
    pub cache_bytes: usize,
    pub maximum_rows: usize,
    pub maximum_logical_bytes: usize,
    pub maximum_read_views: usize,
    pub maximum_view_age_millis: u64,
    pub ordinary: StorageWorkerConfig,
    pub recovery: StorageRecoveryConfig,
}
}

impl StorageLimitsConfig {
    pub(super) fn derive(
        &self,
        root: PathBuf,
        create: bool,
    ) -> Result<ProtectedStoreConfig, PlatformError> {
        let ordinary = &self.ordinary;
        let recovery = &self.recovery;
        if !(2 * MIB..=1024 * MIB).contains(&self.maximum_file_bytes)
            || !(1024 * 1024..=64 * 1024 * 1024).contains(&self.cache_bytes)
            || !(1..=65_536).contains(&self.maximum_rows)
            || !(1..=128 * 1024 * 1024).contains(&self.maximum_logical_bytes)
            || !(1..=32).contains(&self.maximum_read_views)
            || !(1..=60_000).contains(&self.maximum_view_age_millis)
            || !(2..=16).contains(&ordinary.workers)
            || !(1..=256).contains(&ordinary.queued_jobs)
            || !(ordinary.queued_jobs..=1024).contains(&ordinary.accepted_jobs)
            || !(1..ordinary.workers).contains(&ordinary.active_reads)
            || !(64 * MIB..=512 * MIB).contains(&ordinary.retained_bytes)
            || !(40 * MIB..=ordinary.retained_bytes).contains(&ordinary.maximum_job_bytes)
            || !(1..=4).contains(&recovery.workers)
            || !(4..=64).contains(&recovery.queued_jobs)
            || !(recovery.queued_jobs.max(8)..=128).contains(&recovery.accepted_jobs)
            || !(16 * MIB..=128 * MIB).contains(&recovery.retained_bytes)
            || !(8 * MIB + 8192..=recovery.retained_bytes).contains(&recovery.maximum_job_bytes)
        {
            return Err(invalid("store"));
        }
        let resident_bytes = u64::try_from(self.cache_bytes)
            .map_err(|_| invalid("store"))?
            .checked_add(256 * 1024)
            .ok_or_else(|| invalid("store"))?;
        if ordinary
            .maximum_job_bytes
            .checked_add(resident_bytes)
            .is_none_or(|bytes| bytes > ordinary.retained_bytes)
        {
            return Err(invalid("store"));
        }
        let mut config = ProtectedStoreConfig::bounded_linux(root);
        config.create_if_missing = create;
        config.maximum_file_bytes = self.maximum_file_bytes;
        config.engine.cache_bytes = self.cache_bytes;
        config.engine.maximum_rows = self.maximum_rows;
        config.engine.maximum_logical_bytes = self.maximum_logical_bytes;
        config.engine.maximum_read_views = self.maximum_read_views;
        config.engine.maximum_view_age = Duration::from_millis(self.maximum_view_age_millis);
        // Production framing must represent the closed 1024-byte guest key,
        // namespace/entity framing and full 128-intent atomic envelope. These
        // internal format ceilings cannot be downgraded by configuration.
        config.engine.maximum_key_bytes = 4096;
        config.engine.maximum_value_bytes = 2 * 1024 * 1024;
        config.engine.maximum_batch_rows = 1024;
        config.io = StoreIoLimits {
            recovery: Some(StoreIoRecoveryLimits {
                workers: recovery.workers,
                queued_jobs: recovery.queued_jobs,
                accepted_jobs: recovery.accepted_jobs,
                retained_bytes: recovery.retained_bytes,
                job_bytes: recovery.maximum_job_bytes,
            }),
            workers: ordinary.workers + recovery.workers,
            queued_jobs: ordinary.queued_jobs,
            accepted_jobs: ordinary.accepted_jobs,
            active_reads: ordinary.active_reads,
            active_writes: 1,
            retained_bytes: ordinary
                .retained_bytes
                .checked_add(recovery.retained_bytes)
                .ok_or_else(|| invalid("store"))?,
            job_bytes: ordinary.maximum_job_bytes,
            resident_bytes,
        };
        Ok(config)
    }
}

configuration_object! {
#[derive(Clone)]
pub struct NativePartitionConfig {
    pub slots: usize,
    pub bytes: u64,
    pub maximum_reservation_bytes: u64,
}
}

configuration_object! {
#[derive(Clone)]
pub struct NativeLimitsConfig {
    pub ordinary: NativePartitionConfig,
    pub recovery: NativePartitionConfig,
    pub maximum_lifetime_millis: u64,
}
}

impl Default for NativeLimitsConfig {
    fn default() -> Self {
        // Deserialization still requires every partition/ceiling explicitly.
        // This reviewed construction profile reserves room for the retained
        // startup owner and a full supported recovery operation together.
        Self {
            ordinary: NativePartitionConfig {
                slots: 128,
                bytes: 256 * MIB,
                maximum_reservation_bytes: 64 * MIB,
            },
            recovery: NativePartitionConfig {
                slots: 8,
                bytes: 96 * MIB,
                maximum_reservation_bytes: 32 * MIB,
            },
            maximum_lifetime_millis: 180_000,
        }
    }
}

impl NativeLimitsConfig {
    pub(super) fn derive(&self, startup: Duration) -> Result<NativeCapacityLimits, PlatformError> {
        if !(1..=1024).contains(&self.ordinary.slots)
            || !(1..=128).contains(&self.recovery.slots)
            || !(32 * MIB..=4096 * MIB).contains(&self.ordinary.bytes)
            || !(32 * MIB..=512 * MIB).contains(&self.recovery.bytes)
            || !(1..=3_600_000).contains(&self.maximum_lifetime_millis)
            || Duration::from_millis(self.maximum_lifetime_millis) < startup
            || [&self.ordinary, &self.recovery]
                .into_iter()
                .any(|partition| {
                    !(32 * MIB..=partition.bytes).contains(&partition.maximum_reservation_bytes)
                })
        {
            return Err(invalid("native"));
        }
        let partition = |input: &NativePartitionConfig| NativeCapacityPartition {
            slots: input.slots,
            bytes: input.bytes,
            maximum_reservation_bytes: input.maximum_reservation_bytes,
        };
        Ok(NativeCapacityLimits {
            ordinary: partition(&self.ordinary),
            recovery: partition(&self.recovery),
            maximum_lifetime: Duration::from_millis(self.maximum_lifetime_millis),
        })
    }
}

/// Check the actual producer envelopes before accepting startup capacity.
/// The resident original admission occupies one Recovery slot for the store's
/// physical lifetime, even after its initialization deadline has expired.
pub(super) fn startup_footprint(
    store: &ProtectedStoreConfig,
    native: NativeCapacityLimits,
) -> Result<u64, PlatformError> {
    let work = store
        .startup_memory_bytes(super::STARTUP_VALIDATOR_BYTES)
        .map_err(|_| invalid("store"))?
        .checked_add(super::STARTUP_APPLICATION_BYTES)
        .ok_or_else(|| invalid("native"))?;
    let namespace_bytes =
        latent_state::namespace::lifecycle::NamespaceLifecycleRegistry::retained_memory_bytes(
            latent_state::namespace::lifecycle::NamespaceLifecycleLimits::default(),
        )
        .map_err(|_| invalid("native"))?;
    // Initializer pages are physically destroyed before this metadata owner
    // allocates. Its fixed resident Work reuses that same original admission;
    // engine residency and the application shell continue to occupy theirs.
    if store
        .io
        .resident_bytes
        .checked_add(namespace_bytes)
        .and_then(|bytes| bytes.checked_add(super::STARTUP_APPLICATION_BYTES))
        .is_none_or(|resident| resident > work)
    {
        return Err(invalid("native"));
    }
    let startup = work
        .checked_add(NATIVE_RESERVATION_METADATA_BYTES)
        .ok_or_else(|| invalid("native"))?;
    // Existing NativeTransactionAdmission prepays four staging copies, its
    // 16 MiB native working set, both original request copies and eight value
    // copies for the terminal Wire/body/frame owner. Keep source constants in
    // the formula so a format-ceiling change cannot silently undercharge it.
    let ordinary = 4_u64
        .checked_mul(latent_core::transaction_contract::STAGED_BYTES as u64)
        .and_then(|bytes| bytes.checked_add(16 * MIB))
        .and_then(|bytes| {
            bytes.checked_add(2 * latent_rpc::phase4::MAX_REQUEST_BYTES as u64 + 2 * MIB)
        })
        .and_then(|bytes| {
            bytes.checked_add(8 * latent_core::transaction_contract::VALUE_BYTES as u64 + 16384)
        })
        .and_then(|bytes| bytes.checked_add(NATIVE_RESERVATION_METADATA_BYTES))
        .ok_or_else(|| invalid("native"))?;
    // The public recovery backend owns four request/frame copies, a real 8 MiB
    // coherent native page/decoder job and finite 48 KiB framing metadata. Its
    // existing 32 MiB inclusive admission ceiling covers that exact envelope.
    let recovery = 32 * MIB;
    let headroom = startup
        .checked_add(recovery)
        .ok_or_else(|| invalid("native"))?;
    if native.ordinary.maximum_reservation_bytes < ordinary
        || native.ordinary.bytes < ordinary
        || native.recovery.slots < 2
        || native.recovery.maximum_reservation_bytes < startup.max(recovery)
        || native.recovery.bytes < headroom
    {
        return Err(invalid("native"));
    }
    Ok(work)
}

configuration_object! {
#[derive(Clone)]
pub struct DispatcherLimitsConfig {
    pub workers: usize,
    pub queued_jobs: usize,
    pub accepted_jobs: usize,
    pub maximum_command_owners: usize,
    pub per_tenant_jobs: usize,
    pub retained_bytes: u64,
    pub page_rows: usize,
    pub page_bytes: usize,
    pub scan_pages_per_tick: usize,
    pub poll_interval_millis: u64,
}
}

impl DispatcherLimitsConfig {
    pub(super) fn derive(&self) -> Result<DispatcherConfig, PlatformError> {
        if !(1..=16).contains(&self.workers)
            || !(1..=64).contains(&self.queued_jobs)
            || !(self.queued_jobs.max(self.workers)..=128).contains(&self.accepted_jobs)
            || !(1..=1024).contains(&self.maximum_command_owners)
            || !(1..=self.workers).contains(&self.per_tenant_jobs)
            || !(20 * MIB..=512 * MIB).contains(&self.retained_bytes)
            || !(1..=64).contains(&self.page_rows)
            || !(4096..=4 * 1024 * 1024).contains(&self.page_bytes)
            || !(1..=16).contains(&self.scan_pages_per_tick)
            || !(1..=60_000).contains(&self.poll_interval_millis)
        {
            return Err(invalid("dispatcher"));
        }
        Ok(DispatcherConfig {
            workers: self.workers,
            queued_jobs: self.queued_jobs,
            accepted_jobs: self.accepted_jobs,
            maximum_command_owners: self.maximum_command_owners,
            per_tenant_jobs: self.per_tenant_jobs,
            retained_bytes: self.retained_bytes,
            page_rows: self.page_rows,
            page_bytes: self.page_bytes,
            scan_pages_per_tick: self.scan_pages_per_tick,
            poll_interval: Duration::from_millis(self.poll_interval_millis),
            ordering: DispatchOrdering::Unordered,
            start_paused: true,
            start_in_restore_review: false,
        })
    }
}

fn invalid(field: &'static str) -> PlatformError {
    super::super::invalid(match field {
        "store" => "state.store",
        "native" => "state.native",
        "dispatcher" => "state.dispatcher",
        _ => "state.owners",
    })
}

#[cfg(test)]
pub(super) mod tests;
