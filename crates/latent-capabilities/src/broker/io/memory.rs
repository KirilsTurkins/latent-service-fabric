//! Reservations for already bounded typed host values and protocol state.
//! The adapter stores data before this guard in its owner, or shares the guard
//! with the actual byte owner. This avoids allocating a second dummy byte buffer.
use super::{capacity, Charge, IoAdmission, IoCall, Kind, Operation, PlatformError};
use std::sync::Arc;

pub struct IoMemory {
    _bytes: Charge,
    _metadata: Charge,
    _slot: Charge,
    _operation: Arc<Operation>,
}
impl IoMemory {
    fn reserve(
        operation: &Arc<Operation>,
        bytes: usize,
        metadata: usize,
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
        Ok(Self {
            _bytes: charge,
            _metadata: meta,
            _slot: slot,
            _operation: Arc::clone(operation),
        })
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
