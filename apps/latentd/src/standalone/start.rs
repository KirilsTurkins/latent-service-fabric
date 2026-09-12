use latent_admission::LocalAdmissionController;
use latent_artifacts::DirectoryArtifactRepository;
use latent_control_store::DirectoryDeploymentRepository;
use latent_core::SystemActivationClock;
use latent_node::{
    LocalActivationDependencies, LocalActivationServices, StandaloneInventoryReporter,
    StandaloneInventorySources,
};
use latent_routing::{ResolvedRevision, RevisionAdmissionPolicy, RevisionPolicySource};
use latent_wasmtime::{TelemetryLogSink, WasmtimeHostServices};
use latent_wire::invocation::{
    ActivationCleanupOwner, InvocationServiceAdapter, InvocationServiceServices,
    LocalInvocationRuntime, LocalPrincipalPolicy,
};
use latent_wire::management::{
    LocalManagementPolicy, ManagementServiceAdapter, ManagementServices,
};

use super::{
    error, load, observations, transport, ActivationClock, Arc, LocalActivationManager,
    LocalQuotaProvider, LocalScheduler, PlatformError, PlatformErrorCode, RuntimeThreads,
    SharedActivationObserver, StandaloneNode, StructuredLocalSink, TelemetryRuntime,
    WasmtimeComponentEngineFactory,
};
use crate::config::NodeSettings;

mod control;
#[cfg(test)]
mod tests;

pub(super) struct Catalogs {
    pub(super) artifacts: Arc<DirectoryArtifactRepository>,
    pub(super) deployments: Arc<DirectoryDeploymentRepository>,
    pub(super) supply_chain: Option<Arc<latent_policy::supply_chain::SupplyChainAuthority>>,
    control: Option<control::StartupControl>,
}

impl Catalogs {
    #[cfg(test)]
    pub(super) async fn open_observed(
        settings: &NodeSettings,
        observer: latent_control_store::CatalogWorkObserver,
    ) -> Result<Self, PlatformError> {
        if settings.supply_chain.is_enforced() {
            return Err(mode_error());
        }
        let artifacts = Arc::new(DirectoryArtifactRepository::open(
            settings.data_directory.join("releases"),
            settings.artifacts,
        )?);
        let deployments = Arc::new(
            DirectoryDeploymentRepository::open_observed_with_catalog(
                settings.data_directory.join("deployments"),
                artifacts.clone(),
                settings.deployments,
                observer,
                artifacts.lifecycle_authority(),
                Arc::clone(&settings.runtime_profile),
            )
            .await?,
        );
        Ok(Self {
            artifacts,
            deployments,
            supply_chain: None,
            control: None,
        })
    }

    #[cfg(test)]
    pub(super) async fn open(settings: &NodeSettings) -> Result<Self, PlatformError> {
        if settings.supply_chain.is_enforced() {
            return Err(mode_error());
        }
        Self::open_inner(settings, None).await
    }

    pub(super) async fn open_with_control(
        settings: &NodeSettings,
        runtime: &tokio::runtime::Handle,
    ) -> Result<Self, PlatformError> {
        Self::open_inner(settings, Some(runtime)).await
    }

    async fn open_inner(
        settings: &NodeSettings,
        runtime: Option<&tokio::runtime::Handle>,
    ) -> Result<Self, PlatformError> {
        let supply_chain = settings.supply_chain.open(
            &settings.data_directory,
            Arc::clone(&settings.runtime_profile),
        )?;
        let mut control = supply_chain.as_ref().map(|authority| {
            control::StartupControl::start(
                Arc::clone(authority),
                settings.load_sample_interval,
                runtime.expect("enforced startup requires its supplied control runtime"),
            )
        });
        let opened = async {
            let artifacts = Arc::new(if let Some(authority) = &supply_chain {
                DirectoryArtifactRepository::open_enforced(
                    settings.data_directory.join("releases"),
                    settings.artifacts,
                    latent_artifacts::AdmissionStorageLimits::default(),
                    authority.clone(),
                )?
            } else {
                DirectoryArtifactRepository::open(
                    settings.data_directory.join("releases"),
                    settings.artifacts,
                )?
            });
            let deployments = Arc::new(
                DirectoryDeploymentRepository::open_with_catalog(
                    settings.data_directory.join("deployments"),
                    artifacts.clone(),
                    settings.deployments,
                    artifacts.lifecycle_authority(),
                    Arc::clone(&settings.runtime_profile),
                )
                .await?,
            );
            Ok::<_, PlatformError>((artifacts, deployments))
        }
        .await;
        let (artifacts, deployments) = match opened {
            Ok(catalogs) => catalogs,
            Err(failure) => {
                if let Some(control) = control.take() {
                    let _ = control.shutdown(settings.shutdown_grace).await;
                }
                return Err(failure);
            }
        };
        Ok(Self {
            artifacts,
            deployments,
            supply_chain,
            control,
        })
    }
}

impl StandaloneNode {
    pub async fn start(
        settings: NodeSettings,
        control_runtime: tokio::runtime::Handle,
        threads: RuntimeThreads,
    ) -> Result<Self, PlatformError> {
        if !cfg!(target_os = "linux") {
            return Err(error(
                PlatformErrorCode::IncompatibleContract,
                "standalone durable node requires Linux",
            ));
        }
        let catalogs = Catalogs::open_with_control(&settings, &control_runtime).await?;
        Box::pin(Self::start_with_catalogs(
            settings,
            catalogs,
            control_runtime,
            threads,
        ))
        .await
    }

    // Production startup and the isolated measurement collector share every
    // runtime/service owner. The collector may retain catalog ports for timing.
    pub(super) async fn start_with_catalogs(
        settings: NodeSettings,
        catalogs: Catalogs,
        control_runtime: tokio::runtime::Handle,
        threads: RuntimeThreads,
    ) -> Result<Self, PlatformError> {
        Self::start_with_catalogs_and_clock(
            settings,
            catalogs,
            control_runtime,
            threads,
            Arc::new(SystemActivationClock),
        )
        .await
    }

    pub(super) async fn start_with_catalogs_and_clock(
        mut settings: NodeSettings,
        mut catalogs: Catalogs,
        control_runtime: tokio::runtime::Handle,
        threads: RuntimeThreads,
        clock: Arc<dyn ActivationClock>,
    ) -> Result<Self, PlatformError> {
        let mut node = match Self::compose(&mut settings, &catalogs, clock) {
            Ok(node) => node,
            Err(failure) => {
                if let Some(control) = catalogs.control.take() {
                    let _ = control.shutdown(settings.shutdown_grace).await;
                }
                return Err(failure);
            }
        };
        if let Some(control) = catalogs.control.take() {
            node.sampler = Some(control.transfer());
        }
        if let Err(failure) =
            Box::pin(node.start_services(&settings, catalogs, control_runtime, threads)).await
        {
            // Keep every created async owner inside the startup lifetime. The
            // original startup failure remains a failure even if cleanup joins.
            let _ = node.shutdown().await;
            return Err(failure);
        }
        Ok(node)
    }

    async fn start_services(
        &mut self,
        settings: &NodeSettings,
        catalogs: Catalogs,
        control_runtime: tokio::runtime::Handle,
        threads: RuntimeThreads,
    ) -> Result<(), PlatformError> {
        let invocation = InvocationServiceAdapter::with_services(
            Arc::new(LocalInvocationRuntime::with_cleanup(
                self.manager.clone(),
                settings.invocation.clone(),
                self.cleanup
                    .as_ref()
                    .expect("owned cleanup driver")
                    .handle(),
            )?),
            settings.invocation.clone(),
            InvocationServiceServices {
                clock: Arc::clone(&self.clock),
                ..InvocationServiceServices::default()
            },
        )?;
        let management = ManagementServiceAdapter::new(
            ManagementServices {
                artifacts: catalogs.artifacts,
                deployments: catalogs.deployments.clone(),
                routes: catalogs.deployments.clone(),
                inventory: self.inventory.clone(),
                principals: Arc::new(LocalPrincipalPolicy),
                authorization: Arc::new(LocalManagementPolicy),
                clock: Arc::clone(&self.clock),
            },
            settings.management.clone(),
        )?;
        if self.sampler.is_none() {
            self.sampler = Some(load::LoadSampler::start(
                Arc::clone(&self.load),
                settings.load_sample_interval,
                &control_runtime,
                catalogs.supply_chain,
            ));
        }
        let transport = transport::Transport::start(
            settings.transport.clone(),
            invocation,
            management,
            Arc::clone(&self.clock),
            control_runtime,
        )
        .await?;
        self.transport = Some(transport);
        let transport = self.transport.as_ref().expect("owned started transport");
        let topology = Arc::new(observations::TopologySource::new(
            settings,
            self.backend.clone(),
            self.scheduler.clone(),
            transport.handle(),
            self.cleanup
                .as_ref()
                .expect("owned cleanup driver")
                .handle(),
            threads,
        ));
        let mut descriptor = settings.node.clone();
        descriptor.endpoint = format!("http://{}", transport.local_addr());
        self.inventory
            .install(Arc::new(StandaloneInventoryReporter::new(
                settings.inventory.clone(),
                descriptor,
                StandaloneInventorySources {
                    scheduler: self.scheduler.clone(),
                    routes: catalogs.deployments,
                    quotas: self.quotas.clone(),
                    load: self.load.clone(),
                    cache: Arc::new(observations::CacheSource::new(self.backend.clone())),
                    topology,
                    clock: Arc::clone(&self.clock),
                },
            )?))?;
        self.load.start_accepting();
        transport.handle().start_accepting()?;
        Ok(())
    }

    fn compose(
        settings: &mut NodeSettings,
        catalogs: &Catalogs,
        clock: Arc<dyn ActivationClock>,
    ) -> Result<Self, PlatformError> {
        if settings.supply_chain.is_enforced() != catalogs.supply_chain.is_some()
            || (catalogs.supply_chain.is_some() && catalogs.control.is_none())
            || !catalogs
                .deployments
                .is_bound_to_catalog(&catalogs.artifacts.lifecycle_authority())
            || settings.supply_chain.is_enforced()
                != catalogs
                    .artifacts
                    .lifecycle_authority()
                    .required_authority()
                    .is_some()
        {
            return Err(mode_error());
        }
        let sink = Arc::new(StructuredLocalSink::new(settings.local_sink)?);
        let (telemetry, telemetry_runtime) =
            TelemetryRuntime::spawn(settings.telemetry, sink.clone())?;
        let observer = Arc::new(SharedActivationObserver::new(
            telemetry.clone(),
            settings.observer.clone(),
        )?);
        let host_services = WasmtimeHostServices {
            clock: Arc::clone(&clock),
            log_sink: Some(Arc::new(TelemetryLogSink::new(
                observer.clone(),
                Arc::clone(&clock),
            ))),
        };
        let factory = factory(settings, catalogs, host_services)?;
        if factory.runtime_profile().digest() != settings.runtime_profile.digest() {
            return Err(error(
                PlatformErrorCode::IncompatibleContract,
                "node-runtime-profile-changed",
            ));
        }
        let backend = Arc::new(factory.create_backend_instance());
        let quotas = LocalQuotaProvider::new(settings.admission.clone())?;
        let scheduler = Arc::new(LocalScheduler::new(
            settings.scheduler.clone(),
            quotas.clone(),
        )?);
        let load = catalogs.control.as_ref().map_or_else(
            || Arc::new(load::HostLoad::default()),
            control::StartupControl::load,
        );
        let admission =
            LocalAdmissionController::new(Arc::new(UnpinnedPolicy), quotas.clone(), load.clone());
        let manager = LocalActivationManager::with_services(
            settings.manager.clone(),
            LocalActivationDependencies {
                catalog: catalogs.deployments.clone(),
                admission,
                scheduler: scheduler.clone(),
                artifacts: catalogs.artifacts.clone(),
                backend: backend.clone(),
            },
            LocalActivationServices {
                clock: Arc::clone(&clock),
                observer: Some(observer.clone()),
                ..LocalActivationServices::default()
            },
        )?;
        Ok(Self {
            transport: None,
            supply_chain: super::SupplyChainLifetime(catalogs.supply_chain.clone()),
            cleanup: Some(ActivationCleanupOwner::start_with_observer(
                settings.manager.journal.maximum_active,
                settings.manager.cleanup_grace,
                &tokio::runtime::Handle::current(),
                clock.deadline_diagnostic_observer().cloned(),
            )?),
            sampler: None,
            telemetry_runtime: Some(telemetry_runtime),
            factory: Some(factory),
            load,
            inventory: Arc::new(observations::InventorySlot::new()),
            manager,
            scheduler,
            backend,
            quotas,
            observer,
            telemetry,
            sink,
            clock,
            classes: settings.inventory.cell_classes.clone(),
            shutdown_grace: settings.shutdown_grace,
            cleanup_grace: settings.manager.cleanup_grace,
        })
    }
}

fn factory(
    settings: &mut NodeSettings,
    catalogs: &Catalogs,
    services: WasmtimeHostServices,
) -> Result<WasmtimeComponentEngineFactory, PlatformError> {
    // Consume the secret-bearing settings once. Configured isolation never
    // falls back to the ordinary compiler when cache or sandbox setup fails.
    match settings.isolated_aot.take() {
        Some(aot) => WasmtimeComponentEngineFactory::with_catalog_and_aot(
            settings.wasmtime.clone(),
            services,
            Arc::clone(&catalogs.artifacts),
            aot,
        ),
        None => WasmtimeComponentEngineFactory::with_catalog(
            settings.wasmtime.clone(),
            services,
            catalogs.artifacts.lifecycle_authority(),
        ),
    }
}

fn mode_error() -> PlatformError {
    error(
        PlatformErrorCode::PermissionDenied,
        "enforced startup requires matching catalogs and control owner",
    )
}

// The activation manager supplies the same pinned view used to resolve each
// request. Fail closed if admission is accidentally used without that view;
// retaining a startup catalog here would keep obsolete metadata alive.
struct UnpinnedPolicy;

impl RevisionPolicySource for UnpinnedPolicy {
    fn admission_policy(
        &self,
        _: &ResolvedRevision,
    ) -> Result<RevisionAdmissionPolicy, PlatformError> {
        Err(error(
            PlatformErrorCode::RouteUnavailable,
            "activation catalog is not pinned",
        ))
    }
}
