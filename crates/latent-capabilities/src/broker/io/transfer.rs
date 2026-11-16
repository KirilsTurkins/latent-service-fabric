//! One accepted transfer, finite totals and independently owned resident chunks.
use super::output_slot::OutputSlot;
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
    stream_scope: u32,
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
#[cfg(test)]
static PANIC_SLOT_ADDRESS: AtomicUsize = AtomicUsize::new(0);
/// Can be moved directly into a transport's immutable byte owner without copying.
pub struct IoInputChunk {
    bytes: Vec<u8>,
    _memory: IoMemory,
    _slot: Slot,
    owner: Option<Arc<dyn Send + Sync>>,
}

fn http_input_owner_bytes() -> Result<usize, PlatformError> {
    // The vendored Bytes query uses the constructor's actual private Box type;
    // its retirement guard is taken out before the Box is dropped, including
    // during owner unwind. Do not mirror that layout in the caller.
    bytes::Bytes::owner_with_retirement_allocation_size::<
        IoInputChunk,
        super::memory::HttpInputRetirement,
    >()
    .checked_add(super::ALLOCATION_BOOKKEEPING)
    .ok_or_else(capacity)
}
/// One buffer and one outstanding slot prepaid by their original transfer.
/// The allocation dies before its memory and slot reservations. A Store-side
/// adapter may capture bytes without calling back into the operation, then
/// return this owner to the transfer for the authority and total-byte checks.
/// Capture alone is callback-free: every drop or failed conversion of this owner
/// must run outside a Store borrow. This type does not provide a cancellation or
/// Store-teardown handoff.
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
    /// Convert the original accepted input into its HTTP byte owner. Native
    /// profiles prepay its exact backing and retain the original charges until
    /// the last transport clone has physically released the allocation.
    #[doc(hidden)]
    pub fn into_http_bytes(self) -> Result<bytes::Bytes, PlatformError> {
        let retirement = self
            ._memory
            .reserve_http_input_owner(http_input_owner_bytes()?)?;
        Ok(match retirement {
            Some(retirement) => {
                bytes::Bytes::from_owner_with_retirement(self, retirement, |guard| guard.confirm())
            }
            None => bytes::Bytes::from_owner(self),
        })
    }

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
    _slot: OutputSlot<Slot>,
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
        _slot: OutputSlot<Slot>,
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
        if self.owner.is_some() || self.copy.is_none() || self._slot.has_stream() {
            return Err(denied());
        }
        self.owner = Some(owner);
        Ok(())
    }
}
pub struct IoTransferBuffer {
    bytes: IoBuffer,
    copy: IoMemory,
    slot: OutputSlot<Slot>,
    owner: Option<Arc<dyn Send + Sync>>,
}
impl IoTransferBuffer {
    pub fn retain_owner(&mut self, owner: Arc<dyn Send + Sync>) -> Result<(), PlatformError> {
        if self.owner.is_some() || self.slot.has_stream() {
            return Err(denied());
        }
        self.owner = Some(owner);
        Ok(())
    }
    /// Bind a stream's original connection and chunk admission to this output.
    /// This trusted host-only path neither creates nor substitutes a guest grant.
    #[doc(hidden)]
    pub fn retain_stream_owner<T: Send + Sync + 'static>(
        &mut self,
        owner: T,
        window: crate::broker::network::BoundStreamChunkReservation,
    ) -> Result<(), PlatformError> {
        let original_stream = {
            let state = self
                .slot
                .inner
                .operation
                .execution
                .lock()
                .unwrap_or_else(std::sync::PoisonError::into_inner);
            matches!(&state.authority, Authority::Running(call) if call.is_original_stream_connect())
        };
        let original_scope = self
            .slot
            .inner
            .operation
            .with_session(|session| window.belongs_to(self.slot.inner.stream_scope, session));
        if self.owner.is_some() || self.slot.has_stream() || !original_stream || !original_scope {
            return Err(denied());
        }
        let budget = self
            .slot
            .inner
            .operation
            .with_session(|session| session.core.budget.clone());
        self.slot.retain_stream(owner, window, &budget)
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
        self.transfer_inner(options, false, None)
    }
    /// Track real stream buffers in the activation's original native-memory
    /// ledger as well as the shared node I/O ceilings.
    pub fn transfer_with_host_memory(
        &self,
        options: IoTransferOptions,
    ) -> Result<IoTransfer, PlatformError> {
        self.transfer_inner(options, true, None)
    }
    /// Bind this original stream connect call to its original scope once.
    #[doc(hidden)]
    pub fn transfer_for_stream(
        &self,
        options: IoTransferOptions,
        scope: &crate::broker::network::StreamScope,
    ) -> Result<IoTransfer, PlatformError> {
        self.transfer_inner(options, true, Some(scope))
    }
    fn transfer_inner(
        &self,
        options: IoTransferOptions,
        host_memory: bool,
        stream_scope: Option<&crate::broker::network::StreamScope>,
    ) -> Result<IoTransfer, PlatformError> {
        self.checkpoint()?;
        let same_session = stream_scope.is_none_or(|scope| {
            self.operation
                .with_session(|session| scope.belongs_to(session))
        });
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
        if !same_session || (stream_scope.is_some() && !call.is_original_stream_connect()) {
            return Err(denied());
        }
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
            stream_scope: stream_scope.map_or(0, |scope| scope.identity_tag()),
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
        if OutputSlot::<Slot>::allocation_bytes()? > 512 {
            return Err(super::capacity());
        }
        let slot_backing = self
            .inner
            .operation
            .with_session(|session| OutputSlot::<Slot>::reserve(&session.core.budget))?;
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
        #[cfg(test)]
        if PANIC_SLOT_ADDRESS
            .compare_exchange(
                self as *const Self as usize,
                0,
                Ordering::SeqCst,
                Ordering::SeqCst,
            )
            .is_ok()
        {
            panic!("controlled original output slot destructor");
        }
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

    #[allow(dead_code)]
    struct OriginalTransfer {
        operation: OperationOwner,
        budget: CapabilityStreamBudget,
        options: IoTransferOptions,
        input: AtomicU64,
        output: AtomicU64,
        outstanding: AtomicUsize,
        closed: AtomicBool,
        host_memory: bool,
        metadata: Charge,
        stream: Charge,
    }

    #[test]
    fn output_slot_preserves_generic_value_layouts() {
        #[allow(dead_code)]
        struct OriginalInput {
            bytes: Vec<u8>,
            memory: IoMemory,
            slot: Slot,
            owner: Option<Arc<dyn Send + Sync>>,
        }
        #[allow(dead_code)]
        struct OriginalOutput {
            bytes: IoBuffer,
            copy: Option<IoMemory>,
            slot: Shared<Slot>,
            owner: Option<Arc<dyn Send + Sync>>,
        }
        #[allow(dead_code)]
        struct OriginalBuffer {
            bytes: IoBuffer,
            copy: IoMemory,
            slot: Shared<Slot>,
            owner: Option<Arc<dyn Send + Sync>>,
        }
        #[allow(dead_code)]
        enum OriginalRetention {
            Transfer {
                slot: Shared<Slot>,
                owner: Option<Arc<dyn Send + Sync>>,
            },
            Blob {
                owner: crate::broker::pools::PoolCall,
            },
        }
        #[allow(dead_code)]
        struct OriginalCopy {
            bytes: Vec<u8>,
            memory: IoMemory,
            retention: OriginalRetention,
        }
        assert_eq!(
            std::mem::size_of::<IoInputChunk>(),
            std::mem::size_of::<OriginalInput>()
        );
        assert_eq!(
            std::mem::size_of::<IoOutputChunk>(),
            std::mem::size_of::<OriginalOutput>()
        );
        assert_eq!(
            std::mem::size_of::<IoTransferBuffer>(),
            std::mem::size_of::<OriginalBuffer>()
        );
        assert_eq!(
            std::mem::size_of::<IoOutputCopy>(),
            std::mem::size_of::<OriginalCopy>()
        );
        assert_eq!(
            std::mem::align_of::<OutputSlot<Slot>>(),
            std::mem::align_of::<Shared<Slot>>()
        );
        let old = Shared::<Slot>::allocation_bytes().unwrap();
        let new = OutputSlot::<Slot>::allocation_bytes().unwrap();
        let old_transfer = Shared::<OriginalTransfer>::allocation_bytes().unwrap();
        let new_transfer = Shared::<Transfer>::allocation_bytes().unwrap();
        eprintln!("generic output slot original={old} current={new}; transfer original={old_transfer} current={new_transfer}");
        assert!(new > old);
        assert!(new_transfer >= old_transfer && new_transfer <= 2048);
        #[cfg(all(target_arch = "x86_64", target_os = "linux"))]
        assert_eq!((old, new), (200, 216));
    }

    #[tokio::test]
    async fn output_slot_extra_backing_is_admitted_from_the_original_budget() {
        let fixture = Fixture::new(CapabilityBrokerLimits::default());
        let (request, control) = native_request(&fixture, "native-output-slot-extra");
        let session = fixture.session(&request, &control);
        let io = IoRuntime::new(IoLimits::default()).unwrap();
        let call = start(&io, &session).await;
        let transfer = call
            .transfer(IoTransferOptions {
                maximum_chunk_bytes: 16,
                maximum_outstanding_chunks: 1,
            })
            .unwrap();
        let before = control.budget.host_memory_bytes();
        let old = Shared::<Slot>::allocation_bytes().unwrap();
        let new = OutputSlot::<Slot>::allocation_bytes().unwrap();
        let padding = control
            .budget
            .reserve_host_memory(request.budget.memory_bytes - before - old)
            .unwrap();
        let counters = io.snapshot();
        assert!(transfer.output_buffer(16).is_err());
        assert_eq!(io.snapshot(), counters);
        assert_eq!(transfer.outstanding_chunks(), 0);
        assert_eq!(
            control.budget.host_memory_bytes(),
            request.budget.memory_bytes - old
        );
        drop(padding);
        let output = transfer.output_buffer(16).unwrap();
        assert_eq!(
            control.budget.host_memory_bytes(),
            before + new + 2 * (16 + super::super::ALLOCATION_BOOKKEEPING as u64)
        );
        drop(output);
        assert_eq!(control.budget.host_memory_bytes(), before);
    }

    #[tokio::test]
    async fn output_slot_rejects_foreign_authority_and_replacement_owners() {
        let fixture = Fixture::new(CapabilityBrokerLimits::default());
        let (request, control) = native_request(&fixture, "native-output-slot-owner");
        let session = fixture.session(&request, &control);
        let io = IoRuntime::new(IoLimits::default()).unwrap();
        let call = start(&io, &session).await;
        let scope = Arc::new(session.reserve_stream().unwrap());
        let options = IoTransferOptions {
            maximum_chunk_bytes: 16,
            maximum_outstanding_chunks: 1,
        };
        assert!(call.transfer_for_stream(options, &scope).is_err());
        let transfer = call.transfer(options).unwrap();
        let mut buffer = transfer.output_buffer(16).unwrap();
        let error = buffer
            .retain_stream_owner((), scope.reserve_bound_chunk(16).unwrap())
            .err()
            .unwrap();
        assert_eq!(error.code, latent_core::PlatformErrorCode::PermissionDenied);

        // Install directly only to exercise the slot's replacement checks;
        // the public path above cannot accept this non-stream provider.
        buffer
            .slot
            .retain_stream((), scope.reserve_bound_chunk(16).unwrap(), &control.budget)
            .unwrap();
        assert!(buffer.retain_owner(Arc::new(())).is_err());
        assert!(buffer
            .slot
            .retain_stream((), scope.reserve_bound_chunk(16).unwrap(), &control.budget)
            .is_err());
        buffer.spare_mut().unwrap()[0] = 42;
        buffer.advance_written(1).unwrap();
        let mut output = buffer.finish().unwrap();
        assert!(output.retain_owner(Arc::new(())).is_err());
        let copy = output.copy_bytes().unwrap();
        drop(output);
        assert_eq!(copy.as_ref(), &[42]);
        drop(copy);
        assert_eq!(transfer.outstanding_chunks(), 0);
    }

    #[tokio::test]
    async fn output_slot_stream_arc_is_prepaid_before_allocation() {
        let fixture = Fixture::new(CapabilityBrokerLimits::default());
        let (request, control) = native_request(&fixture, "native-stream-chunk-backing");
        let session = fixture.session(&request, &control);
        let io = IoRuntime::new(IoLimits::default()).unwrap();
        let call = start(&io, &session).await;
        let transfer = call
            .transfer(IoTransferOptions {
                maximum_chunk_bytes: 16,
                maximum_outstanding_chunks: 1,
            })
            .unwrap();
        let scope = Arc::new(session.reserve_stream().unwrap());
        let baseline = control.budget.host_memory_bytes();
        let mut buffer = transfer.output_buffer(16).unwrap();
        let before = control.budget.host_memory_bytes();
        let bytes = super::super::stream_chunk_owner_allocation_bytes::<()>().unwrap() as u64;
        let padding = control
            .budget
            .reserve_host_memory(request.budget.memory_bytes - before - bytes + 1)
            .unwrap();
        assert!(buffer
            .slot
            .retain_stream((), scope.reserve_bound_chunk(16).unwrap(), &control.budget)
            .is_err());
        assert!(!buffer.slot.has_stream());
        drop(padding);
        assert_eq!(control.budget.host_memory_bytes(), before);
        buffer
            .slot
            .retain_stream((), scope.reserve_bound_chunk(16).unwrap(), &control.budget)
            .unwrap();
        assert_eq!(control.budget.host_memory_bytes(), before + bytes);
        drop(buffer);
        assert_eq!(control.budget.host_memory_bytes(), baseline);
    }

    #[tokio::test]
    async fn output_slot_keeps_legacy_generic_ownership_and_refunds() {
        let fixture = Fixture::new(CapabilityBrokerLimits::default());
        let (request, control) = fixture.request("legacy-output-slot");
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
        let mut buffer = transfer.output_buffer(16).unwrap();
        assert!(buffer.slot.billing_is_absent_for_test());
        let owner = Arc::new(());
        buffer.retain_owner(owner.clone()).unwrap();
        buffer.spare_mut().unwrap()[0] = 7;
        buffer.advance_written(1).unwrap();
        let mut output = buffer.finish().unwrap();
        let copy = output.copy_bytes().unwrap();
        assert_eq!(Arc::strong_count(&owner), 3);
        drop(output);
        assert_eq!(Arc::strong_count(&owner), 2);
        drop(copy);
        assert_eq!(Arc::strong_count(&owner), 1);
        assert_eq!(transfer.outstanding_chunks(), 0);
        assert_eq!(control.budget.host_memory_bytes(), 0);
        drop((transfer, call));
        assert_eq!(io.snapshot(), super::super::IoSnapshot::default());
    }

    #[tokio::test]
    async fn output_slot_payload_panic_keeps_original_billing_until_cleanup() {
        struct Probe {
            budget: latent_core::ActivationBudget,
            minimum: u64,
            drops: Arc<AtomicUsize>,
            _original_connection: latent_core::HostMemoryReservation,
        }
        impl Drop for Probe {
            fn drop(&mut self) {
                assert!(self.budget.host_memory_bytes() >= self.minimum);
                eprintln!("LSF_OUTPUT_SLOT_OWNER_DROP");
                self.drops.fetch_add(1, Ordering::SeqCst);
            }
        }

        let fixture = Fixture::new(CapabilityBrokerLimits::default());
        let (request, control) = native_request(&fixture, "output-slot-panic");
        let session = fixture.session(&request, &control);
        let io = IoRuntime::new(IoLimits::default()).unwrap();
        let call = start(&io, &session).await;
        let transfer = call
            .transfer(IoTransferOptions {
                maximum_chunk_bytes: 16,
                maximum_outstanding_chunks: 1,
            })
            .unwrap();
        let scope = Arc::new(session.reserve_stream().unwrap());
        let baseline = control.budget.host_memory_bytes();
        let reservations = control.budget.outstanding_reservations();
        let mut original = scope.reserve_host_memory(16 * 1024).unwrap();
        original.confirm();
        let mut buffer = transfer.output_buffer(16).unwrap();
        let payload = buffer.slot.payload_address_for_test();
        let (_, offset) = std::alloc::Layout::new::<[AtomicUsize; 2]>()
            .extend(std::alloc::Layout::new::<Slot>())
            .unwrap();
        let drops = Arc::new(AtomicUsize::new(0));
        buffer
            .slot
            .retain_stream(
                Probe {
                    budget: control.budget.clone(),
                    minimum: baseline
                        + 16 * 1024
                        + OutputSlot::<Slot>::allocation_bytes().unwrap()
                        + super::super::stream_chunk_owner_allocation_bytes::<Probe>().unwrap()
                            as u64,
                    drops: drops.clone(),
                    _original_connection: original,
                },
                scope.reserve_bound_chunk(16).unwrap(),
                &control.budget,
            )
            .unwrap();
        buffer.spare_mut().unwrap()[0] = 1;
        buffer.advance_written(1).unwrap();
        let mut output = buffer.finish().unwrap();
        let copy = output.copy_bytes().unwrap();
        drop(output);
        if let Some(path) = std::env::var_os("LSF_OUTPUT_SLOT_WATCH_FILE") {
            std::fs::write(path, format!("{:x}", payload - offset)).unwrap();
        }
        PANIC_SLOT_ADDRESS.store(payload, Ordering::SeqCst);
        let panic = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| drop(copy)));
        assert!(panic.is_err());
        assert_eq!(PANIC_SLOT_ADDRESS.load(Ordering::SeqCst), 0);
        assert_eq!(drops.load(Ordering::SeqCst), 1);
        assert_eq!(transfer.outstanding_chunks(), 0);
        assert_eq!(control.budget.host_memory_bytes(), baseline);
        assert_eq!(control.budget.outstanding_reservations(), reservations);
    }

    #[tokio::test]
    async fn output_slot_stream_owner_panic_and_caller_unwind_refund_after_retirement() {
        struct Probe {
            budget: latent_core::ActivationBudget,
            minimum: u64,
            drops: Arc<AtomicUsize>,
            panic: bool,
            _original_connection: latent_core::HostMemoryReservation,
        }
        impl Drop for Probe {
            fn drop(&mut self) {
                assert!(self.budget.host_memory_bytes() >= self.minimum);
                self.drops.fetch_add(1, Ordering::SeqCst);
                eprintln!("LSF_STREAM_CHUNK_OWNER_DROP");
                assert!(!self.panic, "controlled stream owner destructor");
            }
        }

        let fixture = Fixture::new(CapabilityBrokerLimits::default());
        let (request, control) = native_request(&fixture, "stream-chunk-panic");
        let session = fixture.session(&request, &control);
        let io = IoRuntime::new(IoLimits::default()).unwrap();
        let call = start(&io, &session).await;
        let transfer = call
            .transfer(IoTransferOptions {
                maximum_chunk_bytes: 16,
                maximum_outstanding_chunks: 1,
            })
            .unwrap();
        let scope = Arc::new(session.reserve_stream().unwrap());
        let baseline = control.budget.host_memory_bytes();
        let reservations = control.budget.outstanding_reservations();
        for mode in 0..2 {
            let mut original = scope.reserve_host_memory(16 * 1024).unwrap();
            original.confirm();
            let mut buffer = transfer.output_buffer(16).unwrap();
            let drops = Arc::new(AtomicUsize::new(0));
            let chunk_bytes = super::super::stream_chunk_owner_allocation_bytes::<Probe>().unwrap();
            buffer
                .slot
                .retain_stream(
                    Probe {
                        budget: control.budget.clone(),
                        minimum: baseline
                            + 16 * 1024
                            + OutputSlot::<Slot>::allocation_bytes().unwrap()
                            + chunk_bytes as u64,
                        drops: drops.clone(),
                        panic: mode == 0,
                        _original_connection: original,
                    },
                    scope.reserve_bound_chunk(16).unwrap(),
                    &control.budget,
                )
                .unwrap();
            if mode == 0 {
                if let Some(path) = std::env::var_os("LSF_OUTPUT_SLOT_WATCH_FILE") {
                    let header = buffer.slot.stream_header_for_test::<Probe>().unwrap();
                    std::fs::write(path, format!("{header:x}")).unwrap();
                }
            }
            buffer.spare_mut().unwrap()[0] = 1;
            buffer.advance_written(1).unwrap();
            let mut output = buffer.finish().unwrap();
            let copy = output.copy_bytes().unwrap();
            drop(output);
            let panic = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
                if mode == 0 {
                    drop(copy);
                } else {
                    let _copy = copy;
                    panic!("controlled caller unwind");
                }
            }));
            assert!(panic.is_err());
            assert_eq!(drops.load(Ordering::SeqCst), 1);
            assert_eq!(transfer.outstanding_chunks(), 0);
            assert_eq!(control.budget.host_memory_bytes(), baseline);
            assert_eq!(control.budget.outstanding_reservations(), reservations);
        }
    }

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
    async fn http_input_owner_uses_original_budget_until_last_clone_and_unwind() {
        use std::sync::atomic::{AtomicBool, Ordering};

        struct ObserveDrop {
            budget: latent_core::ActivationBudget,
            io: Arc<IoRuntime>,
            host: u64,
            metadata: usize,
            observed: Arc<AtomicBool>,
            panic: bool,
        }
        impl Drop for ObserveDrop {
            fn drop(&mut self) {
                self.observed.store(
                    self.budget.host_memory_bytes() == self.host
                        && self.io.snapshot().metadata_bytes == self.metadata,
                    Ordering::SeqCst,
                );
                assert!(!self.panic, "controlled input owner destructor");
            }
        }

        let fixture = Fixture::new(CapabilityBrokerLimits::default());
        for mode in 0..3 {
            let (request, control) = native_request(&fixture, "http-input-retirement");
            let session = fixture.session(&request, &control);
            let io = Arc::new(IoRuntime::new(IoLimits::default()).unwrap());
            let call = start(&io, &session).await;
            let transfer = call
                .transfer(IoTransferOptions {
                    maximum_chunk_bytes: 16,
                    maximum_outstanding_chunks: 1,
                })
                .unwrap();
            let baseline = control.budget.host_memory_bytes();
            let counts = io.snapshot();
            let charge = http_input_owner_bytes().unwrap();
            let mut input = transfer.input(b"data".to_vec()).unwrap();
            let observed = Arc::new(AtomicBool::new(false));
            input
                .retain_owner(Arc::new(ObserveDrop {
                    budget: control.budget.clone(),
                    io: Arc::clone(&io),
                    host: baseline + charge as u64,
                    metadata: counts.metadata_bytes + charge,
                    observed: Arc::clone(&observed),
                    panic: mode == 1,
                }))
                .unwrap();
            let before = control.budget.host_memory_bytes();
            let before_metadata = io.snapshot().metadata_bytes;
            let bytes = input.into_http_bytes().unwrap();
            assert_eq!(&bytes[..], b"data");
            assert_eq!(control.budget.host_memory_bytes(), before + charge as u64);
            assert_eq!(io.snapshot().metadata_bytes, before_metadata + charge);
            let clone = bytes.clone();
            drop(bytes);
            assert!(!observed.load(Ordering::SeqCst));
            assert_eq!(control.budget.host_memory_bytes(), before + charge as u64);
            let result = std::panic::catch_unwind(std::panic::AssertUnwindSafe(move || {
                if mode == 2 {
                    let _caller_owner = clone;
                    panic!("controlled caller unwind");
                }
                drop(clone);
            }));
            assert_eq!(result.is_err(), mode != 0);
            assert!(observed.load(Ordering::SeqCst));
            assert_eq!(control.budget.host_memory_bytes(), baseline);
            assert_eq!(io.snapshot(), counts);
        }
    }

    #[tokio::test]
    async fn http_input_owner_refuses_original_host_and_metadata_exhaustion() {
        let fixture = Fixture::new(CapabilityBrokerLimits::default());
        let (request, control) = native_request(&fixture, "http-input-refusal");
        let session = fixture.session(&request, &control);
        let io = IoRuntime::new(IoLimits::default()).unwrap();
        let call = start(&io, &session).await;
        let transfer = call
            .transfer(IoTransferOptions {
                maximum_chunk_bytes: 16,
                maximum_outstanding_chunks: 1,
            })
            .unwrap();
        let baseline = control.budget.host_memory_bytes();
        let counts = io.snapshot();
        let charge = http_input_owner_bytes().unwrap();

        let input = transfer.input(b"host".to_vec()).unwrap();
        let current = control.budget.host_memory_bytes();
        let padding_bytes = request.budget.memory_bytes - current - charge as u64 + 1;
        let padding = control.budget.reserve_host_memory(padding_bytes).unwrap();
        assert_eq!(
            input.into_http_bytes().err().unwrap().code,
            latent_core::PlatformErrorCode::ResourceExhausted
        );
        assert_eq!(control.budget.host_memory_bytes(), baseline + padding_bytes);
        assert_eq!(io.snapshot(), counts);
        assert_eq!(transfer.outstanding_chunks(), 0);
        drop(padding);

        let input = transfer.input(b"node".to_vec()).unwrap();
        let padding = call
            .operation
            .runtime
            .counters
            .acquire(
                Kind::Metadata,
                IoLimits::default().maximum_metadata_bytes - io.snapshot().metadata_bytes - charge
                    + 1,
            )
            .unwrap();
        assert_eq!(
            input.into_http_bytes().err().unwrap().code,
            latent_core::PlatformErrorCode::ResourceExhausted
        );
        assert_eq!(control.budget.host_memory_bytes(), baseline);
        assert_eq!(transfer.outstanding_chunks(), 0);
        drop(padding);
        assert_eq!(io.snapshot(), counts);
    }

    #[tokio::test]
    async fn http_input_owner_preserves_legacy_phase1_path() {
        let fixture = Fixture::new(CapabilityBrokerLimits::default());
        let (request, control) = fixture.request("http-input-phase1");
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
        let baseline = io.snapshot();
        let input = transfer.input(b"old".to_vec()).unwrap();
        let before = io.snapshot();
        let bytes = input.into_http_bytes().unwrap();
        assert_eq!(&bytes[..], b"old");
        assert_eq!(io.snapshot(), before);
        assert_eq!(control.budget.host_memory_bytes(), 0);
        drop(bytes);
        assert_eq!(io.snapshot(), baseline);
    }

    #[tokio::test]
    async fn http_input_owner_preserves_finalized_budget_error() {
        let fixture = Fixture::new(CapabilityBrokerLimits::default());
        let (request, control) = native_request(&fixture, "http-input-finalized");
        let session = fixture.session(&request, &control);
        let io = IoRuntime::new(IoLimits::default()).unwrap();
        let call = start(&io, &session).await;
        let transfer = call
            .transfer(IoTransferOptions {
                maximum_chunk_bytes: 16,
                maximum_outstanding_chunks: 1,
            })
            .unwrap();
        let counts = io.snapshot();
        let input = transfer.input(b"data".to_vec()).unwrap();
        let _ = control.budget.finalize_at(None, Instant::now());
        let error = input.into_http_bytes().err().unwrap();
        let expected = latent_core::BudgetError::AccountingFinalized.to_platform_error();
        assert_eq!(error.code, expected.code);
        assert_eq!(error.details, expected.details);
        assert_eq!(io.snapshot(), counts);
        assert_eq!(transfer.outstanding_chunks(), 0);
    }

    #[test]
    fn http_input_owner_layout_matches_pinned_allocator_shape() {
        let size = bytes::Bytes::owner_with_retirement_allocation_size::<
            IoInputChunk,
            super::super::memory::HttpInputRetirement,
        >();
        let charge = http_input_owner_bytes().unwrap();
        assert_eq!(charge, size + super::super::ALLOCATION_BOOKKEEPING);
        eprintln!(
            "HTTP input: value={}, retirement={}, optional={}, Box={}, charge={charge}",
            std::mem::size_of::<IoInputChunk>(),
            std::mem::size_of::<super::super::memory::HttpInputRetirement>(),
            std::mem::size_of::<Option<super::super::memory::HttpInputRetirement>>(),
            size
        );
        #[cfg(all(target_arch = "x86_64", target_os = "linux"))]
        assert_eq!(
            (
                std::mem::size_of::<IoInputChunk>(),
                std::mem::align_of::<IoInputChunk>(),
                std::mem::size_of::<super::super::memory::HttpInputRetirement>(),
                std::mem::align_of::<super::super::memory::HttpInputRetirement>(),
                std::mem::size_of::<Option<super::super::memory::HttpInputRetirement>>(),
                size,
            ),
            (168, 8, 48, 8, 48, 224)
        );
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
        let slot_bytes = OutputSlot::<Slot>::allocation_bytes().unwrap();
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
        let generic_owner = Arc::new(());
        output.retain_owner(generic_owner.clone()).unwrap();
        let before = control.budget.host_memory_bytes();
        let copy = output.copy_bytes().unwrap();
        assert_eq!(Arc::strong_count(&generic_owner), 3);
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
        assert_eq!(Arc::strong_count(&generic_owner), 2);
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
        assert_eq!(Arc::strong_count(&generic_owner), 1);
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
        let old_shell = Shared::<OriginalTransfer>::allocation_bytes().unwrap();
        let options = IoTransferOptions {
            maximum_chunk_bytes: 64,
            maximum_outstanding_chunks: 1,
        };
        if shell > old_shell {
            let padding = control
                .budget
                .reserve_host_memory(request.budget.memory_bytes - baseline - old_shell)
                .unwrap();
            assert!(call.transfer(options).is_err());
            assert!(!call.operation.execution.lock().unwrap().transfer_issued);
            assert_eq!(io.snapshot().streams, 0);
            drop(padding);
        }
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
            base + OutputSlot::<Slot>::allocation_bytes().unwrap()
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
                + OutputSlot::<Slot>::allocation_bytes().unwrap()
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
        assert_eq!(control.budget.host_memory_bytes(), before);

        let mut cancelled = first.prepare_input(8).unwrap();
        control.probe.0.store(true, Ordering::SeqCst);
        // Capturing is deliberately inert even after cancellation. The later
        // original-operation check refuses before a transport owner is formed.
        assert!(cancelled.capture(b"cancel"));
        assert!(first.finish_prepared_input(cancelled).is_err());
        assert_eq!(first.outstanding_chunks(), 0);
        assert_eq!(first.accepted_input_bytes(), 0);
        assert_eq!(io.snapshot().staged_bytes, 0);
        assert_eq!(control.budget.host_memory_bytes(), before);
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

    #[tokio::test]
    async fn prepared_input_requires_capture_and_spends_the_original_cumulative_budget() {
        let fixture = Fixture::new(CapabilityBrokerLimits::default());
        let (request, control) = native_request(&fixture, "prepared-input-total");
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
        let before = control.budget.host_memory_bytes();
        let uncaptured = transfer.prepare_input(16).unwrap();
        assert_eq!(uncaptured.captured_len(), None);
        assert!(transfer.finish_prepared_input(uncaptured).is_err());
        assert_eq!(transfer.outstanding_chunks(), 0);
        assert_eq!(io.snapshot().staged_bytes, 0);
        assert_eq!(control.budget.host_memory_bytes(), before);

        for _ in 0..8 {
            let mut prepared = transfer.prepare_input(16).unwrap();
            assert!(prepared.capture(&[7; 16]));
            assert_eq!(prepared.captured_len(), Some(16));
            drop(transfer.finish_prepared_input(prepared).unwrap());
        }
        assert_eq!(transfer.accepted_input_bytes(), 128);
        let mut exhausted = transfer.prepare_input(1).unwrap();
        assert!(exhausted.capture(&[8]));
        assert!(transfer.finish_prepared_input(exhausted).is_err());
        assert_eq!(transfer.accepted_input_bytes(), 128);
        assert_eq!(transfer.outstanding_chunks(), 0);
        assert_eq!(io.snapshot().staged_bytes, 0);
        assert_eq!(control.budget.host_memory_bytes(), before);
        drop((transfer, call));
        assert_eq!(io.snapshot(), super::super::IoSnapshot::default());
        assert_eq!(control.budget.host_memory_bytes(), baseline);
    }
}
