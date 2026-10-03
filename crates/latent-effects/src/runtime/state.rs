use std::collections::{BTreeMap, BTreeSet};
use std::sync::{Arc, Mutex};

use crate::authority::DispatchOwners;
use crate::dispatch_store::DispatchCounts;
use latent_state::store_io::StoreIoSnapshot;
use serde::Serialize;
use tokio::sync::Notify;

use super::{DispatcherConfig, DispatcherError};

#[derive(Debug, Clone, Copy, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct DispatcherSnapshot {
    pub durable: DispatchCounts,
    pub counts_observed_at_millis: u64,
    pub queued: usize,
    pub active_jobs: usize,
    pub retained_attempt_bytes: u64,
    pub live_workers: usize,
    pub accepted_effects: usize,
    pub live_tenants: usize,
    pub claims: u64,
    pub physical_owners: usize,
    pub quarantined_physical_owners: usize,
    pub paused: bool,
    pub admission_closed: bool,
    pub quarantined: bool,
    pub failure: Option<&'static str>,
}

#[derive(Debug, Clone, Copy, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct DispatcherShutdown {
    pub clean: bool,
    pub physically_retired: bool,
    pub scheduling_owner_retired: bool,
    pub worker_threads_joined: usize,
    pub worker_threads_remaining: usize,
    pub snapshot: DispatcherSnapshot,
}

#[derive(Default)]
pub(super) struct State {
    pub closed: bool,
    pub paused: bool,
    pub failure: Option<DispatcherError>,
    effects: BTreeSet<String>,
    tenants: BTreeMap<String, usize>,
    pub claims: u64,
    pub counts: DispatchCounts,
    pub counts_time: u64,
    pub scheduling_retired: bool,
}

pub(super) struct Shared {
    pub state: Mutex<State>,
    pub notify: Notify,
}

impl State {
    pub fn effects_empty(&self) -> bool {
        self.effects.is_empty()
    }
}

impl Shared {
    pub fn new(paused: bool) -> Self {
        Self {
            state: Mutex::new(State {
                paused,
                ..State::default()
            }),
            notify: Notify::new(),
        }
    }

    pub fn available(&self) -> bool {
        self.state
            .lock()
            .is_ok_and(|state| !state.closed && !state.paused && state.failure.is_none())
    }

    pub fn fail(&self, error: DispatcherError) {
        let mut state = self
            .state
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        state.failure.get_or_insert(error);
        state.paused = true;
        drop(state);
        self.notify.notify_one();
    }

    pub fn admit(
        self: &Arc<Self>,
        tenant: &str,
        effect: &str,
        config: &DispatcherConfig,
    ) -> Option<ActiveGuard> {
        let mut state = self.state.lock().ok()?;
        if state.closed
            || state.paused
            || state.failure.is_some()
            || state.effects.len() >= config.accepted_jobs
            || state.effects.contains(effect)
            || state.tenants.get(tenant).copied().unwrap_or(0) >= config.per_tenant_jobs
        {
            return None;
        }
        state.effects.insert(effect.to_owned());
        *state.tenants.entry(tenant.to_owned()).or_default() += 1;
        Some(ActiveGuard {
            shared: Arc::clone(self),
            tenant: tenant.to_owned(),
            effect: effect.to_owned(),
            retired: false,
            started: false,
        })
    }

    pub fn snapshot(&self, jobs: StoreIoSnapshot, owners: DispatchOwners) -> DispatcherSnapshot {
        let state = self
            .state
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        DispatcherSnapshot {
            durable: state.counts,
            counts_observed_at_millis: state.counts_time,
            queued: jobs.queued,
            active_jobs: jobs.active_reads + jobs.active_writes,
            retained_attempt_bytes: jobs.retained_bytes,
            live_workers: jobs.live_workers,
            accepted_effects: state.effects.len(),
            live_tenants: state.tenants.len(),
            claims: state.claims,
            physical_owners: owners.physical,
            quarantined_physical_owners: owners.quarantined,
            paused: state.paused,
            admission_closed: state.closed || jobs.admission_closed,
            quarantined: jobs.quarantined || owners.quarantined != 0 || state.failure.is_some(),
            failure: state.failure.map(failure_name),
        }
    }
}

fn failure_name(error: DispatcherError) -> &'static str {
    match error {
        DispatcherError::Authority(_) => "effect-authority",
        DispatcherError::Store(_) | DispatcherError::ProtectedStore(_) => "shared-store",
        DispatcherError::Worker(_) => "physical-worker",
        DispatcherError::CheckpointRequired => "restore-checkpoint-required",
        DispatcherError::AdmissionClosed => "admission-closed",
        DispatcherError::InvalidConfiguration
        | DispatcherError::UnsupportedOrdering
        | DispatcherError::InvalidAdapter => "configuration",
    }
}

pub(super) struct ActiveGuard {
    shared: Arc<Shared>,
    tenant: String,
    effect: String,
    retired: bool,
    started: bool,
}

impl ActiveGuard {
    pub fn start(&mut self) {
        self.started = true;
    }
    pub fn retire(mut self) {
        self.retired = true;
    }
}

impl Drop for ActiveGuard {
    fn drop(&mut self) {
        let mut state = self
            .shared
            .state
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        if self.retired || !self.started {
            state.effects.remove(&self.effect);
            if let Some(count) = state.tenants.get_mut(&self.tenant) {
                *count -= 1;
                if *count == 0 {
                    state.tenants.remove(&self.tenant);
                }
            }
        } else {
            state.failure.get_or_insert(DispatcherError::Worker(
                latent_state::store_io::StoreIoError::RecoveryRequired,
            ));
            state.paused = true;
        }
        drop(state);
        self.shared.notify.notify_one();
    }
}
