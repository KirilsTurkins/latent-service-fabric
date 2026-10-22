//! Immutable returned bytes retain their original memory owner through clones.
//! Input Payload remains Vec. Only completed result ownership uses this type.
use std::{cell::RefCell, fmt, ops::Deref};

use bytes::Bytes;

use crate::{ActivationBudget, BudgetDimension, BudgetError, HostMemoryReservation};

/// Result clones share bytes and their exact affine reservation. Conversion to
/// transport Bytes also transfers the original owner instead of copying a Vec.
#[derive(Clone, Default)]
pub struct ResultPayload {
    bytes: Bytes,
    capacity: usize,
}

struct Accounted {
    // Rust drops fields in declaration order: storage disappears before refund.
    bytes: Vec<u8>,
    memory: RefCell<HostMemoryReservation>,
    // Original returned bytes are execution/result ownership, unlike a dead
    // Arc header's physical-memory-only guard. Bytes clones share this owner.
    _accounting: ActivationBudget,
}
// Locked bytes1.12.1 src/bytes.rs::Owned<T> adds one AtomicUsize to T.
// Bound that field, either field ordering's alignment padding, and the same
// conservative allocator bookkeeping escrow used by original native owners.
// The escrow covers both the original Vec's allocation metadata and the new
// owner's Box metadata. This is a capacity bound, not an RSS measurement.
const OWNER_ESCROW_BYTES: usize = 256;
const OWNER_LAYOUT_BOUND: usize =
    size_of::<Accounted>() + size_of::<usize>() + 2 * align_of::<Accounted>() + 64;
const _: () = assert!(OWNER_LAYOUT_BOUND + 64 <= OWNER_ESCROW_BYTES);

impl AsRef<[u8]> for Accounted {
    fn as_ref(&self) -> &[u8] {
        // Bytes::from_owner calls this once after its real owner Box exists.
        // The returned immutable view never accesses this RefCell again.
        self.memory.borrow_mut().confirm();
        &self.bytes
    }
}
impl ResultPayload {
    /// Capacity includes unused allocation, preserving existing retained bounds.
    #[must_use]
    pub fn capacity(&self) -> usize {
        self.capacity
    }

    #[must_use]
    pub fn as_slice(&self) -> &[u8] {
        &self.bytes
    }

    /// The caller must already own the Vec's storage reservation. This adds the
    /// bounded Bytes owner allocation before constructing it, on the same ledger.
    pub fn from_reserved(
        bytes: Vec<u8>,
        memory: HostMemoryReservation,
        budget: &ActivationBudget,
    ) -> Result<Self, BudgetError> {
        let capacity = bytes.capacity();
        // Bind the fields before a possible refusal so even failure destroys
        // actual storage before its original reservation.
        // Tuple fields also drop in order: a refused binding must destroy the
        // actual Vec before its original memory guard, without borrowing an
        // ordinary owner from a budget which has not yet been validated.
        let mut source = (bytes, RefCell::new(memory));
        let memory = source.1.get_mut();
        if !memory.is_from_budget(budget) {
            return Err(BudgetError::InvalidAccountingOperation {
                dimension: BudgetDimension::MemoryBytes,
            });
        }
        let needed = capacity as u64 + OWNER_ESCROW_BYTES as u64;
        if needed > memory.bytes() {
            memory.grow(needed - memory.bytes())?;
        }
        // Excess temporary/old-capacity storage has already been destroyed.
        memory.shrink(needed);
        Ok(Self {
            bytes: Bytes::from_owner(Accounted {
                bytes: source.0,
                memory: source.1,
                _accounting: budget.clone(),
            }),
            capacity,
        })
    }

    /// No payload copy and no reservation release at the RPC ownership handoff.
    #[must_use]
    pub fn into_bytes(self) -> Bytes {
        self.bytes
    }

    /// Sharing also retains the original owner for borrowed status responses.
    #[must_use]
    pub fn shared_bytes(&self) -> Bytes {
        self.bytes.clone()
    }
}
impl From<Vec<u8>> for ResultPayload {
    fn from(bytes: Vec<u8>) -> Self {
        let capacity = bytes.capacity();
        Self {
            bytes: bytes.into(),
            capacity,
        }
    }
}
impl AsRef<[u8]> for ResultPayload {
    fn as_ref(&self) -> &[u8] {
        &self.bytes
    }
}
impl Deref for ResultPayload {
    type Target = [u8];
    fn deref(&self) -> &Self::Target {
        &self.bytes
    }
}
impl<T: AsRef<[u8]> + ?Sized> PartialEq<T> for ResultPayload {
    fn eq(&self, other: &T) -> bool {
        self.as_ref() == other.as_ref()
    }
}
impl Eq for ResultPayload {}
impl fmt::Debug for ResultPayload {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        self.as_ref().fmt(formatter)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::{BudgetProfile, ClockSample, EffectiveActivationBudget, ResourceBudget};
    use std::time::Instant;

    fn budget(memory_bytes: u64) -> crate::ActivationBudget {
        let limits = ResourceBudget {
            cpu_fuel: 100,
            memory_bytes,
            wall_time_limit_millis: Some(1000),
            child_calls: 0,
            outbound_requests: 0,
            state_read_bytes: 0,
            state_write_bytes: 0,
            blob_read_bytes: 0,
            blob_write_bytes: 0,
            log_bytes: 0,
            effect_count: 0,
        };
        let grant = EffectiveActivationBudget::admit_profile_at(
            BudgetProfile::Phase3,
            &limits,
            &limits,
            &limits,
            None,
            ClockSample::new(1000, Instant::now()),
        )
        .unwrap();
        crate::ActivationBudget::with_profile(grant, BudgetProfile::Phase3).unwrap()
    }

    #[test]
    fn accounted_payload_clone_and_transport_hold_the_same_bytes_and_charge() {
        fn send_sync<T: Send + Sync>() {}
        send_sync::<ResultPayload>();
        send_sync::<HostMemoryReservation>();
        let budget = budget(4096);
        let mut bytes = Vec::with_capacity(512);
        bytes.extend_from_slice(b"retained-result");
        let pointer = bytes.as_ptr();
        let original = budget.reserve_host_memory(512).unwrap();
        let result = ResultPayload::from_reserved(bytes, original, &budget).unwrap();
        assert_eq!(result.capacity(), 512);
        assert_eq!(result.as_ptr(), pointer);
        let charged = budget.host_memory_bytes();
        assert!(charged >= 512 + size_of::<Accounted>() as u64);
        let clone = result.clone();
        let transport = result.into_bytes();
        assert_eq!(clone.as_ptr(), pointer);
        assert_eq!(transport.as_ptr(), pointer);
        assert_eq!(budget.host_memory_bytes(), charged);
        assert_eq!(budget.outstanding_reservations(), 1);
        let _ = budget.finalize_at(None, Instant::now());
        drop(clone);
        assert_eq!(budget.host_memory_bytes(), charged);
        drop(transport);
        assert_eq!(budget.host_memory_bytes(), 0);
        assert_eq!(budget.outstanding_reservations(), 0);
    }

    #[test]
    fn owner_allocation_refusal_releases_original_storage_and_charge() {
        let budget = budget(128);
        let mut bytes = Vec::with_capacity(128);
        bytes.push(42);
        let original = budget.reserve_host_memory(128).unwrap();
        assert!(ResultPayload::from_reserved(bytes, original, &budget).is_err());
        assert_eq!(budget.host_memory_bytes(), 0);
        assert_eq!(budget.outstanding_reservations(), 0);
    }

    #[test]
    fn a_foreign_reservation_cannot_certify_the_original_budget() {
        let original_budget = budget(4096);
        let foreign_budget = budget(4096);
        let bytes = vec![42];
        let memory = foreign_budget
            .reserve_host_memory(bytes.capacity() as u64)
            .unwrap();
        assert!(ResultPayload::from_reserved(bytes, memory, &original_budget).is_err());
        assert_eq!(foreign_budget.outstanding_reservations(), 0);
        assert_eq!(original_budget.host_memory_bytes(), 0);
    }

    #[test]
    fn legacy_constructor_preserves_capacity_and_comparison() {
        let mut bytes = Vec::with_capacity(512);
        bytes.extend_from_slice(b"same-value");
        let result: ResultPayload = bytes.into();
        assert_eq!(result, b"same-value");
        assert_eq!(result.capacity(), 512);
        assert_eq!(result.as_slice(), b"same-value");
    }
}

impl From<ResultPayload> for Bytes {
    fn from(payload: ResultPayload) -> Self {
        payload.into_bytes()
    }
}
