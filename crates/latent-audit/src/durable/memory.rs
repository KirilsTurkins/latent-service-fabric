//! Original-ledger custody for audit copies. Capacity is admitted before copy;
//! observations track only allocations which have actually been constructed.
mod heap;
use super::{capacity, Result};
pub(crate) use heap::Heap;
use latent_core::node_metadata::{NodeMetadataOwner, NodeMetadataReservation};
use latent_core::{ActivationBudget, BudgetProfile, HostMemoryReservation};
use std::{
    alloc::Layout,
    marker::PhantomData,
    ops::Deref,
    sync::{atomic::AtomicUsize, Arc, Mutex},
};

const BOOKKEEPING: usize = 64;
const MAXIMUM_RECORD_BYTES: usize = 16384;
const MAXIMUM_JSON_NODES: usize = 256;
const OWNED_NODE_BYTES: usize = 128;
const SIMULTANEOUS_RECORD_COPIES: usize = 8;

fn arc_bytes<T>() -> Result<usize> {
    Layout::new::<[AtomicUsize; 2]>()
        .extend(Layout::new::<T>())
        .map_err(|_| capacity())?
        .0
        .pad_to_align()
        .size()
        .checked_add(BOOKKEEPING)
        .ok_or_else(capacity)
}

enum Original {
    Activation(HostMemoryReservation),
    Node(NodeMetadataReservation),
}
struct State {
    original: Original,
    capacity: usize,
    occupied: usize,
    confirmed: usize,
}
struct Account {
    state: Mutex<State>,
}

/// Cloneable custody of one pre-admitted original memory envelope. This is not
/// an execution owner; it cannot finalize, delegate or consume any other budget
/// dimension. No Weak or raw billing Arc can escape.
#[derive(Default)]
#[must_use = "retain original capacity with actual audit owners"]
pub struct AuditCallMemory(Option<Arc<Account>>);
impl Clone for AuditCallMemory {
    fn clone(&self) -> Self {
        Self(self.0.as_ref().map(Arc::clone))
    }
}
impl Drop for AuditCallMemory {
    fn drop(&mut self) {
        if let Some(account) = self.0.take() {
            // Free this real accounting header before the reservation refunds.
            drop(Arc::into_inner(account));
        }
    }
}
impl AuditCallMemory {
    /// Finite simultaneous-copy capacity, not a claim that future copies exist.
    /// The closed codec admits at most256 nodes and two bounded revision lists;
    /// each owned node needs at most64 inline-vector bytes plus64 bookkeeping.
    pub fn owned_heap_bound(record_bytes: usize) -> Result<usize> {
        if !(4096..=MAXIMUM_RECORD_BYTES).contains(&record_bytes) {
            return Err(capacity());
        }
        record_bytes
            .checked_add(MAXIMUM_JSON_NODES * OWNED_NODE_BYTES)
            .ok_or_else(capacity)
    }
    pub(crate) fn envelope_bytes(record_bytes: usize) -> Result<usize> {
        if !(4096..=MAXIMUM_RECORD_BYTES).contains(&record_bytes) {
            return Err(capacity());
        }
        record_bytes
            .checked_add(MAXIMUM_JSON_NODES * OWNED_NODE_BYTES)
            .and_then(|bytes| bytes.checked_add(std::mem::size_of::<super::AuditStoredRecord>()))
            .and_then(|bytes| bytes.checked_mul(SIMULTANEOUS_RECORD_COPIES))
            .and_then(|bytes| bytes.checked_add(16384))
            .ok_or_else(capacity)
    }
    /// Prepare before incarnation, digest allocation or the first captured copy.
    /// Earlier profiles retain their explicit unqualified compatibility path.
    pub(crate) fn activation(budget: &ActivationBudget, bytes: usize) -> Result<Self> {
        if !matches!(
            budget.profile(),
            BudgetProfile::Phase3 | BudgetProfile::Phase4
        ) {
            return Ok(Self::default());
        }
        let total = bytes
            .checked_add(arc_bytes::<Account>()?)
            .ok_or_else(capacity)?;
        let original = budget
            .reserve_host_memory(u64::try_from(total).map_err(|_| capacity())?)
            .map_err(|_| capacity())?;
        Ok(Self::construct(Original::Activation(original), total))
    }
    pub(crate) fn node(owner: &NodeMetadataOwner, bytes: usize) -> Result<Self> {
        let total = bytes
            .checked_add(arc_bytes::<Account>()?)
            .ok_or_else(capacity)?;
        let original = owner.reserve(total).map_err(|_| capacity())?;
        Ok(Self::construct(Original::Node(original), total))
    }
    fn construct(original: Original, capacity: usize) -> Self {
        let fixed = arc_bytes::<Account>().expect("fixed accounting layout");
        if let Original::Node(original) = &original {
            debug_assert_eq!(original.bytes(), capacity);
        }
        let memory = Self(Some(Arc::new(Account {
            state: Mutex::new(State {
                original,
                capacity,
                occupied: fixed,
                confirmed: 0,
            }),
        })));
        {
            let mut state = memory
                .0
                .as_ref()
                .expect("new account")
                .state
                .lock()
                .unwrap_or_else(std::sync::PoisonError::into_inner);
            state.confirmed = fixed;
            if let Original::Activation(original) = &mut state.original {
                original.confirm_bytes(fixed as u64);
            }
        }
        memory
    }
    pub(crate) fn part(&self, bytes: usize) -> Result<Part> {
        if let Some(account) = &self.0 {
            let mut state = account.state.lock().map_err(|_| capacity())?;
            let occupied = state.occupied.checked_add(bytes).ok_or_else(capacity)?;
            if occupied > state.capacity {
                return Err(capacity());
            }
            state.occupied = occupied;
        }
        Ok(Part {
            memory: self.clone(),
            bytes,
            confirmed: 0,
        })
    }
    /// Admit an actual owned Box and its complete separately measured graph
    /// before either the object or its first copied field is allocated.
    pub fn prepare_box<T>(&self, heap_bound: usize) -> Result<AuditBoxPreparation<T>> {
        let bytes = std::mem::size_of::<T>()
            .checked_add(BOOKKEEPING)
            .and_then(|bytes| bytes.checked_add(heap_bound))
            .ok_or_else(capacity)?;
        Ok(AuditBoxPreparation {
            part: self.part(bytes)?,
            marker: PhantomData,
        })
    }
    /// Admit a heap graph retained by an inline affine owner before copying.
    pub fn prepare_value<T>(&self, heap_bound: usize) -> Result<AuditValuePreparation<T>> {
        Ok(AuditValuePreparation {
            part: self.part(heap_bound)?,
            marker: PhantomData,
        })
    }
    pub(crate) fn prepare_arc<T>(&self, heap_bound: usize) -> Result<Preparation<T>> {
        let bytes = arc_bytes::<T>()?
            .checked_add(arc_bytes::<Part>()?)
            .and_then(|bytes| bytes.checked_add(heap_bound))
            .ok_or_else(capacity)?;
        Ok(Preparation {
            part: self.part(bytes)?,
            marker: PhantomData,
        })
    }
    /// Partition simultaneous temporary codec capacity before validation,
    /// normalization and envelope cloning. This remains unconfirmed capacity;
    /// it never invents a future allocation/peak. Concurrent operations sharing
    /// this memory must each admit their own scratch, under the same envelope.
    pub(crate) fn codec_scratch(&self, record_bytes: usize) -> Result<Part> {
        let bytes = Self::owned_heap_bound(record_bytes)?
            .checked_mul(2)
            .and_then(|bytes| bytes.checked_add(2 * record_bytes))
            .and_then(|bytes| bytes.checked_add(4096))
            .ok_or_else(capacity)?;
        self.part(bytes)
    }
    pub(crate) fn prepare_owned(&self, heap_bound: usize) -> Result<Part> {
        self.part(heap_bound)
    }
}

/// One affine physical subview inside the original reserved envelope. It never
/// changes the capacity grant; it only reports actual birth/retirement.
pub(crate) struct Part {
    memory: AuditCallMemory,
    bytes: usize,
    confirmed: usize,
}
impl Part {
    pub(crate) fn confirm(&mut self, bytes: usize) {
        assert!(
            bytes <= self.bytes && self.confirmed == 0,
            "audit physical allocation exceeded pre-admission"
        );
        if let Some(account) = &self.memory.0 {
            let mut state = account
                .state
                .lock()
                .unwrap_or_else(std::sync::PoisonError::into_inner);
            state.confirmed = state
                .confirmed
                .checked_add(bytes)
                .expect("bounded audit allocation sum");
            let actual = state.confirmed;
            if let Original::Activation(original) = &mut state.original {
                original.confirm_bytes(actual as u64);
            }
        }
        self.confirmed = bytes;
    }
}
impl Part {
    fn retire_observed(&mut self, bytes: usize) {
        assert!(
            bytes <= self.confirmed,
            "audit retirement exceeds actual storage"
        );
        if let Some(account) = &self.memory.0 {
            let mut state = account
                .state
                .lock()
                .unwrap_or_else(std::sync::PoisonError::into_inner);
            state.confirmed -= bytes;
            if let Original::Activation(original) = &mut state.original {
                original.retire_confirmed_bytes(bytes as u64);
            }
        }
        self.confirmed -= bytes;
    }
}
impl Drop for Part {
    fn drop(&mut self) {
        if let Some(account) = &self.memory.0 {
            let mut state = account
                .state
                .lock()
                .unwrap_or_else(std::sync::PoisonError::into_inner);
            state.occupied -= self.bytes;
            state.confirmed -= self.confirmed;
            if let Original::Activation(original) = &mut state.original {
                original.retire_confirmed_bytes(self.confirmed as u64);
            }
        }
    }
}
struct Billing(Option<Arc<Part>>);
impl Clone for Billing {
    fn clone(&self) -> Self {
        Self(self.0.as_ref().map(Arc::clone))
    }
}
impl Drop for Billing {
    fn drop(&mut self) {
        if let Some(part) = self.0.take() {
            drop(Arc::into_inner(part));
        }
    }
}
// Physical original payload Arc first, billing Arc second, then its affine
// Part retires/refunds. Every clone follows this same order, including unwind.
pub(crate) struct AuditArc<T> {
    inner: Arc<T>,
    billing: Billing,
}
pub(crate) struct Preparation<T> {
    part: Part,
    marker: PhantomData<T>,
}
impl<T> Preparation<T> {
    pub(crate) fn allocate(self, value: T, heap_bytes: usize) -> AuditArc<T> {
        if self.part.memory.0.is_none() {
            return AuditArc {
                inner: Arc::new(value),
                billing: Billing(None),
            };
        }
        let actual = arc_bytes::<T>()
            .expect("prechecked payload layout")
            .checked_add(arc_bytes::<Part>().expect("prechecked billing layout"))
            .and_then(|bytes| bytes.checked_add(heap_bytes))
            .expect("prechecked audit allocation envelope");
        let billing = Billing(Some(Arc::new(self.part)));
        let inner = Arc::new(value);
        let mut owned = AuditArc { inner, billing };
        Arc::get_mut(owned.billing.0.as_mut().expect("unpublished billing"))
            .expect("unpublished billing")
            .confirm(actual);
        owned
    }
}
impl<T> Clone for AuditArc<T> {
    fn clone(&self) -> Self {
        Self {
            inner: Arc::clone(&self.inner),
            billing: self.billing.clone(),
        }
    }
}
impl<T> Deref for AuditArc<T> {
    type Target = T;
    fn deref(&self) -> &T {
        &self.inner
    }
}
impl<T> AuditArc<T> {
    pub(crate) fn ptr_eq(left: &Self, right: &Self) -> bool {
        Arc::ptr_eq(&left.inner, &right.inner)
    }
}

// The owned value retires before its affine physical observation on all paths.
#[must_use = "retain with the actual owned audit graph"]
pub struct AuditOwned<T> {
    value: T,
    _part: Part,
}
impl<T> AuditOwned<T> {
    pub(crate) fn new(value: T, part: Part, heap_bytes: usize) -> Self {
        let mut owned = Self { value, _part: part };
        owned._part.confirm(heap_bytes);
        owned
    }
}
impl<T> AuditOwned<T> {
    pub(crate) fn with_value<R>(self, use_value: impl FnOnce(T) -> R) -> R {
        let Self { value, _part } = self;
        let result = use_value(value);
        drop(_part);
        result
    }
}

impl<T> Deref for AuditOwned<T> {
    type Target = T;
    fn deref(&self) -> &T {
        &self.value
    }
}

/// Actual Box before its original physical-memory observation/capacity owner.
#[must_use = "retain with the actual audit Box"]
pub struct AuditBox<T> {
    value: Box<T>,
    _part: Part,
}
pub struct AuditBoxPreparation<T> {
    part: Part,
    marker: PhantomData<T>,
}
impl<T> AuditBoxPreparation<T> {
    pub fn allocate(self, value: T, heap_bytes: usize) -> AuditBox<T> {
        let bytes = std::mem::size_of::<T>()
            .checked_add(BOOKKEEPING)
            .and_then(|bytes| bytes.checked_add(heap_bytes))
            .expect("pre-admitted audit Box");
        let mut owned = AuditBox {
            value: Box::new(value),
            _part: self.part,
        };
        owned._part.confirm(bytes);
        owned
    }
}
impl<T> Deref for AuditBox<T> {
    type Target = T;
    fn deref(&self) -> &T {
        &self.value
    }
}
impl<T> std::ops::DerefMut for AuditBox<T> {
    fn deref_mut(&mut self) -> &mut T {
        &mut self.value
    }
}
pub struct AuditValuePreparation<T> {
    part: Part,
    marker: PhantomData<T>,
}
impl<T> AuditValuePreparation<T> {
    pub fn allocate(self, value: T, heap_bytes: usize) -> AuditOwned<T> {
        AuditOwned::new(value, self.part, heap_bytes)
    }
}

impl AuditOwned<super::AuditOperationAttempt> {
    /// Move the captured owned graph into its observation without exporting any
    /// raw payload or cloning under the existing physical capacity claim.
    pub fn into_observation(
        self,
        kind: crate::Phase2AuditEventKind,
        outcome: crate::AuditOutcome,
        reason: super::AuditReason,
        occurred_at_unix_millis: u64,
    ) -> Result<AuditOwned<super::AuditObservation>> {
        let AuditOwned { value, mut _part } = self;
        let super::AuditOperationAttempt {
            scope,
            actor,
            identities,
            operation_id,
            request_digest,
            preview_receipt_digest,
            ..
        } = value;
        let event = super::AuditObservation {
            scope,
            actor,
            identities,
            kind,
            outcome,
            reason,
            cache_kind: None,
            occurred_at_unix_millis,
        };
        // These are the only owned fields omitted from the moved observation.
        drop((operation_id, request_digest, preview_receipt_digest));
        let heap = event.heap_bytes()?;
        let retired = _part
            .confirmed
            .checked_sub(heap)
            .expect("observation only removes fields");
        _part.retire_observed(retired);
        Ok(AuditOwned {
            value: event,
            _part,
        })
    }
}

#[cfg(test)]
mod tests;
