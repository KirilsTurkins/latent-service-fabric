use super::{
    busy, capacity, denied, CapabilityBrokerLimits, CapabilityBrokerSnapshot, PlatformError,
};
use latent_core::node_metadata::{
    NodeMetadataArc, NodeMetadataError, NodeMetadataOwner, NodeMetadataReservation,
};
use std::sync::atomic::{AtomicBool, AtomicUsize, Ordering};

#[derive(Clone, Copy)]
pub(super) enum Kind {
    Provider,
    Plan,
    Session,
    Handle,
    Call,
    Result,
    Metadata,
    Buffer,
}
struct CounterState {
    acquired: AtomicBool,
    counts: [AtomicUsize; 8],
    maxima: [usize; 8],
    native: Option<NodeMetadataOwner>,
}

#[derive(Clone)]
pub(super) struct Counters(NodeMetadataArc<CounterState>);
impl Counters {
    pub(super) fn new(l: CapabilityBrokerLimits) -> Self {
        Self(NodeMetadataArc::unaccounted(Self::state(l, None)))
    }
    fn state(l: CapabilityBrokerLimits, native: Option<NodeMetadataOwner>) -> CounterState {
        CounterState {
            acquired: AtomicBool::new(false),
            native,
            counts: std::array::from_fn(|_| AtomicUsize::new(0)),
            maxima: [
                l.maximum_providers,
                l.maximum_plans,
                l.maximum_sessions,
                l.maximum_handles,
                l.maximum_calls,
                l.maximum_results,
                l.maximum_metadata_bytes,
                l.maximum_buffer_bytes,
            ],
        }
    }
    // Reuse the exact journal/bootstrap node allowance. This is installed only
    // before any broker metadata owner exists; equal names/limits do not mint it.
    pub(super) fn with_native(
        l: CapabilityBrokerLimits,
        native: NodeMetadataOwner,
    ) -> Result<Self, PlatformError> {
        if native.maximum_bytes() != l.maximum_metadata_bytes {
            return Err(denied());
        }
        let prepared = NodeMetadataArc::prepare_fixed(&native, 0).map_err(native_failure)?;
        Ok(Self(prepared.allocate(Self::state(l, Some(native)))))
    }
    pub(super) fn acquire(&self, kind: Kind, amount: usize) -> Result<Charge, PlatformError> {
        let i = kind as usize;
        let native = if matches!(kind, Kind::Metadata) {
            self.0
                .native
                .as_ref()
                .map(|owner| owner.reserve(amount).map_err(native_failure))
                .transpose()?
        } else {
            None
        };
        let mut current = self.0.counts[i].load(Ordering::Acquire);
        // Finite contention work. No spin waiting for a control writer.
        for _ in 0..16 {
            let next = current
                .checked_add(amount)
                .filter(|n| *n <= self.0.maxima[i])
                .ok_or_else(capacity)?;
            match self.0.counts[i].compare_exchange_weak(
                current,
                next,
                Ordering::AcqRel,
                Ordering::Acquire,
            ) {
                Ok(_) => {
                    self.0.acquired.store(true, Ordering::Release);
                    return Ok(Charge {
                        owner: self.clone(),
                        _native: native,
                        kind,
                        amount,
                    });
                }
                Err(actual) => current = actual,
            }
        }
        Err(busy())
    }
    pub(super) fn is_pristine(&self) -> bool {
        self.0.native.is_none()
            && !self.0.acquired.load(Ordering::Acquire)
            && self.0.is_unique()
            && self
                .0
                .counts
                .iter()
                .all(|value| value.load(Ordering::Acquire) == 0)
    }
    pub(super) fn snapshot(&self) -> CapabilityBrokerSnapshot {
        let c = self.0.counts.each_ref().map(|v| v.load(Ordering::Acquire));
        CapabilityBrokerSnapshot {
            providers: c[0],
            plans: c[1],
            sessions: c[2],
            handles: c[3],
            calls: c[4],
            results: c[5],
            metadata_bytes: c[6],
            buffer_bytes: c[7],
        }
    }
}
/// Affine reservation. Actual data/work fields must be destroyed before this.
pub(super) struct Charge {
    owner: Counters,
    kind: Kind,
    amount: usize,
    _native: Option<NodeMetadataReservation>,
}
impl Drop for Charge {
    fn drop(&mut self) {
        self.owner.0.counts[self.kind as usize].fetch_sub(self.amount, Ordering::AcqRel);
    }
}

fn native_failure(failure: NodeMetadataError) -> PlatformError {
    if failure == NodeMetadataError::Busy {
        busy()
    } else {
        capacity()
    }
}

#[cfg(test)]
mod node_metadata_tests {
    use super::*;
    #[test]
    fn original_node_bank_and_logical_broker_metadata_are_distinct_conserved_observations() {
        let limits = CapabilityBrokerLimits::default();
        let owner = NodeMetadataOwner::new(limits.maximum_metadata_bytes).unwrap();
        let base = owner.occupied_bytes();
        let counters = Counters::with_native(limits, owner.clone()).unwrap();
        let fixed = owner.snapshot().fixed_reserved_bytes;
        assert!(fixed > base);
        assert_eq!(counters.snapshot().metadata_bytes, 0);
        let metadata = counters.acquire(Kind::Metadata, 512).unwrap();
        assert_eq!(counters.snapshot().metadata_bytes, 512);
        assert_eq!(owner.snapshot().fixed_reserved_bytes, fixed);
        assert_eq!(owner.snapshot().transient_reserved_bytes, 512);
        drop(metadata);
        assert_eq!(counters.snapshot().metadata_bytes, 0);
        assert_eq!(owner.snapshot().reserved_bytes, fixed);
        let full = owner
            .reserve(limits.maximum_metadata_bytes - fixed)
            .unwrap();
        assert!(counters.acquire(Kind::Metadata, 1).is_err());
        assert_eq!(counters.snapshot().metadata_bytes, 0);
        assert_eq!(owner.occupied_bytes(), limits.maximum_metadata_bytes);
        drop(full);
        drop(counters);
        assert_eq!(owner.snapshot().reserved_bytes, base);
    }
    #[test]
    fn original_metadata_swap_refuses_mismatched_ceiling_and_prior_or_retained_zero_charge() {
        let limits = CapabilityBrokerLimits::default();
        let foreign = NodeMetadataOwner::new(limits.maximum_metadata_bytes - 1).unwrap();
        let before = foreign.occupied_bytes();
        assert!(Counters::with_native(limits, foreign.clone()).is_err());
        assert_eq!(foreign.occupied_bytes(), before);
        let counters = Counters::new(limits);
        assert!(counters.is_pristine());
        let retained = counters.acquire(Kind::Metadata, 0).unwrap();
        assert_eq!(counters.snapshot().metadata_bytes, 0);
        assert!(!counters.is_pristine());
        drop(retained);
        assert_eq!(counters.snapshot().metadata_bytes, 0);
        assert!(!counters.is_pristine());
        // Historical admission remains fenced even after all original owners
        // physically retire; swapping is a bootstrap-only transition.
        let fresh = Counters::new(limits);
        let provider = fresh.acquire(Kind::Provider, 1).unwrap();
        drop(provider);
        assert_eq!(fresh.snapshot().providers, 0);
        assert!(!fresh.is_pristine());
    }
}
