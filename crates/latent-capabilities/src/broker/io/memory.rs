//! Reservations for already bounded typed host values and protocol state.
//! The adapter stores data before this guard in its owner, or shares the guard
//! with the actual byte owner. This avoids allocating a second dummy byte buffer.
use super::{capacity, Charge, IoAdmission, IoCall, Kind, Operation, PlatformError};
use std::sync::Arc;

pub struct IoMemory {
    host: Option<latent_core::budget::HostMemoryReservation>,
    _bytes: Charge,
    _metadata: Charge,
    _slot: Charge,
    _operation: Arc<Operation>,
}
impl IoMemory {
    pub(super) fn reserve(
        operation: &Arc<Operation>,
        bytes: usize,
        metadata: usize,
    ) -> Result<Self, PlatformError> {
        Self::reserve_inner(operation, bytes, metadata, false)
    }
    pub(super) fn reserve_host(
        operation: &Arc<Operation>,
        bytes: usize,
        metadata: usize,
    ) -> Result<Self, PlatformError> {
        Self::reserve_inner(operation, bytes, metadata, true)
    }
    fn reserve_inner(
        operation: &Arc<Operation>,
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
            Some(
                operation
                    .with_session(|session| session.core.budget.reserve_host_memory(bytes as u64))
                    .map_err(|_| capacity())?,
            )
        } else {
            None
        };
        Ok(Self {
            host: native,
            _bytes: charge,
            _metadata: meta,
            _slot: slot,
            _operation: Arc::clone(operation),
        })
    }
    pub(super) fn confirm_host(&mut self) {
        if let Some(native) = &mut self.host {
            native.confirm();
        }
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
