use super::{
    codec, guard_key, quota_key, row_charge, TenantQuota, TenantRecord, TenantUsage, GUARD_BYTES,
    RECORD_BYTES,
};
use crate::embedded::{
    AtomicBatch, EmbeddedStore, ExpectedRow, Family, FencedStoreError, ReadView, RowMutation,
    StoreError,
};

/// Stable exact manifest identity for the finite selected declarations.
pub fn configuration_digest(quotas: &[TenantQuota]) -> Result<[u8; 32], StoreError> {
    Ok(codec::hash(&codec::Guard::new(quotas)?.encode()))
}

/// Installed Phase 4 startup requires the selected declarations even when the
/// lower legacy profile would otherwise allow reads. No limit update or implicit
/// reconstruction is performed on an existing store.
pub fn require_installation(
    view: &ReadView,
    quotas: &[TenantQuota],
) -> Result<[u8; 32], StoreError> {
    let guard = codec::Guard::new(quotas)?.encode();
    if view.get_bounded(&guard_key(), GUARD_BYTES)?.as_deref() != Some(guard.as_slice()) {
        return Err(StoreError::UnsupportedFormat);
    }
    for quota in quotas {
        let captured = codec::capture(view, &quota.tenant)?.ok_or(StoreError::UnsupportedFormat)?;
        if captured.record.quota != *quota {
            return Err(StoreError::UnsupportedFormat);
        }
    }
    Ok(codec::hash(&guard))
}

/// Finite setup before transactional targets admit work. Existing business rows
/// require a separately reviewed accounting migration, never an inferred sum of
/// namespace ceilings. Repeating an exact installation is a read-only success.
pub fn prepare_install(
    view: &ReadView,
    quotas: &[TenantQuota],
) -> Result<PreparedTenantInstallation, StoreError> {
    let guard = codec::Guard::new(quotas)?.encode();
    let digest = codec::hash(&guard);
    if view.get_bounded(&guard_key(), GUARD_BYTES)?.is_some() {
        require_installation(view, quotas)?;
        return Ok(PreparedTenantInstallation {
            batch: AtomicBatch::default(),
            digest,
            quotas: quotas.to_vec(),
            new: false,
        });
    }
    require_no_business_rows(view)?;
    let mut batch = AtomicBatch {
        expectations: vec![ExpectedRow {
            key: guard_key(),
            value: None,
        }],
        mutations: vec![RowMutation {
            key: guard_key(),
            value: Some(guard),
        }],
    };
    for quota in quotas {
        let key = quota_key(&quota.tenant)?;
        if view.get(&key)?.is_some() {
            return Err(StoreError::Corrupt);
        }
        let usage = TenantUsage {
            metadata_rows: 1,
            metadata_bytes: row_charge(&key, &[0; RECORD_BYTES])?,
            ..TenantUsage::default()
        };
        if !usage.within(quota.limits) {
            return Err(StoreError::Capacity);
        }
        let record = TenantRecord {
            quota: quota.clone(),
            generation: 1,
            usage,
        };
        batch.expectations.push(ExpectedRow {
            key: key.clone(),
            value: None,
        });
        batch.mutations.push(RowMutation {
            key,
            value: Some(record.encode()?),
        });
    }
    Ok(PreparedTenantInstallation {
        batch,
        digest,
        quotas: quotas.to_vec(),
        new: true,
    })
}

pub struct PreparedTenantInstallation {
    batch: AtomicBatch,
    digest: [u8; 32],
    quotas: Vec<TenantQuota>,
    new: bool,
}
impl PreparedTenantInstallation {
    #[must_use]
    pub const fn configuration_digest(&self) -> [u8; 32] {
        self.digest
    }
    #[must_use]
    pub const fn is_new(&self) -> bool {
        self.new
    }
    /// The original worker reserves this fixed upper bound; no private worker
    /// or dynamically enlarged recovery pool is created by installation.
    #[must_use]
    pub const fn retained_bytes(&self) -> usize {
        GUARD_BYTES * 3 + RECORD_BYTES * 32 * 4
    }
    #[must_use]
    pub fn batch(&self) -> &AtomicBatch {
        &self.batch
    }

    /// Publish only on the existing reserved native writer. The final check
    /// takes a SHORT real snapshot while that original writer is already held:
    /// any business commit racing the empty preparation refuses installation.
    /// A legacy business batch prepared before setup also captures absent guard
    /// bytes, so cannot later commit across the newly installed profile.
    ///
    /// # Errors
    /// Current review, source rows, installation or actual physical I/O may fail.
    /// A failed/uncertain write never reports successful setup.
    pub fn publish<E>(
        self,
        store: &EmbeddedStore,
        accept: impl FnOnce() -> Result<(), E>,
    ) -> Result<[u8; 32], FencedStoreError<E>> {
        if !self.new {
            let view = store.snapshot()?;
            require_installation(&view, &self.quotas)?;
            drop(view);
            accept().map_err(FencedStoreError::Fence)?;
            return Ok(self.digest);
        }
        store
            .apply_fenced(self.batch, || {
                let view = store.snapshot().map_err(InstallationFence::Store)?;
                require_no_business_rows(&view).map_err(InstallationFence::Store)?;
                drop(view);
                accept().map_err(InstallationFence::Host)
            })
            .map_err(|error| match error {
                FencedStoreError::Store(error)
                | FencedStoreError::Fence(InstallationFence::Store(error)) => {
                    FencedStoreError::Store(error)
                }
                FencedStoreError::Fence(InstallationFence::Host(error)) => {
                    FencedStoreError::Fence(error)
                }
            })?;
        Ok(self.digest)
    }
}

enum InstallationFence<E> {
    Store(StoreError),
    Host(E),
}

fn require_no_business_rows(view: &ReadView) -> Result<(), StoreError> {
    for family in [
        Family::Namespace,
        Family::State,
        Family::Tombstone,
        Family::Command,
        Family::Result,
        Family::Outbox,
        Family::Attempt,
        Family::Inbox,
        Family::PayloadReference,
    ] {
        if view.contains_prefix(family, &[])? {
            return Err(StoreError::UnsupportedFormat);
        }
    }
    for prefix in [
        crate::reservation::QUOTA_PREFIX,
        crate::reservation::KEY_PREFIX,
        b"state-usage-v1\0",
        super::QUOTA_PREFIX,
    ] {
        if view.contains_prefix(Family::Maintenance, prefix)? {
            return Err(StoreError::UnsupportedFormat);
        }
    }
    Ok(())
}
