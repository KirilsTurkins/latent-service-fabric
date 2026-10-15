//! Actual empty-target bootstrap never falls back to a stateless readiness path.
use std::{sync::Arc, time::Instant};

use latent_core::ActivationClock;
use latent_core::PlatformError;
use latent_node::transaction_runtime::{TransactionAdmissionOwners, TransactionInstallation};
use latent_policy::{capability::PolicyStore, supply_chain::SupplyChainAuthority};
use latent_wire::{
    invocation::{
        ActivationCleanupHandle, InvocationLimits, LocalPrincipalPolicy,
        SystemInvocationTraceSource,
    },
    phase4::{
        LocalTransactionRuntime, LocalTransactionServices, Phase4Runtime, StateManagementBackend,
    },
};
use serde::Serialize;

use super::{AdapterClock, StateBootstrap, StateKernel, StateShutdownReport};
use crate::config::state::StateSettings;
use crate::standalone::effects::EffectRuntime;
use crate::standalone::startup_observation::{record_platform, Stage};

pub(in crate::standalone) struct StandaloneStateRuntime {
    kernel: StateKernel,
    admission: Option<Arc<TransactionAdmissionOwners>>,
    installations: Vec<Arc<TransactionInstallation>>,
    management: Option<StateManagementBackend>,
    operations: Vec<crate::config::state::OperationSettings>,
    original_deadline: Instant,
    ready: bool,
    http_rules: bool,
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
        installed: Option<super::InstalledStateServices>,
        runtime: tokio::runtime::Handle,
    ) -> Result<(Self, EffectRuntime), PlatformError> {
        if (!settings.operations.is_empty() || !settings.tenant_quotas.is_empty())
            && installed.is_none()
        {
            return Err(super::unavailable());
        }
        // A current observer is attached before either original catalog is
        // exposed. Refuse an unrelated policy owner before any business I/O.
        let observer = bootstrap.authority.rejection_observer();
        if !policy.rejection_observer_matches(&observer) {
            return Err(super::unavailable());
        }
        let original_deadline = bootstrap.deadline;
        let adapter_clock = installed.as_ref().map_or_else(
            || Arc::new(AdapterClock::default()),
            |s| Arc::clone(&s.http.clock),
        );
        let adapters = installed
            .as_ref()
            .map(|s| {
                s.http
                    .adapters
                    .iter()
                    .cloned()
                    .map(|a| a as Arc<dyn latent_effects::runtime::DeferredEffectAdapter>)
                    .collect()
            })
            .unwrap_or_default();
        let (kernel, mut effects) = StateKernel::start(
            bootstrap,
            settings,
            supply_chain,
            adapters,
            adapter_clock.as_ref(),
            runtime,
        )
        .await
        .inspect_err(|error| record_platform(Stage::ProtectedStoreStartup, error))?;
        let admission = match kernel.admission_owners(Arc::clone(&policy), &effects) {
            Ok(admission) => admission,
            Err(failure) => {
                record_platform(Stage::StateManagement, &failure);
                let _retirement = effects.shutdown(original_deadline).await;
                drop(effects);
                let _retirement = kernel.shutdown(original_deadline).await;
                return Err(failure);
            }
        };
        let installed = match installed {
            Some(services) => {
                super::installations::load(
                    &kernel, settings, &admission, policy, services, &effects,
                )
                .await
            }
            None => Ok(super::installations::InstalledState {
                installations: Vec::new(),
                management: None,
                http_rules: false,
            }),
        };
        let installed = match installed {
            Ok(installed) => installed,
            Err(failure) => {
                record_platform(Stage::StateOperations, &failure);
                drop(admission);
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
                installations: installed.installations,
                management: installed.management,
                operations: settings.operations.clone(),
                original_deadline,
                ready: false,
                http_rules: installed.http_rules,
            },
            effects,
        ))
    }

    pub(in crate::standalone) fn transaction_http(
        &self,
    ) -> Option<super::super::http::transaction::Services> {
        Some(super::super::http::transaction::Services {
            owners: Arc::clone(self.admission.as_ref()?),
            installations: self.installations.clone().into(),
            operations: self.operations.clone().into(),
            management: self.management.clone()?,
        })
    }

    pub(in crate::standalone) fn transaction_rpc(
        &self,
        manager: latent_node::LocalActivationManager,
        cleanup: ActivationCleanupHandle,
        limits: InvocationLimits,
        clock: Arc<dyn ActivationClock>,
    ) -> Result<Option<Arc<dyn Phase4Runtime>>, PlatformError> {
        let Some(management) = self.management.as_ref() else {
            return Ok(None);
        };
        if self.installations.is_empty() {
            return Ok(Some(Arc::new(management.clone())));
        }
        Ok(Some(Arc::new(LocalTransactionRuntime::new(
            manager,
            cleanup,
            Arc::clone(self.admission.as_ref().ok_or_else(super::unavailable)?),
            self.installations.clone(),
            Arc::new(management.clone()),
            limits,
            LocalTransactionServices {
                clock,
                principals: Arc::new(LocalPrincipalPolicy),
                traces: Arc::new(SystemInvocationTraceSource::default()),
            },
        )?)))
    }

    pub(in crate::standalone) fn publish_ready(
        &mut self,
        effects: &EffectRuntime,
    ) -> Result<(), PlatformError> {
        if self.ready || self.kernel.original_deadline()? != self.original_deadline {
            return Err(super::unavailable());
        }
        self.kernel.check_ready(effects)?;
        if self.http_rules {
            effects.release_startup()?;
        } else {
            effects.finish_startup_paused()?;
        }
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
        drop(self.management.take());
        self.installations.clear();
        self.kernel.shutdown(deadline).await.map(Into::into)
    }
}
