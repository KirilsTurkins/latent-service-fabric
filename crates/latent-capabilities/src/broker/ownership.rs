use super::{busy, capacity, CapabilityBrokerLimits, CapabilityBrokerSnapshot, PlatformError};
use std::sync::{
    atomic::{AtomicUsize, Ordering},
    Arc,
};

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
pub(super) struct Counters {
    counts: [AtomicUsize; 8],
    maxima: [usize; 8],
}
impl Counters {
    pub(super) fn new(l: CapabilityBrokerLimits) -> Self {
        Self {
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
    pub(super) fn acquire(
        self: &Arc<Self>,
        kind: Kind,
        amount: usize,
    ) -> Result<Charge, PlatformError> {
        let i = kind as usize;
        let mut current = self.counts[i].load(Ordering::Acquire);
        // Finite contention work. No spin waiting for a control writer.
        for _ in 0..16 {
            let next = current
                .checked_add(amount)
                .filter(|n| *n <= self.maxima[i])
                .ok_or_else(capacity)?;
            match self.counts[i].compare_exchange_weak(
                current,
                next,
                Ordering::AcqRel,
                Ordering::Acquire,
            ) {
                Ok(_) => {
                    return Ok(Charge {
                        owner: Arc::clone(self),
                        kind,
                        amount,
                    })
                }
                Err(actual) => current = actual,
            }
        }
        Err(busy())
    }
    pub(super) fn snapshot(&self) -> CapabilityBrokerSnapshot {
        let c = self.counts.each_ref().map(|v| v.load(Ordering::Acquire));
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
    owner: Arc<Counters>,
    kind: Kind,
    amount: usize,
}
impl Drop for Charge {
    fn drop(&mut self) {
        self.owner.counts[self.kind as usize].fetch_sub(self.amount, Ordering::AcqRel);
    }
}
