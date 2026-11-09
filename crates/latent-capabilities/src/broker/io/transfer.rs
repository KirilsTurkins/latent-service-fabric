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

/// One buffer and one outstanding slot prepaid by their original transfer.
/// The allocation dies before its memory and slot reservations. A Store-side
/// adapter may capture bytes without calling back into the operation, then
/// return this owner to the transfer for the authority and total-byte checks.
pub struct PreparedIoInput {
    bytes: Vec<u8>,
    memory: IoMemory,
    slot: Slot,
    captured: bool,
}

impl PreparedIoInput {
    #[must_use]
    pub fn capacity(&self) -> usize {
        self.bytes.capacity()
    }

    #[must_use]
    pub fn captured_len(&self) -> Option<usize> {
        self.captured.then_some(self.bytes.len())
    }

    /// Copy once into already allocated storage. This does not inspect the
    /// operation, allocate, or invoke a caller-supplied callback. An invalid
    /// request leaves the preparation unchanged and publishes no bytes.
    pub fn capture(&mut self, source: &[u8]) -> bool {
        if self.captured || source.is_empty() || source.len() > self.bytes.len() {
            return false;
        }
        self.bytes[..source.len()].copy_from_slice(source);
        self.bytes.truncate(source.len());
        self.captured = true;
        true
    }
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
/// Both resident data and one canonical lowering copy are prepaid. The resource
/// retains resident storage; materialization moves its copy allowance into the
/// actual immutable byte owner.
pub struct IoOutputChunk {
    bytes: IoBuffer,
    copy: Option<IoMemory>,
    _slot: Shared<Slot>,
    owner: Option<Arc<dyn Send + Sync>>,
}

/// One immutable materialization of a chunk's prepaid lowering allowance.
/// The bytes physically retire before their original reservation and transfer
/// owners. There is no cloning, mutable buffer, or unowned Vec extraction API.
pub struct IoOutputCopy {
    bytes: Vec<u8>,
    _memory: IoMemory,
    _retention: CopyRetention,
}
// Closed retention choices: a real transfer slot or the SAME affine blob call.
// No erased wrapper allocation or manufactured owner is accepted.
enum CopyRetention {
    Transfer {
        _slot: Shared<Slot>,
        _owner: Option<Arc<dyn Send + Sync>>,
    },
    Blob {
        _owner: crate::broker::pools::PoolCall,
    },
}

/// Prepaid capacity for one typed blob range copy; scratch/imported values do
/// not gain a materialization constructor. Dropping unused preparation refunds
/// only reserved capacity, without confirming unallocated Vec backing.
pub struct PreparedIoCopy {
    memory: IoMemory,
    maximum: usize,
}
impl IoCall {
    /// Reserve the actual possible copy before any source I/O. The normal
    /// native profile uses its original ledger; Phase1 keeps logical quotas.
    pub fn reserve_copy(
        &self,
        bytes: usize,
        metadata: usize,
    ) -> Result<PreparedIoCopy, PlatformError> {
        let native = self
            .operation
            .with_session(|session| session.core.budget.profile().supports_descendants());
        let memory = if native {
            IoMemory::reserve_host(&self.operation, bytes, metadata)?
        } else {
            IoMemory::reserve(&self.operation, bytes, metadata)?
        };
        Ok(PreparedIoCopy {
            memory,
            maximum: bytes,
        })
    }
}
impl PreparedIoCopy {
    pub(in crate::broker) fn check_blob(
        &self,
        data: &IoBuffer,
        owner: &crate::broker::pools::PoolCall,
    ) -> Result<(), PlatformError> {
        if !Shared::ptr_eq(&data.operation, &owner.io().operation)
            || !self.memory.belongs_to(&data.operation)
            || !owner.retains_original_request()
            || self.maximum != data.capacity()
        {
            return Err(denied());
        }
        owner.io().checkpoint()
    }
    pub(in crate::broker) fn finish_blob(
        mut self,
        data: &IoBuffer,
        owner: crate::broker::pools::PoolCall,
    ) -> Result<IoOutputCopy, PlatformError> {
        self.check_blob(data, &owner)?;
        let bytes = data.bytes().to_vec();
        if bytes.capacity() > self.maximum {
            return Err(capacity());
        }
        self.memory.confirm_host_capacity(bytes.capacity())?;
        Ok(IoOutputCopy {
            bytes,
            _memory: self.memory,
            _retention: CopyRetention::Blob { _owner: owner },
        })
    }
}
impl AsRef<[u8]> for IoOutputCopy {
    fn as_ref(&self) -> &[u8] {
        &self.bytes
    }
}
impl std::ops::Deref for IoOutputCopy {
    type Target = [u8];
    fn deref(&self) -> &Self::Target {
        self.as_ref()
    }
}
impl IoOutputChunk {
    #[must_use]
    pub fn bytes(&self) -> &[u8] {
        self.bytes.bytes()
    }
    /// Materialize the one prepaid copy. Its own affine owner retains the
    /// original charge even if the source resource closes before lowering.
    pub fn copy_bytes(&mut self) -> Result<IoOutputCopy, PlatformError> {
        let copy = self.copy.as_mut().ok_or_else(invalid)?;
        self.bytes
            .operation
            .with_session(super::CapabilitySession::check_liveness)?;
        let bytes = self.bytes.bytes().to_vec();
        if bytes.capacity() > self.bytes.capacity() {
            return Err(capacity());
        }
        copy.confirm_host_capacity(bytes.capacity())?;
        Ok(IoOutputCopy {
            bytes,
            _memory: self.copy.take().expect("one checked copy allowance"),
            _retention: CopyRetention::Transfer {
                _slot: self._slot.clone(),
                _owner: self.owner.clone(),
            },
        })
    }
    pub fn retain_owner(&mut self, owner: Arc<dyn Send + Sync>) -> Result<(), PlatformError> {
        if self.owner.is_some() || self.copy.is_none() {
            return Err(denied());
        }
        self.owner = Some(owner);
        Ok(())
    }
}
pub struct IoTransferBuffer {
    bytes: IoBuffer,
    copy: IoMemory,
    slot: Shared<Slot>,
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
            copy: Some(self.copy),
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

    /// Reserve and allocate one bounded input before borrowing guest memory.
    /// Like `input_with`, this may invoke the original operation's callbacks;
    /// callers must not invoke it while holding a Store borrow.
    pub fn prepare_input(&self, maximum: usize) -> Result<PreparedIoInput, PlatformError> {
        self.inner.check()?;
        if maximum == 0 || maximum > self.maximum_chunk_bytes() {
            return Err(capacity());
        }
        let slot = Transfer::slot(&self.inner)?;
        // This new ingress path promises physical ownership of its snapshot.
        // The older logical-only profile must therefore refuse before allocating.
        let mut memory = IoMemory::reserve_host(&self.inner.operation, maximum, 512)?;
        // As in IoBuffer, fixed repetition requests exactly the prepaid
        // capacity and no growing operation is exposed after construction.
        let bytes = vec![0; maximum];
        if bytes.capacity() != maximum {
            return Err(capacity());
        }
        memory.confirm_host_capacity(bytes.capacity())?;
        Ok(PreparedIoInput {
            bytes,
            memory,
            slot,
            captured: false,
        })
    }

    #[must_use]
    pub fn owns_prepared_input(&self, prepared: &PreparedIoInput) -> bool {
        Shared::ptr_eq(&self.inner, &prepared.slot.inner)
    }

    /// Validate the original owner and spend the actual captured bytes once.
    /// Authority/deadline checks may call host-provided code, so this must run
    /// outside a Store borrow. A failed check publishes no transport chunk.
    pub fn finish_prepared_input(
        &self,
        prepared: PreparedIoInput,
    ) -> Result<IoInputChunk, PlatformError> {
        if !self.owns_prepared_input(&prepared) {
            return Err(denied());
        }
        if !prepared.captured {
            return Err(invalid());
        }
        self.inner.check()?;
        let PreparedIoInput {
            bytes,
            memory,
            slot,
            captured: _,
        } = prepared;
        // Install the real owner before spending, so failure frees bytes before
        // refunding either their memory reservation or their transfer slot.
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
        // Source and materialized copy share ONE outstanding-chunk lifetime.
        // Prepay its actual Arc/billing backing before either byte allocation.
        if Shared::<Slot>::allocation_bytes()? > 512 {
            return Err(super::capacity());
        }
        let slot_backing = self
            .inner
            .operation
            .with_session(|session| Shared::<Slot>::reserve(&session.core.budget))?;
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
        // The copy/resident metadata ceilings also admit the Slot envelope.
        // Their checks must precede the actual Shared allocation, not just its
        // activation-memory reservation.
        let slot = slot_backing.allocate(slot);
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
    use crate::broker::io::{tests::native_request, IoFuture, IoLimits, IoRuntime};
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
    async fn native_output_copy_is_affine_and_outlives_source_chunk_and_call() {
        let fixture = Fixture::new(CapabilityBrokerLimits::default());
        let (request, control) = native_request(&fixture, "native-output-copy");
        let session = fixture.session(&request, &control);
        let io = IoRuntime::new(IoLimits::default()).unwrap();
        let baseline = control.budget.host_memory_bytes();
        let guards = control.budget.outstanding_reservations();
        let call = start(&io, &session).await;
        let transfer = call
            .transfer(IoTransferOptions {
                maximum_chunk_bytes: 16,
                maximum_outstanding_chunks: 1,
            })
            .unwrap();
        let before_buffer = control.budget.host_memory_bytes();
        let slot_bytes = Shared::<Slot>::allocation_bytes().unwrap();
        let padding_bytes = request.budget.memory_bytes - before_buffer - slot_bytes + 1;
        let padding = control.budget.reserve_host_memory(padding_bytes).unwrap();
        let before_refusal = io.snapshot();
        assert_eq!(
            transfer.output_buffer(16).err().unwrap().code,
            latent_core::PlatformErrorCode::ResourceExhausted
        );
        assert_eq!(io.snapshot(), before_refusal);
        assert_eq!(transfer.outstanding_chunks(), 0);
        assert_eq!(
            control.budget.host_memory_bytes(),
            before_buffer + padding_bytes
        );
        drop(padding);
        let metadata_padding = call
            .operation
            .runtime
            .counters
            .acquire(
                Kind::Metadata,
                IoLimits::default().maximum_metadata_bytes - io.snapshot().metadata_bytes,
            )
            .unwrap();
        let before_metadata_refusal = io.snapshot();
        let peak_before = control.budget.snapshot_at(Instant::now()).peak_memory_bytes;
        assert_eq!(peak_before, before_buffer);
        assert_eq!(
            transfer.output_buffer(16).err().unwrap().code,
            latent_core::PlatformErrorCode::ResourceExhausted
        );
        assert_eq!(io.snapshot(), before_metadata_refusal);
        assert_eq!(transfer.outstanding_chunks(), 0);
        assert_eq!(control.budget.host_memory_bytes(), before_buffer);
        assert_eq!(
            control.budget.snapshot_at(Instant::now()).peak_memory_bytes,
            peak_before
        );
        drop(metadata_padding);
        let mut buffer = transfer.output_buffer(16).unwrap();
        buffer.spare_mut().unwrap()[..8].copy_from_slice(b"resident");
        buffer.advance_written(8).unwrap();
        let mut output = buffer.finish().unwrap();
        let before = control.budget.host_memory_bytes();
        let copy = output.copy_bytes().unwrap();
        assert_eq!(copy.as_ref(), b"resident");
        assert!(copy._memory.charged_to(&control.budget));
        assert_eq!(control.budget.host_memory_bytes(), before);
        assert_eq!(
            output.copy_bytes().err().unwrap().code,
            latent_core::PlatformErrorCode::InvalidArgument
        );
        assert_eq!(control.budget.host_memory_bytes(), before);
        let resident = 16 + super::super::ALLOCATION_BOOKKEEPING as u64;
        drop(output);
        assert_eq!(control.budget.host_memory_bytes(), before - resident);
        assert_eq!(io.snapshot().result_bytes, 0);
        assert_eq!(transfer.outstanding_chunks(), 1);
        assert_eq!(
            transfer.output_buffer(16).err().unwrap().code,
            latent_core::PlatformErrorCode::ResourceExhausted
        );
        drop((transfer, call));
        assert_eq!(copy.as_ref(), b"resident");
        assert!(control.budget.host_memory_bytes() >= baseline + resident);
        assert_eq!(io.snapshot().calls, 1);
        assert_eq!(io.snapshot().streams, 1);
        assert_eq!(io.snapshot().buffers, 1);
        drop(copy);
        assert_eq!(control.budget.host_memory_bytes(), baseline);
        assert_eq!(control.budget.outstanding_reservations(), guards);
        assert_eq!(io.snapshot(), super::super::IoSnapshot::default());
        let fresh = start(&io, &session).await;
        drop(fresh);
        assert_eq!(control.budget.host_memory_bytes(), baseline);
        assert_eq!(io.snapshot(), super::super::IoSnapshot::default());
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
            base + Shared::<Slot>::allocation_bytes().unwrap()
                + 2 * (16 + super::super::ALLOCATION_BOOKKEEPING as u64)
        );
        output.spare_mut().unwrap()[..8].copy_from_slice(b"resident");
        output.advance_written(8).unwrap();
        let mut output = output.finish().unwrap();
        let copy = output.copy_bytes().unwrap();
        assert_eq!(copy.as_ref(), b"resident");
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
            before
                + shell
                + Shared::<Slot>::allocation_bytes().unwrap()
                + 2 * (16 + super::super::ALLOCATION_BOOKKEEPING as u64)
        );
        drop((resident, explicit, explicit_call));
        assert_eq!(control.budget.host_memory_bytes(), baseline);
    }

    struct ObservedClock {
        calls: AtomicUsize,
        forbidden: AtomicBool,
    }
    impl latent_core::ActivationClock for ObservedClock {
        fn sample(&self) -> latent_core::ClockSample {
            assert!(!self.forbidden.load(Ordering::SeqCst));
            self.calls.fetch_add(1, Ordering::SeqCst);
            latent_core::ClockSample::system_now()
        }
        fn monotonic_now(&self) -> Instant {
            assert!(!self.forbidden.load(Ordering::SeqCst));
            self.calls.fetch_add(1, Ordering::SeqCst);
            Instant::now()
        }
    }

    struct OriginalUploadDropWitness {
        transfer: IoTransfer,
        io: Arc<IoRuntime>,
        budget: latent_core::ActivationBudget,
        expected_host_bytes: u64,
        dropped: Arc<AtomicBool>,
    }
    impl Drop for OriginalUploadDropWitness {
        fn drop(&mut self) {
            // This destructor runs on the real upload field of the same
            // PreparedHttpUpload type stored by the host table.
            assert_eq!(self.transfer.outstanding_chunks(), 0);
            assert_eq!(self.io.snapshot().staged_bytes, 0);
            assert_eq!(self.budget.host_memory_bytes(), self.expected_host_bytes);
            self.dropped.store(true, Ordering::SeqCst);
        }
    }
    impl crate::broker::streaming_http::HttpUpload for OriginalUploadDropWitness {
        fn write(
            &mut self,
            _: Vec<u8>,
        ) -> IoFuture<'_, Result<(), crate::broker::streaming_http::StreamingHttpError>> {
            IoFuture::failed(crate::broker::streaming_http::StreamingHttpError::InvalidState)
        }
        fn finish(
            self: Box<Self>,
        ) -> IoFuture<
            'static,
            Result<
                Box<dyn crate::broker::streaming_http::HttpBody>,
                crate::broker::streaming_http::StreamingHttpError,
            >,
        > {
            IoFuture::failed(crate::broker::streaming_http::StreamingHttpError::InvalidState)
        }
    }

    #[tokio::test]
    async fn prepared_http_owner_drops_real_unsubmitted_input_before_upload_on_drop_and_cancel() {
        use crate::broker::streaming_http::PreparedHttpUpload;
        use std::{
            future::Future,
            task::{Context, Poll, Waker},
        };

        let fixture = Fixture::new(CapabilityBrokerLimits::default());
        let (request, control) = native_request(&fixture, "prepared-upload-drop-order");
        let session = fixture.session(&request, &control);
        let io = Arc::new(IoRuntime::new(IoLimits::default()).unwrap());
        let baseline = control.budget.host_memory_bytes();
        for cancel_suspended in [false, true] {
            let call = start(&io, &session).await;
            let transfer = call
                .transfer(IoTransferOptions {
                    maximum_chunk_bytes: 16,
                    maximum_outstanding_chunks: 1,
                })
                .unwrap();
            let before_input = control.budget.host_memory_bytes();
            let prepared = transfer.prepare_input(16).unwrap();
            assert_eq!(transfer.outstanding_chunks(), 1);
            assert_eq!(io.snapshot().staged_bytes, 16);
            let dropped = Arc::new(AtomicBool::new(false));
            let held = PreparedHttpUpload {
                prepared: Some(prepared),
                upload: Box::new(OriginalUploadDropWitness {
                    transfer,
                    io: io.clone(),
                    budget: control.budget.clone(),
                    expected_host_bytes: before_input,
                    dropped: dropped.clone(),
                }),
                generation: 1,
            };
            if cancel_suspended {
                // Models a detached host future; the separate provider test
                // exercises the actual submitted-write cancellation path.
                let mut future = Box::pin(async move {
                    std::future::pending::<()>().await;
                    drop(held);
                });
                assert!(matches!(
                    future
                        .as_mut()
                        .poll(&mut Context::from_waker(Waker::noop())),
                    Poll::Pending
                ));
                drop(future);
            } else {
                drop(held);
            }
            assert!(dropped.load(Ordering::SeqCst));
            drop(call);
            assert_eq!(io.snapshot(), super::super::IoSnapshot::default());
            assert_eq!(control.budget.host_memory_bytes(), baseline);
        }
    }

    #[tokio::test]
    async fn prepared_input_captures_once_without_callbacks_and_retains_the_original_owner() {
        let clock = Arc::new(ObservedClock {
            calls: AtomicUsize::new(0),
            forbidden: AtomicBool::new(false),
        });
        let fixture = Fixture::with_activation_clock(clock.clone());
        let (request, control) = native_request(&fixture, "prepared-input-owner");
        let session = fixture.session(&request, &control);
        let io = IoRuntime::new(IoLimits::default()).unwrap();
        let baseline = control.budget.host_memory_bytes();
        let call = start(&io, &session).await;
        let transfer = call
            .transfer(IoTransferOptions {
                maximum_chunk_bytes: 16,
                maximum_outstanding_chunks: 1,
            })
            .unwrap();
        assert!(transfer.prepare_input(0).is_err());
        assert!(transfer.prepare_input(17).is_err());
        assert_eq!(transfer.outstanding_chunks(), 0);

        let before = control.budget.host_memory_bytes();
        let mut prepared = transfer.prepare_input(16).unwrap();
        assert_eq!(prepared.capacity(), 16);
        assert_eq!(transfer.outstanding_chunks(), 1);
        assert_eq!(io.snapshot().staged_bytes, 16);
        assert_eq!(
            control.budget.host_memory_bytes(),
            before + 16 + super::super::ALLOCATION_BOOKKEEPING as u64
        );
        assert!(transfer.prepare_input(1).is_err());
        let calls = clock.calls.load(Ordering::SeqCst);
        clock.forbidden.store(true, Ordering::SeqCst);
        assert!(!prepared.capture(&[]));
        assert!(!prepared.capture(&[1; 17]));
        let mut source = *b"data";
        assert!(prepared.capture(&source));
        source.fill(b'x');
        assert!(!prepared.capture(&source));
        clock.forbidden.store(false, Ordering::SeqCst);
        assert_eq!(clock.calls.load(Ordering::SeqCst), calls);
        assert_eq!(transfer.accepted_input_bytes(), 0);
        let chunk = transfer.finish_prepared_input(prepared).unwrap();
        assert!(clock.calls.load(Ordering::SeqCst) > calls);
        assert_eq!(chunk.as_ref(), b"data");
        assert_eq!(transfer.accepted_input_bytes(), 4);
        assert!(chunk._memory.charged_to(&control.budget));
        assert_eq!(transfer.outstanding_chunks(), 1);
        // Keep the exact original operation and transfer alive so no other
        // owner can be mistaken for this input allocation's native charge.
        assert_eq!(
            control.budget.host_memory_bytes(),
            before + 16 + super::super::ALLOCATION_BOOKKEEPING as u64
        );
        drop(chunk);
        assert_eq!(control.budget.host_memory_bytes(), before);
        assert_eq!(transfer.outstanding_chunks(), 0);

        // Preserve the original control: a later input still retains its
        // exact operation after the transfer and call owners are dropped.
        let mut prepared = transfer.prepare_input(16).unwrap();
        assert!(prepared.capture(b"data"));
        let chunk = transfer.finish_prepared_input(prepared).unwrap();
        assert_eq!(transfer.accepted_input_bytes(), 8);
        assert!(chunk._memory.charged_to(&control.budget));
        drop((transfer, call));
        assert_eq!(chunk.as_ref(), b"data");
        assert_eq!(io.snapshot().staged_bytes, 16);
        assert!(control.budget.host_memory_bytes() > baseline);
        drop(chunk);
        assert_eq!(io.snapshot(), super::super::IoSnapshot::default());
        assert_eq!(control.budget.host_memory_bytes(), baseline);
    }

    #[tokio::test]
    async fn prepared_input_refuses_foreign_owners_cancellation_and_unfunded_capacity() {
        let fixture = Fixture::new(CapabilityBrokerLimits::default());
        let (request, control) = native_request(&fixture, "prepared-input-refusal");
        let session = fixture.session(&request, &control);
        let io = IoRuntime::new(IoLimits::default()).unwrap();
        let first_call = start(&io, &session).await;
        let second_call = start(&io, &session).await;
        let options = IoTransferOptions {
            maximum_chunk_bytes: 16,
            maximum_outstanding_chunks: 1,
        };
        let first = first_call.transfer(options).unwrap();
        let second = second_call.transfer(options).unwrap();
        let before = control.budget.host_memory_bytes();
        let envelope = 16 + super::super::ALLOCATION_BOOKKEEPING as u64;
        let held = request.budget.memory_bytes - before - envelope + 1;
        let padding = control.budget.reserve_host_memory(held).unwrap();
        let before_refusal = io.snapshot();
        assert!(first.prepare_input(16).is_err());
        assert_eq!(io.snapshot(), before_refusal);
        assert_eq!(first.outstanding_chunks(), 0);
        drop(padding);

        let mut foreign = first.prepare_input(8).unwrap();
        assert!(foreign.capture(b"foreign"));
        assert!(first.owns_prepared_input(&foreign));
        assert!(!second.owns_prepared_input(&foreign));
        assert!(second.finish_prepared_input(foreign).is_err());
        assert_eq!(first.outstanding_chunks(), 0);
        assert_eq!(first.accepted_input_bytes(), 0);
        assert_eq!(second.accepted_input_bytes(), 0);
        assert_eq!(io.snapshot().staged_bytes, 0);

        let mut cancelled = first.prepare_input(8).unwrap();
        control.probe.0.store(true, Ordering::SeqCst);
        // Capturing is deliberately inert even after cancellation. The later
        // original-operation check refuses before a transport owner is formed.
        assert!(cancelled.capture(b"cancel"));
        assert!(first.finish_prepared_input(cancelled).is_err());
        assert_eq!(first.outstanding_chunks(), 0);
        assert_eq!(first.accepted_input_bytes(), 0);
        assert_eq!(io.snapshot().staged_bytes, 0);
    }

    #[tokio::test]
    async fn prepared_input_refuses_the_logical_only_profile_before_allocation() {
        let fixture = Fixture::new(CapabilityBrokerLimits::default());
        let (request, control) = fixture.request("prepared-input-phase1");
        assert!(!control.budget.profile().supports_descendants());
        let session = fixture.session(&request, &control);
        let io = IoRuntime::new(IoLimits::default()).unwrap();
        let call = start(&io, &session).await;
        let transfer = call
            .transfer(IoTransferOptions {
                maximum_chunk_bytes: 16,
                maximum_outstanding_chunks: 1,
            })
            .unwrap();
        let before = io.snapshot();
        assert!(transfer.prepare_input(16).is_err());
        assert_eq!(io.snapshot(), before);
        assert_eq!(transfer.outstanding_chunks(), 0);
        assert_eq!(control.budget.host_memory_bytes(), 0);
    }
}
