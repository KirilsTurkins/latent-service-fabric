use super::{CapabilitySession, MetricActivationLimits, MetricError};
use crate::broker::session::SessionCore;
use std::sync::Arc;

#[derive(Clone, Copy, Default)]
struct SeriesUse {
    key: [u8; 32],
    pending: usize,
    accepted: bool,
}
#[derive(Default)]
pub(in crate::broker) struct SessionUsage {
    observations: usize,
    bytes: usize,
    series: [SeriesUse; 32],
}
pub(super) struct Reservation {
    core: Arc<SessionCore>,
    slot: usize,
    bytes: usize,
    committed: bool,
}
impl Reservation {
    pub(super) fn new(
        session: &CapabilitySession,
        key: [u8; 32],
        bytes: usize,
        limits: MetricActivationLimits,
    ) -> Result<Self, MetricError> {
        session.core.check()?;
        let mut usage = session
            .core
            .metrics
            .try_lock()
            .map_err(|_| MetricError::BudgetExhausted)?;
        if usage.observations >= limits.maximum_observations
            || bytes > limits.maximum_record_bytes.saturating_sub(usage.bytes)
        {
            return Err(MetricError::BudgetExhausted);
        }
        let used = |slot: &SeriesUse| slot.accepted || slot.pending > 0;
        let slot = match usage.series.iter().position(|s| used(s) && s.key == key) {
            Some(slot) => slot,
            None => {
                if usage.series.iter().filter(|s| used(s)).count() >= limits.maximum_series {
                    return Err(MetricError::BudgetExhausted);
                }
                let slot = usage
                    .series
                    .iter()
                    .position(|s| !used(s))
                    .ok_or(MetricError::BudgetExhausted)?;
                usage.series[slot] = SeriesUse {
                    key,
                    pending: 0,
                    accepted: false,
                };
                slot
            }
        };
        usage.series[slot].pending += 1;
        usage.observations += 1;
        usage.bytes += bytes;
        Ok(Self {
            core: session.core.clone(),
            slot,
            bytes,
            committed: false,
        })
    }
    pub(super) fn commit(&mut self) {
        let mut usage = self
            .core
            .metrics
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        usage.series[self.slot].pending -= 1;
        usage.series[self.slot].accepted = true;
        self.committed = true;
    }
}
impl Drop for Reservation {
    fn drop(&mut self) {
        if !self.committed {
            let mut usage = self
                .core
                .metrics
                .lock()
                .unwrap_or_else(std::sync::PoisonError::into_inner);
            usage.series[self.slot].pending -= 1;
            usage.observations -= 1;
            usage.bytes -= self.bytes;
        }
    }
}
