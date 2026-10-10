//! Original global memory prepaid before protected initialization can allocate.
use std::sync::Arc;

use latent_core::native_capacity::{
    NativeAdmissionClass, NativeBufferClass, NativeBufferPermit, NativeCapacityError,
    NativeCapacityOwner, NativeReservation,
};

use super::native_capacity::NativeBinding;
use super::{ProtectedStoreConfig, ProtectedStoreError};
use crate::embedded::StoreError;
use crate::store_io::StoreIoError;

#[cfg(test)]
mod tests;

pub(super) struct StartupMemorySize {
    pub initialization: u64,
    pub resident: u64,
    pub total: u64,
}

impl ProtectedStoreConfig {
    /// Checked native Work needed before reserving the original Recovery
    /// admission. This is sizing metadata; it creates no owner or permission.
    /// Resident bytes remain occupied until the engine and protected descriptors
    /// physically retire, so the configured Recovery partition must also retain
    /// capacity for the node's bounded recovery operations.
    pub fn startup_memory_bytes(
        &self,
        validator_retained_bytes: u64,
    ) -> Result<u64, ProtectedStoreError> {
        Ok(startup_memory_size(self, validator_retained_bytes)?.total)
    }
}

pub(super) fn startup_memory_size(
    config: &ProtectedStoreConfig,
    validator_retained_bytes: u64,
) -> Result<StartupMemorySize, ProtectedStoreError> {
    let initialization = config
        .validate()?
        .checked_add(8 * 1024 * 1024)
        .and_then(|bytes| bytes.checked_add(validator_retained_bytes))
        .and_then(|bytes| bytes.checked_add(4096))
        .ok_or(ProtectedStoreError::InvalidConfiguration)?;
    let total = initialization
        .checked_add(config.io.resident_bytes)
        .ok_or(ProtectedStoreError::InvalidConfiguration)?;
    if initialization > config.io.job_bytes || total > config.io.retained_bytes {
        return Err(ProtectedStoreError::InvalidConfiguration);
    }
    Ok(StartupMemorySize {
        initialization,
        resident: config.io.resident_bytes,
        total,
    })
}

/// Affine startup admission from the node's existing global owner. No default
/// owner, refreshed deadline, ordinary admission or foreign reservation can be
/// substituted for this original Recovery reservation.
pub struct ProtectedStoreStartupMemory {
    owner: NativeCapacityOwner,
    reservation: Arc<NativeReservation>,
}

impl ProtectedStoreStartupMemory {
    pub fn new(
        owner: &NativeCapacityOwner,
        reservation: Arc<NativeReservation>,
    ) -> Result<Self, ProtectedStoreError> {
        if !reservation.is_from_owner(owner)
            || reservation.class() != NativeAdmissionClass::Recovery
        {
            return Err(ProtectedStoreError::InvalidConfiguration);
        }
        reservation.with_live(|| ()).map_err(memory_error)?;
        Ok(Self {
            owner: owner.clone(),
            reservation,
        })
    }

    pub(super) fn prepare(
        self,
        size: &StartupMemorySize,
    ) -> Result<PreparedStartupMemory, ProtectedStoreError> {
        if self.reservation.work_bytes() < size.total {
            return Err(ProtectedStoreError::Store(StoreError::Capacity));
        }
        // Both affine subreservations precede worker, descriptor and engine
        // allocations. Refusal rolls back only these unused subreservations;
        // another real buffer on the original ledger remains charged.
        let initialization = self
            .reservation
            .reserve_buffer(NativeBufferClass::Work, size.initialization)
            .map_err(memory_error)?;
        let resident = self
            .reservation
            .reserve_buffer(NativeBufferClass::Work, size.resident)
            .map_err(memory_error)?;
        Ok(PreparedStartupMemory {
            binding: Arc::new(NativeBinding::bound(self.owner)),
            original: Arc::clone(&self.reservation),
            initialization: InitializationMemory {
                _permit: initialization,
                original: Arc::clone(&self.reservation),
            },
            resident: ResidentMemory {
                _permit: resident,
                _original: self.reservation,
            },
        })
    }
}

pub(super) struct PreparedStartupMemory {
    pub binding: Arc<NativeBinding>,
    pub original: Arc<NativeReservation>,
    pub initialization: InitializationMemory,
    pub resident: ResidentMemory,
}

pub(super) struct InitializationMemory {
    _permit: NativeBufferPermit,
    original: Arc<NativeReservation>,
}

impl InitializationMemory {
    /// A short original gate only; no lock is retained across native I/O.
    pub fn check(&self) -> Result<(), ProtectedStoreError> {
        self.original.with_live(|| ()).map_err(memory_error)
    }
}

/// This is the LAST PhysicalStore field. The original admission remains live
/// until engine, root, mutable descriptors and exclusive lock destruction.
pub(super) struct ResidentMemory {
    _permit: NativeBufferPermit,
    _original: Arc<NativeReservation>,
}

pub(super) fn memory_error(error: NativeCapacityError) -> ProtectedStoreError {
    match error {
        NativeCapacityError::AdmissionClosed | NativeCapacityError::DeadlineExceeded => {
            ProtectedStoreError::Io(StoreIoError::AdmissionClosed)
        }
        NativeCapacityError::Quarantined | NativeCapacityError::Poisoned => {
            ProtectedStoreError::Io(StoreIoError::RecoveryRequired)
        }
        _ => ProtectedStoreError::Store(StoreError::Capacity),
    }
}
