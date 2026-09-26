use super::{E, RECORD_BYTES};
use crate::custom::CustomMetricLimits;
use std::sync::{
    atomic::{AtomicUsize, Ordering},
    Arc,
};

#[derive(Default)]
pub(super) struct QueueCounters {
    pub node: AtomicUsize,
    pub tenants: [AtomicUsize; 8],
}
pub(crate) struct QueueCharge {
    counters: Arc<QueueCounters>,
    tenant: usize,
}
fn reserve(counter: &AtomicUsize, limit: usize) -> Result<(), E> {
    counter
        .fetch_update(Ordering::AcqRel, Ordering::Acquire, |old| {
            old.checked_add(RECORD_BYTES).filter(|next| *next <= limit)
        })
        .map(|_| ())
        .map_err(|_| E::BudgetExhausted)
}
impl QueueCounters {
    pub(super) fn reserve(
        self: &Arc<Self>,
        tenant: usize,
        limits: CustomMetricLimits,
    ) -> Result<QueueCharge, E> {
        reserve(&self.node, limits.maximum_queued_bytes)?;
        if let Err(error) = reserve(
            &self.tenants[tenant],
            limits.maximum_queued_bytes_per_tenant,
        ) {
            self.node.fetch_sub(RECORD_BYTES, Ordering::AcqRel);
            return Err(error);
        }
        Ok(QueueCharge {
            counters: self.clone(),
            tenant,
        })
    }
}
impl Drop for QueueCharge {
    fn drop(&mut self) {
        self.counters.tenants[self.tenant].fetch_sub(RECORD_BYTES, Ordering::AcqRel);
        self.counters.node.fetch_sub(RECORD_BYTES, Ordering::AcqRel);
    }
}
