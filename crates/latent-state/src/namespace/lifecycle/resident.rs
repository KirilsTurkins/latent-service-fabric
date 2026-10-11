//! One original native charge follows the actual metadata owner and its pins.
use std::mem::size_of;
use std::sync::Arc;

use latent_core::native_capacity::{
    NativeAdmissionClass, NativeBufferClass, NativeBufferPermit, NativeCapacityError,
    NativeCapacityOwner, NativeReservation,
};

use super::{
    NamespaceError, NamespaceLifecycleCompletion, NamespaceLifecycleHandle,
    NamespaceLifecycleLimits, Owner, Stamp,
};

const SLOT_BYTES: u64 = 3072;
const PIN_BYTES: u64 = 128;
const OWNER_BYTES: u64 = 4096;
const MAXIMUM_BYTES: u64 = 16 * 1024 * 1024;

// A slot covers three simultaneous records during resolution (the old record,
// pending record and replacement clone), each with two <=256-byte identities
// and the exact 71-byte schema, plus nine 64-byte allocation envelopes, its
// stamp/Arc/vector entry and one affine completion. Handles are charged apart.
const _: () = assert!(size_of::<Stamp>() <= 512);
const _: () = assert!(size_of::<NamespaceLifecycleCompletion>() <= 128);
const _: () = assert!(size_of::<NamespaceLifecycleHandle>() <= 128);
const _: () = assert!(size_of::<Owner>() <= 4096);
const _: () = assert!(
    3 * (2 * super::super::IDENTITY_BYTES + 71) + 9 * 64 + 512 + 64 + 16 + 128
        <= SLOT_BYTES as usize
);

pub(super) fn memory_bytes(limits: NamespaceLifecycleLimits) -> Result<u64, NamespaceError> {
    if !(1..=4096).contains(&limits.namespaces) || !(1..=4096).contains(&limits.owners) {
        return Err(NamespaceError::Invalid);
    }
    let namespaces = u64::try_from(limits.namespaces).map_err(|_| NamespaceError::Capacity)?;
    let owners = u64::try_from(limits.owners).map_err(|_| NamespaceError::Capacity)?;
    let bytes = namespaces
        .checked_mul(SLOT_BYTES)
        .and_then(|bytes| {
            owners
                .checked_mul(PIN_BYTES)
                .and_then(|pins| bytes.checked_add(pins))
        })
        .and_then(|bytes| bytes.checked_add(OWNER_BYTES))
        .and_then(|bytes| bytes.checked_add(OWNER_BYTES - 1))
        .map(|bytes| bytes / OWNER_BYTES * OWNER_BYTES)
        .ok_or(NamespaceError::Capacity)?;
    if bytes > MAXIMUM_BYTES {
        return Err(NamespaceError::Capacity);
    }
    Ok(bytes)
}

pub(super) struct ResidentMetadata {
    _memory: NativeBufferPermit,
    original: Arc<NativeReservation>,
}

impl ResidentMetadata {
    pub(super) fn new(
        limits: NamespaceLifecycleLimits,
        native: &NativeCapacityOwner,
        original: Arc<NativeReservation>,
    ) -> Result<Self, NamespaceError> {
        let bytes = memory_bytes(limits)?;
        if !original.is_from_owner(native) || original.class() != NativeAdmissionClass::Recovery {
            return Err(NamespaceError::Invalid);
        }
        // This original no-I/O gate precedes metadata allocation. After startup
        // its deadline never acts as namespace permission: each operation still
        // needs its own original policy/request and current lifecycle fence.
        let memory = original
            .reserve_buffer(NativeBufferClass::Work, bytes)
            .map_err(memory_error)?;
        Ok(Self {
            _memory: memory,
            original,
        })
    }

    pub(super) fn uses_native_capacity(&self, native: &NativeCapacityOwner) -> bool {
        self.original.is_from_owner(native)
    }

    pub(super) fn check_live(&self) -> Result<(), NamespaceError> {
        self.original.with_live(|| ()).map_err(memory_error)
    }
}

fn memory_error(error: NativeCapacityError) -> NamespaceError {
    match error {
        NativeCapacityError::AdmissionClosed | NativeCapacityError::DeadlineExceeded => {
            NamespaceError::Unavailable
        }
        NativeCapacityError::Quarantined | NativeCapacityError::Poisoned => {
            NamespaceError::RecoveryRequired
        }
        _ => NamespaceError::Capacity,
    }
}
