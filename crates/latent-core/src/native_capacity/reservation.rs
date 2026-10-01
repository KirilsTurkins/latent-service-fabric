use std::sync::{Arc, Mutex};
use std::time::Instant;

use super::{
    NativeAdmissionClass, NativeBuffer, NativeBufferClass, NativeBufferPermit, NativeCapacityError,
    NativeCapacityOwner, NativeReservationRequest, Owner, MAXIMUM_NATIVE_BUFFER_GUARDS,
};

#[derive(Default)]
pub(super) struct Buffers {
    pub used: [u64; 3],
    pub guards: usize,
}

pub(super) struct Lease {
    pub owner: Arc<Owner>,
    pub class: NativeAdmissionClass,
    pub request: NativeReservationRequest,
    pub bytes: u64,
    pub deadline: Instant,
    pub buffers: Mutex<Buffers>,
}

impl Drop for Lease {
    fn drop(&mut self) {
        let mut state = self.owner.lock_physical();
        let usage = &mut state.usage[self.class.index()];
        usage.slots -= 1;
        usage.bytes -= self.bytes;
        if state.snapshot().physically_retired() {
            state.retired_at = Some(self.owner.clock.monotonic_now());
        }
        drop(state);
        self.owner.wake();
    }
}

/// Non-clone admission. Wrap it in Arc only in the original worker/response
/// owners. Its prepaid global slot/bytes survive until its last real owner drops.
pub struct NativeReservation {
    pub(super) lease: Arc<Lease>,
}

impl NativeReservation {
    pub(super) fn new(
        owner: Arc<Owner>,
        class: NativeAdmissionClass,
        request: NativeReservationRequest,
        bytes: u64,
        deadline: Instant,
    ) -> Self {
        Self {
            lease: Arc::new(Lease {
                owner,
                class,
                request,
                bytes,
                deadline,
                buffers: Mutex::new(Buffers::default()),
            }),
        }
    }

    #[must_use]
    pub fn is_from_owner(&self, owner: &NativeCapacityOwner) -> bool {
        Arc::ptr_eq(&self.lease.owner, &owner.0)
    }

    #[must_use]
    pub fn reserved_bytes(&self) -> u64 {
        self.lease.bytes
    }
    #[must_use]
    pub fn request_bytes(&self) -> u64 {
        self.lease.request.request_bytes
    }
    #[must_use]
    pub fn work_bytes(&self) -> u64 {
        self.lease.request.work_bytes
    }
    #[must_use]
    pub fn response_bytes(&self) -> u64 {
        self.lease.request.response_bytes
    }
    #[must_use]
    pub fn original_deadline(&self) -> Instant {
        self.lease.deadline
    }
    #[must_use]
    pub fn class(&self) -> NativeAdmissionClass {
        self.lease.class
    }

    /// Original deadline and node-close fence. The action must be short, must
    /// not await or perform I/O, and must not recursively acquire this owner.
    pub fn with_live<T>(&self, action: impl FnOnce() -> T) -> Result<T, NativeCapacityError> {
        let state = self
            .lease
            .owner
            .state
            .lock()
            .map_err(|_| NativeCapacityError::Poisoned)?;
        self.lease
            .owner
            .check(&state, self.lease.class, self.lease.deadline)?;
        Ok(action())
    }

    /// Reserve before allocating the actual buffer. Parts cannot borrow each
    /// other's quota; even zero-byte owner shells have a finite sixteen-guard cap.
    pub fn reserve_buffer(
        &self,
        class: NativeBufferClass,
        bytes: u64,
    ) -> Result<NativeBufferPermit, NativeCapacityError> {
        self.with_live(|| {
            let mut buffers = self
                .lease
                .buffers
                .lock()
                .map_err(|_| NativeCapacityError::Poisoned)?;
            if buffers.guards >= MAXIMUM_NATIVE_BUFFER_GUARDS {
                return Err(NativeCapacityError::BufferLimit);
            }
            let used = buffers.used[class.index()]
                .checked_add(bytes)
                .ok_or(NativeCapacityError::BufferTooLarge)?;
            if used > self.lease.request.capacities()[class.index()] {
                return Err(NativeCapacityError::BufferTooLarge);
            }
            buffers.used[class.index()] = used;
            buffers.guards += 1;
            Ok(NativeBufferPermit::new(
                Arc::clone(&self.lease),
                class,
                bytes,
            ))
        })?
    }

    /// An owned fixed-size byte allocation, made only after actual admission.
    pub fn allocate_bytes(
        &self,
        class: NativeBufferClass,
        bytes: usize,
    ) -> Result<NativeBuffer<Vec<u8>>, NativeCapacityError> {
        let amount = u64::try_from(bytes).map_err(|_| NativeCapacityError::BufferTooLarge)?;
        let permit = self.reserve_buffer(class, amount)?;
        let mut buffer = Vec::new();
        buffer
            .try_reserve_exact(bytes)
            .map_err(|_| NativeCapacityError::AllocationFailed)?;
        if buffer.capacity() > bytes {
            return Err(NativeCapacityError::BufferTooLarge);
        }
        buffer.resize(bytes, 0);
        Ok(permit.attach(buffer))
    }
}
