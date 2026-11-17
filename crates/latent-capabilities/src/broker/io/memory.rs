//! Reservations for already bounded typed host values and protocol state.
//! The adapter stores data before this guard in its owner, or shares the guard
//! with the actual byte owner. This avoids allocating a second dummy byte buffer.
use super::{capacity, denied, Charge, IoAdmission, IoCall, Kind, OperationOwner, PlatformError};

// Retained outside the Bytes allocation, and dropped only after its header and
// input owner have physically retired. Both charges belong to the original call.
pub(in crate::broker) struct HttpInputRetirement {
    host: latent_core::budget::HostMemoryReservation,
    _metadata: Charge,
}

impl HttpInputRetirement {
    pub(in crate::broker) fn confirm(&mut self) {
        self.host.confirm();
    }
}

pub struct IoMemory {
    host: Option<latent_core::budget::HostMemoryReservation>,
    _bytes: Charge,
    _metadata: Charge,
    _slot: Charge,
    _operation: OperationOwner,
}
// Identity/provenance only. No upgrade or authority API is exposed.
pub(in crate::broker) struct HttpInputOrigin {
    _operation: super::OperationWeak,
}
impl IoMemory {
    pub(in crate::broker) fn reserve_http_body_owner(
        &self,
        expected: Option<&super::super::session::SessionCoreOwner>,
        bytes: usize,
    ) -> Result<Option<HttpInputRetirement>, PlatformError> {
        self._operation.with_session(|session| {
            if expected.is_some_and(|original| !super::Shared::ptr_eq(&session.core, original)) {
                return Err(denied());
            }
            // Phase 1 keeps the original logical-only behavior. Native profiles
            // reserve from this exact operation's existing session and node.
            if !session.core.budget.profile().supports_descendants() {
                return Ok(None);
            }
            let metadata = self
                ._operation
                .runtime
                .counters
                .acquire(Kind::Metadata, bytes)?;
            let host = session
                .core
                .budget
                .reserve_host_memory(u64::try_from(bytes).map_err(|_| capacity())?)
                .map_err(|failure| failure.to_platform_error())?;
            Ok(Some(HttpInputRetirement {
                host,
                _metadata: metadata,
            }))
        })
    }

    pub(super) fn reserve_http_input_owner(
        &self,
        bytes: usize,
    ) -> Result<Option<HttpInputRetirement>, PlatformError> {
        self._operation.with_session(|session| {
            let Some(original) = &self.host else {
                // The old logical-only profile has no host ledger. Do not
                // silently use that path for a native-accounted transfer.
                return if session.core.budget.profile().supports_descendants() {
                    Err(denied())
                } else {
                    Ok(None)
                };
            };
            if !original.is_from_budget(&session.core.budget) {
                return Err(denied());
            }
            let metadata = self
                ._operation
                .runtime
                .counters
                .acquire(Kind::Metadata, bytes)?;
            let host = session
                .core
                .budget
                .reserve_host_memory(u64::try_from(bytes).map_err(|_| capacity())?)
                .map_err(|failure| failure.to_platform_error())?;
            Ok(Some(HttpInputRetirement {
                host,
                _metadata: metadata,
            }))
        })
    }
    pub(in crate::broker) fn http_checkpoint(&self) -> Result<(), PlatformError> {
        self._operation.check()
    }
    pub(in crate::broker) fn http_origin(&self) -> HttpInputOrigin {
        HttpInputOrigin {
            _operation: super::Shared::downgrade(&self._operation),
        }
    }
    pub(in crate::broker) fn http_original_session(
        &self,
        original: &super::super::session::SessionCoreOwner,
    ) -> bool {
        self._operation
            .with_session(|session| super::Shared::ptr_eq(&session.core, original))
    }
    pub(super) fn reserve(
        operation: &OperationOwner,
        bytes: usize,
        metadata: usize,
    ) -> Result<Self, PlatformError> {
        Self::reserve_inner(operation, bytes, metadata, false)
    }
    pub(super) fn reserve_host(
        operation: &OperationOwner,
        bytes: usize,
        metadata: usize,
    ) -> Result<Self, PlatformError> {
        Self::reserve_inner(operation, bytes, metadata, true)
    }
    fn reserve_inner(
        operation: &OperationOwner,
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
            Some(operation.with_session(|session| {
                let bytes = bytes
                    .checked_add(super::ALLOCATION_BOOKKEEPING)
                    .and_then(|n| u64::try_from(n).ok())
                    .ok_or_else(capacity)?;
                session
                    .core
                    .budget
                    .reserve_host_memory(bytes)
                    .map_err(|_| capacity())
            })?)
        } else {
            None
        };
        Ok(Self {
            host: native,
            _bytes: charge,
            _metadata: meta,
            _slot: slot,
            _operation: operation.clone(),
        })
    }
    pub(super) fn belongs_to(&self, operation: &OperationOwner) -> bool {
        super::Shared::ptr_eq(&self._operation, operation)
    }
    #[cfg(test)]
    pub(super) fn charged_to(&self, budget: &latent_core::ActivationBudget) -> bool {
        self.host
            .as_ref()
            .is_some_and(|guard| guard.is_from_budget(budget))
    }
    pub(super) fn confirm_host_capacity(
        &mut self,
        capacity_bytes: usize,
    ) -> Result<(), PlatformError> {
        if capacity_bytes == 0 {
            return Ok(());
        }
        if let Some(native) = &mut self.host {
            let bytes = capacity_bytes
                .checked_add(super::ALLOCATION_BOOKKEEPING)
                .and_then(|n| u64::try_from(n).ok())
                .ok_or_else(capacity)?;
            if bytes > native.bytes() {
                return Err(capacity());
            }
            // An unused larger maximum remains reserved, never reported physical.
            native.confirm_bytes(bytes);
        }
        Ok(())
    }
}
impl IoAdmission {
    /// Copy a synchronous borrowed ingress into this admission's actual paid
    /// buffer. Allocate/reserve first; no borrowed Store slice enters an owner.
    pub fn copy_input(
        &self,
        source: &[u8],
        metadata: usize,
    ) -> Result<super::IoBuffer, PlatformError> {
        let mut input = self.input(source.len().max(1), metadata)?;
        input.spare_mut()?[..source.len()].copy_from_slice(source);
        input.advance_written(source.len())?;
        Ok(input)
    }
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
