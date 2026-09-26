use std::{
    sync::Arc,
    time::{Duration, Instant},
};

use super::{ProviderDescriptor, ProviderServices, ProviderShutdownReport};
use latent_artifacts::DirectoryArtifactRepository;
use latent_blobs::{
    local::{LocalBlobLimits, LocalBlobStore},
    provider::LocalBlobProvider,
};
use latent_capabilities::broker::{
    io::{IoLimits, IoRuntime},
    pools::{ProviderPoolLimits, ProviderPools},
    ActivationCapabilityBroker, ActivationCapabilityRuntime, CapabilityBrokerLimits,
    ProviderReference, ProviderRegistration,
};
use latent_control_store::{
    bindings::{BindingLimits, ConfiguredBindingProvider},
    DirectoryDeploymentRepository,
};
use latent_core::{PlatformError, PlatformErrorCode, ServiceId, TenantId};
use latent_policy::capability::PolicyStore;

use crate::config::{NodeSettings, ProviderIdentity};

#[path = "events.rs"]
mod events;
#[path = "http.rs"]
mod http;
#[path = "local_service.rs"]
mod local_service;
#[path = "scalar.rs"]
mod scalar;
#[path = "secrets.rs"]
mod secrets;
#[path = "startup.rs"]
mod startup;

pub(in crate::standalone) struct ProviderRuntime {
    pub runtime: Arc<ActivationCapabilityRuntime>,
    pools: Arc<ProviderPools>,
    io: Arc<IoRuntime>,
    secrets: Option<latent_secrets::LocalSecretStore>,
    guest_secrets: Option<latent_secrets::LocalSecretStore>,
    event_secrets: Option<latent_secrets::LocalSecretStore>,
    metrics: Option<Arc<latent_capabilities::broker::metrics::MetricProvider>>,
    blobs: Option<Arc<LocalBlobStore>>,
    registrations: Vec<ProviderRegistration>,
    descriptors: Vec<ProviderDescriptor>,
}

impl ProviderRuntime {
    #[expect(
        clippy::too_many_lines,
        reason = "bounded provider owners are installed and rolled back in one transaction"
    )]
    pub async fn open(
        settings: &NodeSettings,
        artifacts: &Arc<DirectoryArtifactRepository>,
        deployments: &Arc<DirectoryDeploymentRepository>,
        policies: Arc<PolicyStore>,
        services: ProviderServices,
    ) -> Result<Self, PlatformError> {
        let config = settings.providers.as_ref().ok_or_else(unavailable)?;
        let broker = Arc::new(
            ActivationCapabilityBroker::new(
                artifacts.lifecycle_authority(),
                policies,
                services.clock,
                CapabilityBrokerLimits::default(),
            )?
            .with_audit(services.audit, true)?,
        );
        let io = Arc::new(IoRuntime::new(IoLimits::default())?);
        let pools = Arc::new(ProviderPools::new(
            broker.clone(),
            io.clone(),
            services.control,
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
            guest_secrets: None,
            event_secrets: None,
            metrics: None,
            blobs: None,
            registrations: Vec::with_capacity(3),
            descriptors: Vec::with_capacity(9),
        };
        let deadline = Instant::now() + Duration::from_secs(30);
        let installed = tokio::time::timeout_at(deadline.into(), async {
            let mut providers = Vec::with_capacity(9);
            for (installation, monotonic) in
                [(&config.clock_monotonic, true), (&config.clock_wall, false)]
            {
                if let Some(installation) = installation {
                    let registration =
                        scalar::clock(&broker, installation.identity.epoch, monotonic)?;
                    providers.push(owner.record(&installation.identity, registration.reference()));
                    owner.registrations.push(registration);
                }
            }
            if let Some(installation) = &config.random {
                let provider = latent_capabilities::broker::random::RandomProvider::system(
                    &broker,
                    installation.identity.epoch,
                    latent_capabilities::broker::random::RandomLimits::default(),
                )?;
                providers.push(owner.record(&installation.identity, provider.reference()));
                owner.runtime.install_random(provider)?;
            }
            if let Some(http) = &config.http {
                let (provider, secrets) = http::install(&owner.pools, http, deadline).await?;
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
            if let Some(config) = &config.events {
                let (provider, store) = events::install(&owner.pools, config, deadline).await?;
                owner.event_secrets = Some(store);
                providers.push(owner.record(&config.identity, provider.reference()));
                owner.runtime.install_events(Arc::new(provider))?;
            }
            if let Some(config) = &config.secrets {
                let (provider, store) = secrets::install(&owner.pools, config, deadline).await?;
                owner.guest_secrets = Some(store);
                providers.push(owner.record(&config.identity, provider.reference()));
                owner.runtime.install_secrets(Arc::new(provider))?;
            }
            if let Some(config) = &config.metrics {
                let provider = latent_capabilities::broker::metrics::MetricProvider::install(
                    &broker,
                    services.telemetry.ok_or_else(unavailable)?,
                    config.identity.epoch,
                    config.configuration(),
                    latent_capabilities::broker::metrics::MetricActivationLimits {
                        maximum_observations: 32,
                        maximum_series: 16,
                        maximum_record_bytes: 1024 * 1024,
                    },
                )?;
                providers.push(owner.record(&config.identity, provider.reference()));
                owner.metrics = Some(provider.clone());
                owner.runtime.install_metrics(provider)?;
            }
            if let Some(config) = &config.local_service {
                let registration = local_service::install(&broker, config)?;
                let mut provider = owner.record(&config.identity, registration.reference());
                provider.local_deployment =
                    Some(latent_core::DeploymentId(config.deployment.clone()));
                providers.push(provider);
                owner.registrations.push(registration);
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

    pub fn metric_observation(
        &self,
        sink: &latent_telemetry::StructuredLocalSink,
    ) -> Result<Option<super::MetricObservation>, PlatformError> {
        self.metrics
            .as_ref()
            .map(|provider| super::metrics::observe(provider, sink))
            .transpose()
    }

    pub fn retire(&self) {
        self.runtime.retire();
        for registration in &self.registrations {
            registration.retire();
        }
        self.pools.retire();
        if let Some(secrets) = &self.secrets {
            secrets.close();
        }
        if let Some(secrets) = &self.guest_secrets {
            secrets.close();
        }
        if let Some(secrets) = &self.event_secrets {
            secrets.close();
        }
        if let Some(metrics) = &self.metrics {
            metrics.retire();
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
        let mut secret_generations = 0;
        let mut secret_references = 0;
        let mut secrets_closed = true;
        for store in [&self.secrets, &self.guest_secrets, &self.event_secrets]
            .into_iter()
            .flatten()
        {
            store.close();
            let snapshot = store.snapshot().map_err(|_| unavailable())?;
            secret_generations += snapshot.retained_generations;
            secret_references += snapshot.references;
            secrets_closed &= snapshot.closed && !snapshot.loading;
        }
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
            && secrets_closed
            && secret_generations == 0
            && secret_references == 0
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
            secret_generations,
            secret_references,
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
