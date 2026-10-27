//! One accepted transfer, finite totals and independently owned resident chunks.
use super::{
    capacity, denied, invalid, Authority, Charge, IoBuffer, IoCall, IoMemory, Kind, OperationOwner,
    PlatformError, Shared,
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
    operation: OperationOwner,
    budget: CapabilityStreamBudget,
    options: IoTransferOptions,
    input: AtomicU64,
    output: AtomicU64,
    outstanding: AtomicUsize,
    closed: AtomicBool,
    host_memory: bool,
    _metadata: Charge,
    _stream: Charge,
}
/// Affine stream lifetime. Dropping it stops new chunks but cannot refund bytes
/// retained by an actual socket, guest chunk, or a cancelled reader's buffer.
pub struct IoTransfer {
    inner: Shared<Transfer>,
}
struct Slot {
    inner: Shared<Transfer>,
}
/// Can be moved directly into a transport's immutable byte owner without copying.
pub struct IoInputChunk {
    bytes: Vec<u8>,
    _memory: IoMemory,
    _slot: Slot,
    owner: Option<Arc<dyn Send + Sync>>,
}
impl IoInputChunk {
    pub fn retain_owner(&mut self, owner: Arc<dyn Send + Sync>) -> Result<(), PlatformError> {
        if self.owner.is_some() {
            return Err(denied());
        }
        self.owner = Some(owner);
        Ok(())
    }
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
    copy: IoMemory,
    _slot: Slot,
    owner: Option<Arc<dyn Send + Sync>>,
}
impl IoOutputChunk {
    #[must_use]
    pub fn bytes(&self) -> &[u8] {
        self.bytes.bytes()
    }
    /// The prepaid canonical copy stays charged with this affine chunk. A host
    /// must retain the chunk while lowering the returned bytes into guest memory.
    pub fn copy_bytes(&mut self) -> Result<Vec<u8>, PlatformError> {
        self.bytes
            .operation
            .with_session(super::CapabilitySession::check_liveness)?;
        let bytes = self.bytes.bytes().to_vec();
        if bytes.capacity() > self.bytes.capacity() {
            return Err(capacity());
        }
        self.copy.confirm_host_capacity(bytes.capacity())?;
        Ok(bytes)
    }
    pub fn retain_owner(&mut self, owner: Arc<dyn Send + Sync>) -> Result<(), PlatformError> {
        if self.owner.is_some() {
            return Err(denied());
        }
        self.owner = Some(owner);
        Ok(())
    }
}
pub struct IoTransferBuffer {
    bytes: IoBuffer,
    copy: IoMemory,
    slot: Slot,
    owner: Option<Arc<dyn Send + Sync>>,
}
impl IoTransferBuffer {
    pub fn retain_owner(&mut self, owner: Arc<dyn Send + Sync>) -> Result<(), PlatformError> {
        if self.owner.is_some() {
            return Err(denied());
        }
        self.owner = Some(owner);
        Ok(())
    }
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
            copy: self.copy,
            _slot: self.slot,
            owner: self.owner,
        })
    }
}
impl IoCall {
    /// Available only when the original final policy decision explicitly
    /// authorized a stream budget. This allowance can be issued only once.
    pub fn transfer(&self, options: IoTransferOptions) -> Result<IoTransfer, PlatformError> {
        self.transfer_inner(options, false)
    }
    /// Track real stream buffers in the activation's original native-memory
    /// ledger as well as the shared node I/O ceilings.
    pub fn transfer_with_host_memory(
        &self,
        options: IoTransferOptions,
    ) -> Result<IoTransfer, PlatformError> {
        self.transfer_inner(options, true)
    }
    fn transfer_inner(
        &self,
        options: IoTransferOptions,
        host_memory: bool,
    ) -> Result<IoTransfer, PlatformError> {
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
        // Authority is already locked above. Borrow its SAME original core;
        // with_session would recursively lock operation.execution here.
        let core = call.session_core();
        if Shared::<Transfer>::allocation_bytes()? > 2048 {
            return Err(capacity());
        }
        let backing = Shared::<Transfer>::reserve(&core.budget)?;
        let host_memory = host_memory || core.budget.profile().supports_descendants();
        let inner = backing.allocate(Transfer {
            operation: self.operation.clone(),
            budget,
            options,
            input: AtomicU64::new(0),
            output: AtomicU64::new(0),
            outstanding: AtomicUsize::new(0),
            closed: AtomicBool::new(false),
            host_memory,
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
    fn slot(owner: &Shared<Self>) -> Result<Slot, PlatformError> {
        let this = &**owner;
        this.check()?;
        let mut previous = this.outstanding.load(Ordering::Acquire);
        for _ in 0..16 {
            let next = previous
                .checked_add(1)
                .filter(|n| *n <= this.options.maximum_outstanding_chunks)
                .ok_or_else(capacity)?;
            match this.outstanding.compare_exchange_weak(
                previous,
                next,
                Ordering::AcqRel,
                Ordering::Acquire,
            ) {
                Ok(_) => {
                    return Ok(Slot {
                        inner: owner.clone(),
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
        self.input_with(bytes.capacity(), || Ok(bytes))
    }
    /// Reserve the original resident/native charges before materializing guest
    /// bytes. The producer runs synchronously and no Store borrow is retained.
    pub fn input_with(
        &self,
        maximum: usize,
        produce: impl FnOnce() -> Result<Vec<u8>, PlatformError>,
    ) -> Result<IoInputChunk, PlatformError> {
        self.inner.check()?;
        if maximum == 0 || maximum > self.maximum_chunk_bytes() {
            return Err(capacity());
        }
        let slot = Transfer::slot(&self.inner)?;
        let mut memory = if self.inner.host_memory {
            IoMemory::reserve_host(&self.inner.operation, maximum, 512)?
        } else {
            IoMemory::reserve(&self.inner.operation, maximum, 512)?
        };
        let bytes = produce()?;
        if bytes.is_empty() || bytes.capacity() > maximum {
            return Err(capacity());
        }
        memory.confirm_host_capacity(bytes.capacity())?;
        // Construct the real data owner first: a failed total-byte check must
        // drop its bytes before returning the resident-memory reservation.
        let chunk = IoInputChunk {
            bytes,
            _memory: memory,
            _slot: slot,
            owner: None,
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
        let slot = Transfer::slot(&self.inner)?;
        let copy = if self.inner.host_memory {
            IoMemory::reserve_host(&self.inner.operation, capacity, 512)?
        } else {
            IoMemory::reserve(&self.inner.operation, capacity, 512)?
        };
        let bytes = if self.inner.host_memory {
            IoBuffer::allocate_host(&self.inner.operation, capacity, 512)?
        } else {
            IoBuffer::allocate(&self.inner.operation, capacity, 512)?
        };
        Ok(IoTransferBuffer {
            bytes,
            copy,
            slot,
            owner: None,
        })
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

#[cfg(test)]
mod native_tests {
    use super::*;
    use crate::broker::io::{tests::native_request, IoLimits, IoRuntime};
    use crate::broker::{
        tests::fixture::{resource, Fixture, CAP},
        CapabilityBrokerLimits, CapabilityCallCost, CapabilitySession,
    };
    use std::sync::atomic::AtomicUsize;
    use std::time::Instant;

    async fn start(io: &IoRuntime, session: &CapabilitySession) -> IoCall {
        let admission = io.admit(session).unwrap().wait().await.unwrap();
        let handle = session.bind(CAP, "read", resource()).unwrap();
        let provider = session
            .dispatch(
                handle,
                "read",
                resource(),
                &[],
                CapabilityCallCost::new(32)
                    .with_stream_budget(CapabilityStreamBudget::new(128, 128).unwrap()),
                |call| call,
            )
            .unwrap();
        session.close_handle(handle).unwrap();
        admission.start(provider).unwrap()
    }
    #[tokio::test]
    async fn native_transfer_factory_is_prepaid_and_confirms_only_actual_capacity() {
        let fixture = Fixture::new(CapabilityBrokerLimits::default());
        let (request, control) = native_request(&fixture, "native-transfer-factory");
        let session = fixture.session(&request, &control);
        let io = IoRuntime::new(IoLimits::default()).unwrap();
        let call = start(&io, &session).await;
        let baseline = control.budget.host_memory_bytes();
        let shell = Shared::<Transfer>::allocation_bytes().unwrap();
        let options = IoTransferOptions {
            maximum_chunk_bytes: 64,
            maximum_outstanding_chunks: 1,
        };
        let pad_bytes = request.budget.memory_bytes - baseline - shell + 1;
        let pad = control.budget.reserve_host_memory(pad_bytes).unwrap();
        assert_eq!(
            call.transfer(options).err().unwrap().code,
            crate::broker::PlatformErrorCode::ResourceExhausted
        );
        assert!(!call.operation.execution.lock().unwrap().transfer_issued);
        assert_eq!(io.snapshot().streams, 0);
        drop(pad);
        let transfer = call.transfer(options).unwrap();
        assert!(transfer.inner.host_memory); // normal native route needs no opt-in
        assert_eq!(control.budget.host_memory_bytes(), baseline + shell);
        let base = control.budget.host_memory_bytes();
        let envelope = 64 + super::super::ALLOCATION_BOOKKEEPING as u64;
        let padding_bytes = request.budget.memory_bytes - base - envelope + 1;
        let padding = control.budget.reserve_host_memory(padding_bytes).unwrap();
        let produced = AtomicUsize::new(0);
        assert!(transfer
            .input_with(64, || {
                produced.fetch_add(1, Ordering::SeqCst);
                Ok(vec![7; 8])
            })
            .is_err());
        assert_eq!(produced.load(Ordering::SeqCst), 0);
        assert_eq!(transfer.outstanding_chunks(), 0);
        drop(padding);
        let before_peak = control.budget.snapshot_at(Instant::now()).peak_memory_bytes;
        let input = transfer
            .input_with(64, || {
                produced.fetch_add(1, Ordering::SeqCst);
                Ok(vec![7; 8])
            })
            .unwrap();
        assert_eq!(produced.load(Ordering::SeqCst), 1);
        assert_eq!(input.bytes.capacity(), 8);
        assert_eq!(control.budget.host_memory_bytes(), base + envelope);
        assert!(input._memory.charged_to(&control.budget));
        assert!(
            control.budget.snapshot_at(Instant::now()).peak_memory_bytes
                <= before_peak.max(base + 8 + super::super::ALLOCATION_BOOKKEEPING as u64)
        );
        drop(input);
        assert_eq!(control.budget.host_memory_bytes(), base);
        let mut output = transfer.output_buffer(16).unwrap();
        assert_eq!(
            control.budget.host_memory_bytes(),
            base + 2 * (16 + super::super::ALLOCATION_BOOKKEEPING as u64)
        );
        output.spare_mut().unwrap()[..8].copy_from_slice(b"resident");
        output.advance_written(8).unwrap();
        let mut output = output.finish().unwrap();
        let copy = output.copy_bytes().unwrap();
        assert_eq!(copy, b"resident");
        drop(copy); // This ONE concrete lowering retains its real chunk owner.
        drop(output);
        assert_eq!(control.budget.host_memory_bytes(), base);
        drop(transfer);
        assert_eq!(control.budget.host_memory_bytes(), baseline);
        let explicit_call = start(&io, &session).await;
        let before = control.budget.host_memory_bytes();
        let explicit = explicit_call.transfer_with_host_memory(options).unwrap();
        assert_eq!(control.budget.host_memory_bytes(), before + shell);
        let resident = explicit.output_buffer(16).unwrap();
        assert_eq!(
            control.budget.host_memory_bytes(),
            before + shell + 2 * (16 + super::super::ALLOCATION_BOOKKEEPING as u64)
        );
        drop((resident, explicit, explicit_call));
        assert_eq!(control.budget.host_memory_bytes(), baseline);
    }
}
