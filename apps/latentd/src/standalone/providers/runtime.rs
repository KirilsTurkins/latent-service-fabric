use std::{
    sync::Arc,
    time::{Duration, Instant},
};

use super::{ProviderDescriptor, ProviderShutdownReport};
use latent_artifacts::DirectoryArtifactRepository;
use latent_audit::AuditHandle;
use latent_blobs::{
    local::{LocalBlobLimits, LocalBlobStore},
    provider::LocalBlobProvider,
};
use latent_capabilities::broker::{
    io::{IoLimits, IoRuntime},
    pools::{ProviderPoolLimits, ProviderPools},
    ActivationCapabilityBroker, ActivationCapabilityRuntime, CapabilityBrokerLimits,
    ProviderReference,
};
use latent_control_store::{
    bindings::{BindingLimits, ConfiguredBindingProvider},
    DirectoryDeploymentRepository,
};
use latent_core::{ActivationClock, PlatformError, PlatformErrorCode, ServiceId, TenantId};
use latent_policy::capability::PolicyStore;

use crate::config::{NodeSettings, ProviderIdentity};

#[path = "http.rs"]
mod http;
#[path = "startup.rs"]
mod startup;

pub(in crate::standalone) struct ProviderRuntime {
    pub runtime: Arc<ActivationCapabilityRuntime>,
    pools: Arc<ProviderPools>,
    io: Arc<IoRuntime>,
    secrets: Option<latent_secrets::LocalSecretStore>,
    blobs: Option<Arc<LocalBlobStore>>,
    descriptors: Vec<ProviderDescriptor>,
}

impl ProviderRuntime {
    pub async fn open(
        settings: &NodeSettings,
        artifacts: &Arc<DirectoryArtifactRepository>,
        deployments: &Arc<DirectoryDeploymentRepository>,
        policies: Arc<PolicyStore>,
        audit: AuditHandle,
        clock: Arc<dyn ActivationClock>,
        control: tokio::runtime::Handle,
    ) -> Result<Self, PlatformError> {
        let config = settings.providers.as_ref().ok_or_else(unavailable)?;
        let broker = Arc::new(
            ActivationCapabilityBroker::new(
                artifacts.lifecycle_authority(),
                policies,
                clock,
                CapabilityBrokerLimits::default(),
            )?
            .with_audit(audit, true)?,
        );
        let io = Arc::new(IoRuntime::new(IoLimits::default())?);
        let pools = Arc::new(ProviderPools::new(
            broker.clone(),
            io.clone(),
            control,
            ProviderPoolLimits::default(),
        )?);
        let runtime = Arc::new(ActivationCapabilityRuntime::new(
            broker.clone(),
            deployments.clone(),
        ));
        let mut owner = Self {
            runtime,
            pools,
            io,
            secrets: None,
            blobs: None,
            descriptors: Vec::with_capacity(2),
        };
        let deadline = Instant::now() + Duration::from_secs(30);
        let installed = tokio::time::timeout_at(deadline.into(), async {
            let mut providers = Vec::with_capacity(2);
            if let Some(http) = &config.http {
                let (provider, secrets) = http::install(&owner.pools, http).await?;
                owner.secrets = secrets;
                providers.push(owner.record(&http.identity, provider.reference()));
                owner.runtime.install_http(Arc::new(provider))?;
            }
            if let Some(blob) = &config.blob {
                let root = settings
                    .data_directory
                    .join(format!("provider-blobs-{}", blob.identity.id));
                let job = startup::admit(
                    || {
                        let root = root.clone();
                        let namespace = blob.namespace.clone();
                        owner.pools.control_blocking(move || {
                            LocalBlobStore::open(&root, &namespace, LocalBlobLimits::default())
                        })
                    },
                    deadline,
                )
                .await?;
                let store = job.wait().await?.map_err(|_| unavailable())?;
                let provider = LocalBlobProvider::install(
                    owner.pools.clone(),
                    &blob.identity.id,
                    blob.identity.epoch,
                    0,
                    store.clone(),
                )
                .map_err(|_| unavailable())?;
                owner.blobs = Some(store);
                providers.push(owner.record(&blob.identity, provider.reference()));
                owner.runtime.install_blobs(Arc::new(provider))?;
            }
            deployments
                .activate_configured_bindings(
                    config.definitions()?,
                    broker,
                    providers,
                    BindingLimits::default(),
                )
                .await
        })
        .await
        .unwrap_or_else(|_| Err(unavailable()));
        if let Err(failure) = installed {
            let _ = owner
                .shutdown(Instant::now() + settings.shutdown_grace)
                .await;
            return Err(failure);
        }
        Ok(owner)
    }

    fn record(
        &mut self,
        identity: &ProviderIdentity,
        reference: ProviderReference,
    ) -> ConfiguredBindingProvider {
        self.descriptors.push(ProviderDescriptor {
            id: identity.id.clone(),
            tenant: identity.tenant.clone(),
            service: identity.service.clone(),
            capability: reference.capability().to_owned(),
            profile: reference.profile().to_owned(),
            configuration_digest: reference.configuration_digest().to_owned(),
            configuration_epoch: reference.configuration_epoch().to_string(),
        });
        ConfiguredBindingProvider {
            tenant: TenantId(identity.tenant.clone()),
            service: ServiceId(identity.service.clone()),
            reference,
            local_deployment: None,
        }
    }

    pub fn descriptors(&self) -> &[ProviderDescriptor] {
        &self.descriptors
    }

    pub fn retire(&self) {
        self.runtime.retire();
        self.pools.retire();
        if let Some(secrets) = &self.secrets {
            secrets.close();
        }
        if let Some(blobs) = &self.blobs {
            blobs.close();
        }
    }

    pub async fn shutdown(
        &self,
        deadline: Instant,
    ) -> Result<ProviderShutdownReport, PlatformError> {
        self.retire();
        let pools = self.pools.shutdown(deadline).await?;
        let broker = self.runtime.broker().snapshot();
        let io = self.io.snapshot();
        let blob = self
            .blobs
            .as_ref()
            .map(|store| store.snapshot())
            .transpose()
            .map_err(|_| unavailable())?
            .unwrap_or_default();
        let clean = pools.is_clean()
            && broker.sessions == 0
            && broker.handles == 0
            && broker.calls == 0
            && broker.results == 0
            && broker.buffer_bytes == 0
            && io.calls == 0
            && io.occupied_running_slots == 0
            && io.queued_calls == 0
            && io.staged_bytes == 0
            && io.result_bytes == 0
            && io.metadata_bytes == 0
            && io.buffers == 0
            && io.streams == 0
            && blob_quiescent(&blob);
        Ok(ProviderShutdownReport {
            clean,
            control_owners: pools.control_owners,
            connections: pools.connections,
            pending_requests: pools.pending_requests,
            running_requests: pools.running_requests,
            workers: pools.workers,
            cleanup_jobs: pools.cleanup_jobs,
            failed_cleanup: pools.failed_cleanup,
            sessions: broker.sessions,
            handles: broker.handles,
            calls: broker.calls,
            results: broker.results,
            io_calls: io.calls,
            io_retained_bytes: io.staged_bytes + io.result_bytes + io.metadata_bytes,
            blob_stages: blob.stages,
            blob_handles: blob.handles,
            blob_work: blob.active_work,
        })
    }
}

impl Drop for ProviderRuntime {
    fn drop(&mut self) {
        self.retire();
    }
}

fn unavailable() -> PlatformError {
    crate::standalone::error(
        PlatformErrorCode::Unavailable,
        "configured-provider-unavailable",
    )
}

fn blob_quiescent(snapshot: &latent_blobs::local::LocalBlobSnapshot) -> bool {
    snapshot.handles == 0 && snapshot.active_work == 0 && !snapshot.poisoned
}

#[cfg(test)]
mod tests {
    use super::blob_quiescent;
    use latent_blobs::local::LocalBlobSnapshot;

    #[test]
    fn shutdown_retains_charged_durable_stages_without_claiming_live_handle_reclamation() {
        let mut snapshot = LocalBlobSnapshot {
            stages: 2,
            reserved_stage_bytes: 8192,
            accounted_disk_bytes: 32768,
            closed: true,
            ..LocalBlobSnapshot::default()
        };
        assert!(blob_quiescent(&snapshot));
        snapshot.handles = 1;
        assert!(!blob_quiescent(&snapshot));
        snapshot.handles = 0;
        snapshot.active_work = 1;
        assert!(!blob_quiescent(&snapshot));
        snapshot.active_work = 0;
        snapshot.poisoned = true;
        assert!(!blob_quiescent(&snapshot));
    }
}
