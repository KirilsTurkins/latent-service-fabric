//! Actual empty-target bootstrap never falls back to a stateless readiness path.
use std::{sync::Arc, time::Instant};

use latent_core::PlatformError;
use latent_node::transaction_runtime::TransactionAdmissionOwners;
use latent_policy::{capability::PolicyStore, supply_chain::SupplyChainAuthority};
use serde::Serialize;

use super::{AdapterClock, StateBootstrap, StateKernel, StateShutdownReport};
use crate::config::state::StateSettings;
use crate::standalone::effects::EffectRuntime;

pub(in crate::standalone) struct StandaloneStateRuntime {
    kernel: StateKernel,
    admission: Option<Arc<TransactionAdmissionOwners>>,
    original_deadline: Instant,
    ready: bool,
}

#[cfg(all(test, target_os = "linux", target_arch = "x86_64"))]
mod tests;

/// Bounded physical facts, without paths, file handles, payloads or authority.
#[derive(Clone, Copy, Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct StateRetirementReport {
    pub clean: bool,
    pub quarantined: bool,
    #[serde(flatten)]
    pub physical: StatePhysicalRetirement,
    pub live_storage_workers: usize,
    pub live_storage_owners: usize,
    pub queued_storage_retirements: usize,
    pub accepted_storage_jobs: usize,
    pub storage_retained_bytes: u64,
    pub ordinary_native_reservations: usize,
    pub recovery_native_reservations: usize,
    pub ordinary_native_bytes: u64,
    pub recovery_native_bytes: u64,
    pub namespace_owners: usize,
}

/// Independent retirement witnesses from the original storage and native owners.
#[derive(Clone, Copy, Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct StatePhysicalRetirement {
    pub store_physically_retired: bool,
    pub native_physically_retired: bool,
}

impl std::ops::Deref for StateRetirementReport {
    type Target = StatePhysicalRetirement;

    fn deref(&self) -> &Self::Target {
        &self.physical
    }
}

impl From<StateShutdownReport> for StateRetirementReport {
    fn from(report: StateShutdownReport) -> Self {
        let store = report.store.snapshot;
        let native = report.native.snapshot;
        Self {
            clean: report.clean,
            physical: StatePhysicalRetirement {
                store_physically_retired: store.physically_retired(),
                native_physically_retired: native.physically_retired(),
            },
            quarantined: store.quarantined || native.quarantined,
            live_storage_workers: store.live_workers,
            live_storage_owners: store.physical_owners,
            queued_storage_retirements: store.queued_retirements,
            accepted_storage_jobs: store.accepted,
            storage_retained_bytes: store.retained_bytes,
            ordinary_native_reservations: native.ordinary.slots,
            recovery_native_reservations: native.recovery.slots,
            ordinary_native_bytes: native.ordinary.bytes,
            recovery_native_bytes: native.recovery.bytes,
            namespace_owners: report.namespace_owners,
        }
    }
}

impl StandaloneStateRuntime {
    pub(in crate::standalone) async fn start(
        bootstrap: StateBootstrap,
        settings: &StateSettings,
        supply_chain: Arc<SupplyChainAuthority>,
        policy: Arc<PolicyStore>,
        runtime: tokio::runtime::Handle,
    ) -> Result<(Self, EffectRuntime), PlatformError> {
        // These installed declarations need actual signed/current rule and
        // selected-asset producers. Descriptive config cannot replace them or
        // turn this empty bootstrap into a live transactional installation.
        if !settings.operations.is_empty() || !settings.tenant_quotas.is_empty() {
            return Err(super::unavailable());
        }
        // A current observer is attached before either original catalog is
        // exposed. Refuse an unrelated policy owner before any business I/O.
        let observer = bootstrap.authority.rejection_observer();
        if !policy.rejection_observer_matches(&observer) {
            return Err(super::unavailable());
        }
        let original_deadline = bootstrap.deadline;
        let adapter_clock = AdapterClock::default();
        let (kernel, mut effects) = StateKernel::start(
            bootstrap,
            settings,
            supply_chain,
            Vec::new(),
            &adapter_clock,
            runtime,
        )
        .await?;
        let admission = match kernel.admission_owners(policy, &effects) {
            Ok(admission) => admission,
            Err(failure) => {
                let _retirement = effects.shutdown(original_deadline).await;
                drop(effects);
                let _retirement = kernel.shutdown(original_deadline).await;
                return Err(failure);
            }
        };
        Ok((
            Self {
                kernel,
                admission: Some(admission),
                original_deadline,
                ready: false,
            },
            effects,
        ))
    }

    pub(in crate::standalone) fn publish_ready(
        &mut self,
        effects: &EffectRuntime,
    ) -> Result<(), PlatformError> {
        if self.ready || self.kernel.original_deadline()? != self.original_deadline {
            return Err(super::unavailable());
        }
        self.kernel.check_ready(effects)?;
        // Dispatcher remains paused. No execution rule or configured target is
        // installed by this empty protected bootstrap readiness observation.
        self.ready = true;
        Ok(())
    }

    pub(in crate::standalone) fn is_running(&self, effects: &EffectRuntime) -> bool {
        self.ready && self.kernel.is_running(effects)
    }

    pub(in crate::standalone) async fn shutdown(
        mut self,
        deadline: Instant,
    ) -> Result<StateRetirementReport, PlatformError> {
        // The same original boot cutoff governs failure before readiness. A
        // completed node instead uses its original node-shutdown cutoff.
        let deadline = if self.ready {
            deadline
        } else {
            deadline.min(self.original_deadline)
        };
        drop(self.admission.take());
        self.kernel.shutdown(deadline).await.map(Into::into)
    }
}
