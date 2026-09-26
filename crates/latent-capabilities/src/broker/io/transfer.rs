//! One accepted transfer, finite totals and independently owned resident chunks.
use super::{
    capacity, denied, invalid, Authority, Charge, IoBuffer, IoCall, IoMemory, Kind, Operation,
    PlatformError,
};
use crate::broker::CapabilityStreamBudget;
use std::sync::{
    atomic::{AtomicBool, AtomicU64, AtomicUsize, Ordering},
    Arc,
};

#[derive(Debug, Clone, Copy)]
pub struct IoTransferOptions {
    pub maximum_chunk_bytes: usize,
    pub maximum_outstanding_chunks: usize,
}
struct Transfer {
    operation: Arc<Operation>,
    budget: CapabilityStreamBudget,
    options: IoTransferOptions,
    input: AtomicU64,
    output: AtomicU64,
    outstanding: AtomicUsize,
    closed: AtomicBool,
    _metadata: Charge,
    _stream: Charge,
}
/// Affine stream lifetime. Dropping it stops new chunks but cannot refund bytes
/// retained by an actual socket, guest chunk, or a cancelled reader's buffer.
pub struct IoTransfer {
    inner: Arc<Transfer>,
}
struct Slot {
    inner: Arc<Transfer>,
}
/// Can be moved directly into a transport's immutable byte owner without copying.
pub struct IoInputChunk {
    bytes: Vec<u8>,
    _memory: IoMemory,
    _slot: Slot,
}
impl AsRef<[u8]> for IoInputChunk {
    fn as_ref(&self) -> &[u8] {
        &self.bytes
    }
}
/// Both the resident data and one canonical lowering copy are prepaid. The
/// guest resource keeps this owner through every borrow and its final Drop.
pub struct IoOutputChunk {
    bytes: IoBuffer,
    _copy: IoMemory,
    _slot: Slot,
}
impl IoOutputChunk {
    #[must_use]
    pub fn bytes(&self) -> &[u8] {
        self.bytes.bytes()
    }
}
pub struct IoTransferBuffer {
    bytes: IoBuffer,
    copy: IoMemory,
    slot: Slot,
}
impl IoTransferBuffer {
    pub fn spare_mut(&mut self) -> Result<&mut [u8], PlatformError> {
        self.bytes.spare_mut()
    }
    pub fn advance_written(&mut self, count: usize) -> Result<(), PlatformError> {
        self.bytes.advance_written(count)
    }
    #[must_use]
    pub fn bytes(&self) -> &[u8] {
        self.bytes.bytes()
    }
    pub fn finish(self) -> Result<IoOutputChunk, PlatformError> {
        self.slot.inner.check()?;
        if self.bytes.bytes().is_empty() {
            return Err(invalid());
        }
        spend(
            &self.slot.inner.output,
            self.bytes.bytes().len(),
            self.slot.inner.budget.output_bytes(),
        )?;
        Ok(IoOutputChunk {
            bytes: self.bytes.retain_for_transfer()?,
            _copy: self.copy,
            _slot: self.slot,
        })
    }
}
impl IoCall {
    /// Available only when the original final policy decision explicitly
    /// authorized a stream budget. This allowance can be issued only once.
    pub fn transfer(&self, options: IoTransferOptions) -> Result<IoTransfer, PlatformError> {
        self.checkpoint()?;
        let runtime = &self.operation.runtime;
        if options.maximum_chunk_bytes == 0
            || options.maximum_chunk_bytes > runtime.limits.maximum_chunk_bytes
            || options.maximum_outstanding_chunks == 0
            || options.maximum_outstanding_chunks > runtime.limits.maximum_stream_chunks
        {
            return Err(capacity());
        }
        let mut state = self
            .operation
            .execution
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        if state.transfer_issued {
            return Err(denied());
        }
        let Authority::Running(call) = &state.authority else {
            return Err(denied());
        };
        let budget = call.stream_budget().ok_or_else(denied)?;
        if budget.input_bytes() > runtime.limits.maximum_stream_bytes
            || budget.output_bytes() > runtime.limits.maximum_stream_bytes
        {
            return Err(capacity());
        }
        let stream = runtime.counters.acquire(Kind::Stream, 1)?;
        let metadata = runtime.counters.acquire(Kind::Metadata, 2048)?;
        let inner = Arc::new(Transfer {
            operation: Arc::clone(&self.operation),
            budget,
            options,
            input: AtomicU64::new(0),
            output: AtomicU64::new(0),
            outstanding: AtomicUsize::new(0),
            closed: AtomicBool::new(false),
            _metadata: metadata,
            _stream: stream,
        });
        state.transfer_issued = true;
        Ok(IoTransfer { inner })
    }
}
impl Transfer {
    fn check(&self) -> Result<(), PlatformError> {
        self.operation.check()?;
        if self.closed.load(Ordering::Acquire) {
            return Err(denied());
        }
        Ok(())
    }
    fn slot(self: &Arc<Self>) -> Result<Slot, PlatformError> {
        self.check()?;
        let mut previous = self.outstanding.load(Ordering::Acquire);
        for _ in 0..16 {
            let next = previous
                .checked_add(1)
                .filter(|n| *n <= self.options.maximum_outstanding_chunks)
                .ok_or_else(capacity)?;
            match self.outstanding.compare_exchange_weak(
                previous,
                next,
                Ordering::AcqRel,
                Ordering::Acquire,
            ) {
                Ok(_) => {
                    return Ok(Slot {
                        inner: Arc::clone(self),
                    })
                }
                Err(actual) => previous = actual,
            }
        }
        Err(capacity())
    }
}
impl IoTransfer {
    #[must_use]
    pub fn maximum_chunk_bytes(&self) -> usize {
        self.inner.options.maximum_chunk_bytes
    }
    pub fn input(&self, bytes: Vec<u8>) -> Result<IoInputChunk, PlatformError> {
        self.inner.check()?;
        if bytes.is_empty() || bytes.capacity() > self.maximum_chunk_bytes() {
            return Err(capacity());
        }
        let slot = self.inner.slot()?;
        let memory = IoMemory::reserve(&self.inner.operation, bytes.capacity(), 512)?;
        // Construct the real data owner first: a failed total-byte check must
        // drop its bytes before returning the resident-memory reservation.
        let chunk = IoInputChunk {
            bytes,
            _memory: memory,
            _slot: slot,
        };
        spend(
            &self.inner.input,
            chunk.bytes.len(),
            self.inner.budget.input_bytes(),
        )?;
        Ok(chunk)
    }
    /// Obtain capacity before asking the transport for another frame. Saturation
    /// returns without polling I/O; the caller may drop held chunks and retry.
    pub fn output_buffer(&self, capacity: usize) -> Result<IoTransferBuffer, PlatformError> {
        self.inner.check()?;
        if capacity == 0 || capacity > self.maximum_chunk_bytes() {
            return Err(invalid());
        }
        let slot = self.inner.slot()?;
        let copy = IoMemory::reserve(&self.inner.operation, capacity, 512)?;
        let bytes = IoBuffer::allocate(&self.inner.operation, capacity, 512)?;
        Ok(IoTransferBuffer { bytes, copy, slot })
    }
    #[must_use]
    pub fn outstanding_chunks(&self) -> usize {
        self.inner.outstanding.load(Ordering::Acquire)
    }
    #[must_use]
    pub fn accepted_input_bytes(&self) -> u64 {
        self.inner.input.load(Ordering::Acquire)
    }
    #[must_use]
    pub fn accepted_output_bytes(&self) -> u64 {
        self.inner.output.load(Ordering::Acquire)
    }
}
impl Drop for IoTransfer {
    fn drop(&mut self) {
        self.inner.closed.store(true, Ordering::Release);
    }
}
impl Drop for Slot {
    fn drop(&mut self) {
        self.inner.outstanding.fetch_sub(1, Ordering::AcqRel);
    }
}
fn spend(counter: &AtomicU64, bytes: usize, maximum: u64) -> Result<(), PlatformError> {
    let mut previous = counter.load(Ordering::Acquire);
    for _ in 0..16 {
        let next = previous
            .checked_add(bytes as u64)
            .filter(|n| *n <= maximum)
            .ok_or_else(capacity)?;
        match counter.compare_exchange_weak(previous, next, Ordering::AcqRel, Ordering::Acquire) {
            Ok(_) => return Ok(()),
            Err(actual) => previous = actual,
        }
    }
    Err(capacity())
}
