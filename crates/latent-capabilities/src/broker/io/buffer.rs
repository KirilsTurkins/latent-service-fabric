use super::{capacity, invalid, stream::StreamLifetime, Charge, Kind, Operation, PlatformError};
use std::sync::Arc;
use zeroize::Zeroizing;

/// Fixed-capacity storage. Adapters can borrow initialized spare bytes, never
/// extract or grow an uncharged Vec. A partial consumer keeps the full capacity.
pub struct IoBuffer {
    bytes: Zeroizing<Vec<u8>>,
    position: usize,
    length: usize,
    charge: Charge,
    _metadata: Charge,
    _slot: Charge,
    pub(super) stream: Option<Arc<StreamLifetime>>,
    pub(super) operation: Arc<Operation>,
}
impl IoBuffer {
    pub(super) fn allocate(
        op: &Arc<Operation>,
        capacity: usize,
        metadata: usize,
    ) -> Result<Self, PlatformError> {
        op.check()?;
        if capacity == 0 || capacity > op.runtime.limits.maximum_chunk_bytes {
            return Err(super::capacity());
        }
        let slot = op.runtime.counters.acquire(Kind::Buffer, 1)?;
        let meta = op.runtime.counters.acquire(
            Kind::Metadata,
            metadata.checked_add(512).ok_or_else(super::capacity)?,
        )?;
        let charge = op.runtime.counters.acquire(Kind::Staged, capacity)?;
        // Vec repetition requests exactly its length as capacity. No reserve,
        // push, extension, shrink or realloc is exposed after construction.
        let bytes = Zeroizing::new(vec![0; capacity]);
        if bytes.capacity() != capacity {
            return Err(super::capacity());
        }
        Ok(Self {
            bytes,
            position: 0,
            length: 0,
            charge,
            _metadata: meta,
            _slot: slot,
            stream: None,
            operation: Arc::clone(op),
        })
    }
    #[must_use]
    pub fn capacity(&self) -> usize {
        self.bytes.capacity()
    }
    #[must_use]
    pub fn bytes(&self) -> &[u8] {
        &self.bytes[self.position..self.length]
    }
    /// Read at most this slice from the transport. Charge precedes the read.
    pub fn spare_mut(&mut self) -> Result<&mut [u8], PlatformError> {
        self.operation.check()?;
        if self.charge.kind != Kind::Staged {
            return Err(invalid());
        }
        Ok(&mut self.bytes[self.length..])
    }
    pub fn advance_written(&mut self, count: usize) -> Result<(), PlatformError> {
        self.operation.check()?;
        if self.charge.kind != Kind::Staged {
            return Err(invalid());
        }
        self.length = self
            .length
            .checked_add(count)
            .filter(|n| *n <= self.bytes.len())
            .ok_or_else(capacity)?;
        Ok(())
    }
    pub fn consume(&mut self, count: usize) -> Result<(), PlatformError> {
        self.position = self
            .position
            .checked_add(count)
            .filter(|n| *n <= self.length)
            .ok_or_else(invalid)?;
        Ok(())
    }
    /// Used only by the sealed transfer owner after spending its independently
    /// authorized cumulative output. It never exposes a movable `IoBuffer` to callers.
    pub(super) fn retain_for_transfer(mut self) -> Result<Self, PlatformError> {
        self.operation.check()?;
        if self.charge.kind != Kind::Staged || self.stream.is_some() {
            return Err(invalid());
        }
        self.charge = self
            .operation
            .runtime
            .counters
            .acquire(Kind::Result, self.capacity())?;
        Ok(self)
    }
    /// Transfer, without copying, into retained-output accounting. Reserving the
    /// result side first prevents a refund gap on saturation or cancellation.
    pub fn retain(mut self) -> Result<Self, PlatformError> {
        self.operation.check()?;
        if self.charge.kind == Kind::Staged {
            let result = self
                .operation
                .runtime
                .counters
                .acquire(Kind::Result, self.capacity())?;
            self.operation.accept_output(self.bytes().len())?;
            self.charge = result;
        }
        Ok(self)
    }
}
