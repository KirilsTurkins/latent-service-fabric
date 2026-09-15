use crate::EventError;
use latent_capabilities::broker::pools::ProviderMetadata;
use std::sync::{
    atomic::{AtomicU64, Ordering},
    Arc, Mutex,
};

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum TriggerTerminal {
    Succeeded,
    DeclaredFailure,
    Rejected,
    TimedOut,
    Cancelled,
    Failed,
    Exhausted,
}
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Acknowledgement {
    Accepted,
    RetryScheduled,
    Terminated,
    NotSent,
    Uncertain,
}
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct TriggerStep {
    pub configuration_epoch: u64,
    pub trigger_index: usize,
    pub stream_sequence: u64,
    pub delivery_count: u32,
    pub route_generation: u64,
    pub terminal: TriggerTerminal,
    pub acknowledgement: Acknowledgement,
    /// Closed error category; never contains broker text, credentials or payload.
    pub error: Option<EventError>,
}
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub struct TriggerSnapshot {
    pub configuration_epoch: u64,
    pub triggers: usize,
    pub active_deliveries: u64,
    pub pulls: u64,
    pub executions: u64,
    pub acknowledged: u64,
    pub retries: u64,
    pub terminated: u64,
    pub exhausted: u64,
    pub uncertain_acknowledgements: u64,
    pub delivery_errors: u64,
    pub connection_attempts: u64,
    pub connection_reuses: u64,
}
#[derive(Clone)]
pub struct TriggerMonitor(pub(super) Arc<Counters>);
pub(super) struct Counters {
    pub epoch: u64,
    pub triggers: usize,
    pub active: AtomicU64,
    pub pulls: AtomicU64,
    pub executions: AtomicU64,
    pub acknowledged: AtomicU64,
    pub retries: AtomicU64,
    pub terminated: AtomicU64,
    pub exhausted: AtomicU64,
    pub uncertain: AtomicU64,
    pub rejected: AtomicU64,
    pub attempts: AtomicU64,
    pub reuses: AtomicU64,
    pub last: Mutex<Option<TriggerStep>>,
    pub _metadata: ProviderMetadata,
}
impl TriggerMonitor {
    /// Most recent terminal delivery or rejected poll. Idle polls do not erase it.
    pub fn last_step(&self) -> Option<TriggerStep> {
        *self
            .0
            .last
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
    }
    pub(super) fn record(&self, step: TriggerStep) {
        *self
            .0
            .last
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner) = Some(step);
    }
    #[must_use]
    pub fn snapshot(&self) -> TriggerSnapshot {
        let c = &self.0;
        let n = |v: &AtomicU64| v.load(Ordering::Acquire);
        TriggerSnapshot {
            configuration_epoch: c.epoch,
            triggers: c.triggers,
            active_deliveries: n(&c.active),
            pulls: n(&c.pulls),
            executions: n(&c.executions),
            acknowledged: n(&c.acknowledged),
            retries: n(&c.retries),
            terminated: n(&c.terminated),
            exhausted: n(&c.exhausted),
            uncertain_acknowledgements: n(&c.uncertain),
            delivery_errors: n(&c.rejected),
            connection_attempts: n(&c.attempts),
            connection_reuses: n(&c.reuses),
        }
    }
}
