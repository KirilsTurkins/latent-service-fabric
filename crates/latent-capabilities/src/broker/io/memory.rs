//! Reservations for already bounded typed host values and protocol state.
//! The adapter stores data before this guard in its owner, or shares the guard
//! with the actual byte owner. This avoids allocating a second dummy byte buffer.
use super::{capacity, Charge, IoAdmission, IoCall, Kind, OperationOwner, PlatformError};

pub struct IoMemory {
    host: Option<latent_core::budget::HostMemoryReservation>,
    _bytes: Charge,
    _metadata: Charge,
    _slot: Charge,
    _operation: OperationOwner,
}
impl IoMemory {
    pub(super) fn reserve(
        operation: &OperationOwner,
        bytes: usize,
        metadata: usize,
    ) -> Result<Self, PlatformError> {
        Self::reserve_inner(operation, bytes, metadata, false)
    }
    pub(super) fn reserve_host(
        operation: &OperationOwner,
        bytes: usize,
        metadata: usize,
    ) -> Result<Self, PlatformError> {
        Self::reserve_inner(operation, bytes, metadata, true)
    }
    fn reserve_inner(
        operation: &OperationOwner,
        bytes: usize,
        metadata: usize,
        host: bool,
    ) -> Result<Self, PlatformError> {
        operation.check()?;
        if bytes == 0 || bytes > operation.runtime.limits.maximum_chunk_bytes {
            return Err(capacity());
        }
        let slot = operation.runtime.counters.acquire(Kind::Buffer, 1)?;
        let meta = operation.runtime.counters.acquire(
            Kind::Metadata,
            metadata.checked_add(512).ok_or_else(capacity)?,
        )?;
        let charge = operation.runtime.counters.acquire(Kind::Staged, bytes)?;
        let native = if host {
            Some(operation.with_session(|session| {
                let bytes = bytes
                    .checked_add(super::ALLOCATION_BOOKKEEPING)
                    .and_then(|n| u64::try_from(n).ok())
                    .ok_or_else(capacity)?;
                session
                    .core
                    .budget
                    .reserve_host_memory(bytes)
                    .map_err(|_| capacity())
            })?)
        } else {
            None
        };
        Ok(Self {
            host: native,
            _bytes: charge,
            _metadata: meta,
            _slot: slot,
            _operation: operation.clone(),
        })
    }
    #[cfg(test)]
    pub(super) fn charged_to(&self, budget: &latent_core::ActivationBudget) -> bool {
        self.host
            .as_ref()
            .is_some_and(|guard| guard.is_from_budget(budget))
    }
    pub(super) fn confirm_host_capacity(
        &mut self,
        capacity_bytes: usize,
    ) -> Result<(), PlatformError> {
        if capacity_bytes == 0 {
            return Ok(());
        }
        if let Some(native) = &mut self.host {
            let bytes = capacity_bytes
                .checked_add(super::ALLOCATION_BOOKKEEPING)
                .and_then(|n| u64::try_from(n).ok())
                .ok_or_else(capacity)?;
            if bytes > native.bytes() {
                return Err(capacity());
            }
            // An unused larger maximum remains reserved, never reported physical.
            native.confirm_bytes(bytes);
        }
        Ok(())
    }
}
impl IoAdmission {
    /// Reserve before retaining/copying a typed request into an asynchronous owner.
    pub fn reserve_input(&self, bytes: usize, metadata: usize) -> Result<IoMemory, PlatformError> {
        IoMemory::reserve(
            self.operation.as_ref().expect("affine admission"),
            bytes,
            metadata,
        )
    }
}
impl IoCall {
    pub fn reserve_scratch(
        &self,
        bytes: usize,
        metadata: usize,
    ) -> Result<IoMemory, PlatformError> {
        IoMemory::reserve(&self.operation, bytes, metadata)
    }
}
