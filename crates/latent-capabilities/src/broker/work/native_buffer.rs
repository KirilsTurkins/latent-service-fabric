//! The original copied byte allocation, zeroed and freed before its refund.
use crate::broker::capacity;
use latent_core::{ActivationBudget, HostMemoryReservation, PlatformError};
use std::ops::Deref;
use zeroize::Zeroizing;

// Field order is the lifetime contract: Zeroizing clears the original Vec,
// then Vec deallocates its backing, then the physical-only guard can refund.
// No mutable Vec, Clone, auxiliary allocation or detached guard can escape.
pub(in crate::broker) struct NativeBuffer {
    bytes: Zeroizing<Vec<u8>>,
    _native_owned: Option<HostMemoryReservation>,
}

impl NativeBuffer {
    pub(super) fn empty() -> Self {
        Self {
            bytes: Zeroizing::new(Vec::new()),
            _native_owned: None,
        }
    }

    pub(in crate::broker) fn copy(
        budget: &ActivationBudget,
        source: &[u8],
    ) -> Result<Self, PlatformError> {
        if source.is_empty() {
            return Ok(Self::empty());
        }
        let mut native = if budget.profile().supports_descendants() {
            let bytes = u64::try_from(source.len())
                .ok()
                .and_then(|bytes| bytes.checked_add(64))
                .ok_or_else(capacity)?;
            Some(
                budget
                    .reserve_host_memory(bytes)
                    .map_err(|e| e.to_platform_error())?,
            )
        } else {
            None
        };
        // Pinned Rust's u8 slice-to-Vec copy requests exactly len bytes; the
        // independent allocator bookkeeping allowance was admitted above.
        let bytes = Zeroizing::new(source.to_vec());
        debug_assert_eq!(bytes.capacity(), source.len());
        if let Some(native) = &mut native {
            native.confirm();
        }
        Ok(Self {
            bytes,
            _native_owned: native,
        })
    }

    #[cfg(test)]
    pub(in crate::broker) fn capacity(&self) -> usize {
        self.bytes.capacity()
    }

    #[cfg(test)]
    pub(in crate::broker) fn charged_to(&self, budget: &ActivationBudget) -> bool {
        self._native_owned
            .as_ref()
            .is_some_and(|memory| memory.is_from_budget(budget))
    }
}

impl Deref for NativeBuffer {
    type Target = [u8];
    fn deref(&self) -> &[u8] {
        self.bytes.as_slice()
    }
}
