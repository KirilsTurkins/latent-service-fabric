use std::sync::Arc;

use super::reservation::Lease;
use super::NativeBufferClass;

/// Affine subreservation for one actual trusted native buffer. Attach the owned
/// value immediately after allocation, or retain this permit beside its original
/// worker/response owner. No cloning or independent ledger finalization refunds it.
pub struct NativeBufferPermit {
    lease: Arc<Lease>,
    class: NativeBufferClass,
    bytes: u64,
}

impl NativeBufferPermit {
    pub(super) fn new(lease: Arc<Lease>, class: NativeBufferClass, bytes: u64) -> Self {
        Self {
            lease,
            class,
            bytes,
        }
    }

    #[must_use]
    pub fn bytes(&self) -> u64 {
        self.bytes
    }

    /// Trusted native constructors must stay within the already admitted bound.
    /// Owned value destruction precedes this permit's physical quota release.
    pub fn attach<T>(self, value: T) -> NativeBuffer<T> {
        NativeBuffer {
            value,
            permit: self,
        }
    }
}

impl Drop for NativeBufferPermit {
    fn drop(&mut self) {
        let mut buffers = self
            .lease
            .buffers
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        buffers.used[self.class.index()] -= self.bytes;
        buffers.guards -= 1;
    }
}

/// Field order preserves physical value destruction before its affine charge.
pub struct NativeBuffer<T> {
    value: T,
    permit: NativeBufferPermit,
}

impl<T> NativeBuffer<T> {
    #[must_use]
    pub fn get(&self) -> &T {
        &self.value
    }
    #[must_use]
    pub fn reserved_bytes(&self) -> u64 {
        self.permit.bytes()
    }

    /// Move both together into an existing worker/frame owner; retaining the
    /// permit through the value's actual destruction remains mandatory.
    pub fn into_parts(self) -> (T, NativeBufferPermit) {
        (self.value, self.permit)
    }
}

impl NativeBuffer<Vec<u8>> {
    /// Write existing bytes without extending their already admitted capacity.
    pub fn as_mut_slice(&mut self) -> &mut [u8] {
        self.value.as_mut_slice()
    }
}
