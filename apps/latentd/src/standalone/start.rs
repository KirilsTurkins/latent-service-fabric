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
mod recovery;
#[cfg(test)]
mod tests;

pub(super) struct Catalogs {
    profile: crate::config::ExecutionProfileReport,
    pub(super) artifacts: Arc<DirectoryArtifactRepository>,
    pub(super) deployments: Arc<DirectoryDeploymentRepository>,
    pub(super) supply_chain: Option<Arc<latent_policy::supply_chain::SupplyChainAuthority>>,
    control: Option<control::StartupControl>,
    audit: Option<super::audit::AuditRuntime>,
    rollouts: Option<super::rollouts::RolloutRuntime>,
    policies: Option<super::policies::PolicyRuntime>,
    capabilities: Option<Arc<latent_capabilities::broker::ActivationCapabilityRuntime>>,
    providers: Option<Box<super::providers::ProviderRuntime>>,
    clock: Arc<dyn ActivationClock>,
}

impl Catalogs {
    fn validate_composition(
        &self,
        settings: &NodeSettings,
        clock: &Arc<dyn ActivationClock>,
    ) -> Result<(), PlatformError> {
        if let Some(capabilities) = &self.capabilities {
            capabilities.check_catalog(&self.artifacts.lifecycle_authority())?;
            capabilities.check_clock(clock)?;
            if capabilities.broker().has_audit()
                && self
                    .audit
                    .as_ref()
                    .is_none_or(|audit| !capabilities.broker().audit_owner_matches(&audit.handle()))
            {
                return Err(mode_error());
            }
            capabilities.check_policy_owner(
                self.policies
                    .as_ref()
                    .ok_or_else(mode_error)?
                    .handle()
                    .store(),
            )?;
        }
        if !self.profile.matches(settings)
            || settings.supply_chain.is_enforced() != self.supply_chain.is_some()
            || settings.audit.is_some() != self.audit.is_some()
            || settings.rollouts.is_some() != self.rollouts.is_some()
            || settings.capability_policies.is_some() != self.policies.is_some()
            || settings.providers.is_some() != self.providers.is_some()
            || self.policies.as_ref().is_some_and(|owner| {
                let handle = owner.handle();
                !handle
                    .store()
                    .catalog_owner_matches(&self.artifacts.lifecycle_authority())
                    || settings.capability_policies.is_none_or(|config| {
                        handle.store().limits() != config.store
                            || handle.maximum_jobs() != config.maximum_control_jobs
                    })
            })
            || settings.rollouts.and_then(|value| value.canary).is_some()
                != self.deployments.canary_hub().is_some()
            || !self.accepts_activation_clock(clock)
            || (self.supply_chain.is_some() && self.control.is_none())
            || !self
                .deployments
                .is_bound_to_catalog(&self.artifacts.lifecycle_authority())
            || settings.supply_chain.is_enforced()
                != self
                    .artifacts
                    .lifecycle_authority()
                    .required_authority()
                    .is_some()
        {
            return Err(mode_error());
        }
        Ok(())
    }

    fn accepts_activation_clock(&self, clock: &Arc<dyn ActivationClock>) -> bool {
        (self.control.is_none() && self.deployments.canary_hub().is_none())
            || Arc::ptr_eq(clock, &self.clock)
    }

    #[cfg(test)]
    pub(super) async fn open_observed(
        settings: &NodeSettings,
        observer: latent_control_store::CatalogWorkObserver,
    ) -> Result<Self, PlatformError> {
        let profile = settings.check_config()?;
        if settings.supply_chain.is_enforced()
            || settings.audit.is_some()
            || settings.rollouts.is_some()
            || settings.capability_policies.is_some()
        {
            return Err(mode_error());
        }
        let audit = super::audit::AuditRuntime::open(
            settings.data_directory.join("audit"),
            None,
            tokio::runtime::Handle::current(),
        )
        .await?;
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
            profile,
            artifacts,
            deployments,
            supply_chain: None,
            control: None,
            audit,
            rollouts: None,
            policies: None,
            capabilities: None,
            providers: None,
            clock: Arc::new(SystemActivationClock),
        })
    }

    #[cfg(test)]
    pub(super) async fn open(settings: &NodeSettings) -> Result<Self, PlatformError> {
        if settings.supply_chain.is_enforced()
            || settings.audit.is_some()
            || settings.rollouts.is_some()
            || settings.capability_policies.is_some()
        {
            return Err(mode_error());
        }
        Self::open_inner(settings, None, Arc::new(SystemActivationClock)).await
    }

    pub(super) async fn open_with_control(
        settings: &NodeSettings,
        runtime: &tokio::runtime::Handle,
    ) -> Result<Self, PlatformError> {
        Self::open_with_control_and_clock(settings, runtime, Arc::new(SystemActivationClock)).await
    }

    pub(super) async fn open_with_control_and_clock(
        settings: &NodeSettings,
        runtime: &tokio::runtime::Handle,
        clock: Arc<dyn ActivationClock>,
    ) -> Result<Self, PlatformError> {
        Self::open_inner(settings, Some(runtime), clock).await
    }

    #[allow(
        clippy::too_many_lines,
        reason = "keep startup ownership and ordered failure cleanup in one visible scope"
    )]
    async fn open_inner(
        settings: &NodeSettings,
        runtime: Option<&tokio::runtime::Handle>,
        clock: Arc<dyn ActivationClock>,
    ) -> Result<Self, PlatformError> {
        let profile = settings.check_config()?;
        settings.persist_execution_profile()?;
        let audit = super::audit::AuditRuntime::open(
            settings.data_directory.join("audit"),
            settings.audit,
            runtime
                .cloned()
                .unwrap_or_else(tokio::runtime::Handle::current),
        )
        .await?;
        let supply_chain = match settings.supply_chain.open(
            &settings.data_directory,
            Arc::clone(&settings.runtime_profile),
        ) {
            Ok(authority) => authority,
            Err(failure) => {
                if let Some(audit) = &audit {
                    let _ = audit.shutdown(settings.shutdown_grace).await;
                }
                return Err(failure);
            }
        };
        let mut control = supply_chain.as_ref().map(|authority| {
            control::StartupControl::start(
                Arc::clone(authority),
                settings.load_sample_interval,
                runtime.expect("enforced startup requires its supplied control runtime"),
                Arc::clone(&clock),
            )
        });
        let mut rollouts = None;
        let mut policies = None;
        let mut providers = None;
        let opened = async {
            let artifacts = Arc::new(if let Some(authority) = &supply_chain {
                let authority: Arc<dyn latent_artifacts::AdmissionAuthority> =
                    if let Some(audit) = &audit {
                        Arc::new(latent_artifacts::AuditedAdmissionAuthority::new(
                            authority.clone(),
                            audit.handle(),
                        ))
                    } else {
                        authority.clone()
                    };
                DirectoryArtifactRepository::open_enforced(
                    settings.data_directory.join("releases"),
                    settings.artifacts,
                    latent_artifacts::AdmissionStorageLimits::default(),
                    authority,
                )?
            } else {
                DirectoryArtifactRepository::open(
                    settings.data_directory.join("releases"),
                    settings.artifacts,
                )?
            });
            policies = super::policies::PolicyRuntime::open(
                &settings.data_directory.join("capability-policies"),
                settings.capability_policies,
                artifacts.lifecycle_authority(),
                runtime,
            )?;
            let deployments = DirectoryDeploymentRepository::open_with_catalog_and_rollout_limits(
                settings.data_directory.join("deployments"),
                artifacts.clone(),
                settings.deployments,
                artifacts.lifecycle_authority(),
                Arc::clone(&settings.runtime_profile),
                settings.rollouts.map_or_else(
                    latent_control_store::rollouts::RolloutLimits::recovery_maximum,
                    |value| value.store,
                ),
            )
            .await?;
            let deployments = if let Some(config) = settings.rollouts.and_then(|value| value.canary)
            {
                deployments.with_canary(
                    latent_telemetry::BoundedPhase2CanaryOutcomeWindow::with_clock(
                        config,
                        Arc::clone(&clock),
                    )?,
                )?
            } else {
                deployments
            };
            let deployments = Arc::new(deployments);
            if settings.providers.is_none() && !deployments.binding_definitions()?.is_empty() {
                return Err(mode_error());
            }
            if let Some(settings) = settings.rollouts {
                rollouts = Some(super::rollouts::RolloutRuntime::start(
                    deployments.clone(),
                    audit.as_ref().ok_or_else(mode_error)?.handle(),
                    settings.coordinator,
                    runtime.ok_or_else(mode_error)?,
                )?);
                rollouts
                    .as_ref()
                    .expect("owned coordinator")
                    .wait_started(std::time::Instant::now() + std::time::Duration::from_secs(30))
                    .await?;
            }
            if let Some(audit) = &audit {
                if rollouts.is_none() {
                    latent_rollout::reconcile_rollout_audit(
                        &audit.handle(),
                        deployments.as_ref(),
                        std::time::Instant::now() + std::time::Duration::from_secs(30),
                    )
                    .await?;
                }
                latent_rollout::deployment_audit::reconcile_deployment_audit(
                    &audit.handle(),
                    deployments.as_ref(),
                    std::time::Instant::now() + std::time::Duration::from_secs(30),
                )
                .await?;
                latent_rollout::trigger_audit::reconcile_trigger_audit(
                    &audit.handle(),
                    deployments.as_ref(),
                    std::time::Instant::now() + std::time::Duration::from_secs(30),
                )
                .await?;
                recovery::reconcile(
                    &audit.handle(),
                    artifacts.as_ref(),
                    std::time::Instant::now() + std::time::Duration::from_secs(30),
                )
                .await?;
            }
            if settings.providers.is_some() {
                providers = Some(Box::new(
                    super::providers::ProviderRuntime::open(
                        settings,
                        &artifacts,
                        &deployments,
                        policies
                            .as_ref()
                            .ok_or_else(mode_error)?
                            .handle()
                            .store()
                            .clone(),
                        audit.as_ref().ok_or_else(mode_error)?.handle(),
                        clock.clone(),
                        runtime.ok_or_else(mode_error)?.clone(),
                    )
                    .await?,
                ));
            }
            Ok::<_, PlatformError>((artifacts, deployments))
        }
        .await;
        let (artifacts, deployments) = match opened {
            Ok(catalogs) => catalogs,
            Err(failure) => {
                if let Some(providers) = &providers {
                    let _ = providers
                        .shutdown(std::time::Instant::now() + settings.shutdown_grace)
                        .await;
                }
                if let Some(rollouts) = &rollouts {
                    let _ = rollouts.shutdown(settings.shutdown_grace).await;
                }
                if let Some(control) = control.take() {
                    let _ = control.shutdown(settings.shutdown_grace).await;
                }
                let joined = match &rollouts {
                    Some(owner) => owner.worker_joined().await,
                    None => true,
                };
                if let Some(audit) = audit.as_ref().filter(|_| joined) {
                    let _ = audit.shutdown(settings.shutdown_grace).await;
                }
                return Err(failure);
            }
        };
        Ok(Self {
            profile,
            artifacts,
            deployments,
            supply_chain,
            control,
            audit,
            rollouts,
            policies,
            capabilities: providers.as_ref().map(|owner| owner.runtime.clone()),
            providers,
            clock,
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
        let catalogs = Box::pin(Catalogs::open_with_control(&settings, &control_runtime)).await?;
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
        let clock = Arc::clone(&catalogs.clock);
        Self::start_with_catalogs_and_clock(settings, catalogs, control_runtime, threads, clock)
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
                if let Some(providers) = &catalogs.providers {
                    let _ = providers
                        .shutdown(std::time::Instant::now() + settings.shutdown_grace)
                        .await;
                }
                if let Some(rollouts) = &catalogs.rollouts {
                    let _ = rollouts.shutdown(settings.shutdown_grace).await;
                }
                if let Some(control) = catalogs.control.take() {
                    let _ = control.shutdown(settings.shutdown_grace).await;
                }
                let joined = match &catalogs.rollouts {
                    Some(owner) => owner.worker_joined().await,
                    None => true,
                };
                if let Some(audit) = catalogs.audit.as_ref().filter(|_| joined) {
                    let _ = audit.shutdown(settings.shutdown_grace).await;
                }
                return Err(failure);
            }
        };
        if let Some(control) = catalogs.control.take() {
            node.sampler = Some(control.transfer());
        }
        node.audit = catalogs.audit.take();
        node.rollouts = catalogs.rollouts.take();
        node.policies = catalogs.policies.take();
        node.providers = catalogs.providers.take();
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

    fn policy_management(
        &self,
        mut management: ManagementServiceAdapter,
        catalogs: &Catalogs,
    ) -> Result<ManagementServiceAdapter, PlatformError> {
        if let Some(policies) = &self.policies {
            management = management.with_policy_control(policies.handle())?;
        }
        if let Some(capabilities) = &catalogs.capabilities {
            management = management.with_capability_inspection(
                catalogs.deployments.clone(),
                capabilities.broker().clone(),
            )?;
        }
        management.with_http_control(catalogs.deployments.clone())
    }

    #[expect(
        clippy::too_many_lines,
        reason = "ordered shared transports, inventory installation and admission cutover stay together"
    )]
    async fn start_services(
        &mut self,
        settings: &NodeSettings,
        catalogs: Catalogs,
        control_runtime: tokio::runtime::Handle,
        threads: RuntimeThreads,
    ) -> Result<(), PlatformError> {
        let cleanup = self
            .cleanup
            .as_ref()
            .expect("owned cleanup driver")
            .handle();
        let invocation = InvocationServiceAdapter::with_services(
            Arc::new(LocalInvocationRuntime::with_cleanup(
                self.manager.clone(),
                settings.invocation.clone(),
                cleanup.clone(),
            )?),
            settings.invocation.clone(),
            InvocationServiceServices {
                clock: Arc::clone(&self.clock),
                ..InvocationServiceServices::default()
            },
        )?;
        let management = ManagementServiceAdapter::new(
            ManagementServices {
                audit: self.audit.as_ref().map(super::audit::AuditRuntime::handle),
                rollouts: self
                    .rollouts
                    .as_ref()
                    .map(super::rollouts::RolloutRuntime::handle),
                artifacts: catalogs.artifacts.clone(),
                deployments: catalogs.deployments.clone(),
                routes: catalogs.deployments.clone(),
                inventory: self.inventory.clone(),
                principals: Arc::new(LocalPrincipalPolicy),
                authorization: Arc::new(LocalManagementPolicy),
                clock: Arc::clone(&self.clock),
            },
            settings.management.clone(),
        )?;
        let management = self.policy_management(management, &catalogs)?;
        if self.sampler.is_none() {
            self.sampler = Some(load::LoadSampler::start(
                Arc::clone(&self.load),
                settings.load_sample_interval,
                &control_runtime,
                catalogs.supply_chain,
                Arc::clone(&self.clock),
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
        self.start_http(settings, &catalogs.deployments)?;
        #[cfg(all(target_os = "linux", target_arch = "x86_64"))]
        if let Some(http) = &self.http {
            http.install_assets(catalogs.artifacts.clone())?;
        }
        let transport = self.transport.as_ref().expect("owned started transport");
        let topology = Arc::new(
            observations::TopologySource::new(
                settings,
                self.backend.clone(),
                self.scheduler.clone(),
                transport.handle(),
                cleanup,
                threads,
            )
            .with_policies(
                self.policies
                    .as_ref()
                    .map(super::policies::PolicyRuntime::handle),
            )
            .with_http(self.http.as_ref().map(super::http::HttpOwner::handle))
            .with_rollouts(
                self.rollouts
                    .as_ref()
                    .map(super::rollouts::RolloutRuntime::handle),
            ),
        );
        let mut descriptor = settings.node.clone();
        descriptor.endpoint = format!("http://{}", transport.local_addr());
        self.describe_http(settings, &mut descriptor);
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
        if let Some(http) = &self.http {
            http.handle().start_accepting()?;
        }
        Ok(())
    }

    fn describe_http(&self, settings: &NodeSettings, descriptor: &mut latent_node::NodeDescriptor) {
        if let Some(http) = &self.http {
            let scheme = if settings.http.as_ref().expect("HTTP settings").tls.is_some() {
                "https"
            } else {
                "http"
            };
            descriptor.attributes.insert(
                "lsf.http.endpoint".into(),
                format!("{scheme}://{}", http.local_addr()),
            );
            descriptor
                .attributes
                .insert("lsf.http.profile".into(), "buffered-http1-v1".into());
        }
    }

    fn start_http(
        &mut self,
        settings: &NodeSettings,
        deployments: &Arc<DirectoryDeploymentRepository>,
    ) -> Result<(), PlatformError> {
        if let Some(http) = &settings.http {
            self.http = Some(super::http::HttpOwner::start(
                http.clone(),
                super::http::HttpServices {
                    manager: self.manager.clone(),
                    deployments: deployments.clone(),
                    cleanup: self
                        .cleanup
                        .as_ref()
                        .expect("owned cleanup driver")
                        .handle(),
                    clock: self.clock.clone(),
                    budget: settings.admission.budget_ceiling.clone(),
                },
            )?);
        }
        Ok(())
    }

    fn compose(
        settings: &mut NodeSettings,
        catalogs: &Catalogs,
        clock: Arc<dyn ActivationClock>,
    ) -> Result<Self, PlatformError> {
        catalogs.validate_composition(settings, &clock)?;
        settings
            .node
            .attributes
            .extend(catalogs.profile.attributes());
        let sink = Arc::new(StructuredLocalSink::new(settings.local_sink)?);
        let (telemetry, telemetry_runtime) =
            TelemetryRuntime::spawn(settings.telemetry, sink.clone())?;
        let observer = Arc::new(SharedActivationObserver::new(
            telemetry.clone(),
            settings.observer.clone(),
        )?);
        let host_services = WasmtimeHostServices {
            capabilities: catalogs.capabilities.clone(),
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
        let quotas = LocalQuotaProvider::with_profile(
            settings.admission.clone(),
            settings.budget_profile,
            settings.delegation_limits,
        )?;
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
                canary: catalogs
                    .rollouts
                    .as_ref()
                    .and_then(|owner| owner.handle().canary_capture()),
                clock: Arc::clone(&clock),
                observer: Some(observer.clone()),
                ..LocalActivationServices::default()
            },
        )?;
        install_local_services(settings, catalogs, &manager)?;
        Ok(Self {
            transport: None,
            http: None,
            audit: None,
            rollouts: None,
            policies: None,
            providers: None,
            supply_chain: super::SupplyChainLifetime(catalogs.supply_chain.clone()),
            capabilities: super::CapabilityLifetime(catalogs.capabilities.clone()),
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

fn install_local_services(
    settings: &NodeSettings,
    catalogs: &Catalogs,
    manager: &LocalActivationManager,
) -> Result<(), PlatformError> {
    if settings.budget_profile == latent_core::BudgetProfile::Phase3 {
        if let Some(capabilities) = &catalogs.capabilities {
            capabilities.install_local_services(
                manager.local_service_invoker(settings.admission.budget_ceiling.clone())?,
            )?;
        }
    }
    Ok(())
}

fn factory(
    settings: &mut NodeSettings,
    catalogs: &Catalogs,
    services: WasmtimeHostServices,
) -> Result<WasmtimeComponentEngineFactory, PlatformError> {
    // Consume the secret-bearing settings once. Configured isolation never
    // falls back to the ordinary compiler when cache or sandbox setup fails.
    match settings.isolated_aot.take() {
        Some(mut aot) => {
            aot.audit = catalogs
                .audit
                .as_ref()
                .map(super::audit::AuditRuntime::handle);
            WasmtimeComponentEngineFactory::with_catalog_and_aot(
                settings.wasmtime.clone(),
                services,
                Arc::clone(&catalogs.artifacts),
                aot,
            )
        }
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
