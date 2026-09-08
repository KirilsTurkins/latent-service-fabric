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
    InvocationServiceAdapter, InvocationServiceServices, LocalInvocationRuntime,
    LocalPrincipalPolicy,
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

pub(super) struct Catalogs {
    pub(super) artifacts: Arc<DirectoryArtifactRepository>,
    pub(super) deployments: Arc<DirectoryDeploymentRepository>,
}

impl Catalogs {
    pub(super) async fn open(settings: &NodeSettings) -> Result<Self, PlatformError> {
        let artifacts = Arc::new(DirectoryArtifactRepository::open(
            settings.data_directory.join("releases"),
            settings.artifacts,
        )?);
        let deployments = Arc::new(
            DirectoryDeploymentRepository::open(
                settings.data_directory.join("deployments"),
                artifacts.clone(),
                settings.deployments,
            )
            .await?,
        );
        Ok(Self {
            artifacts,
            deployments,
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
        let catalogs = Catalogs::open(&settings).await?;
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
        let mut node = Self::compose(&settings, &catalogs)?;
        let invocation = InvocationServiceAdapter::with_services(
            Arc::new(LocalInvocationRuntime::with_limits(
                node.manager.clone(),
                settings.invocation.clone(),
            )?),
            settings.invocation.clone(),
            InvocationServiceServices {
                clock: Arc::clone(&node.clock),
                ..InvocationServiceServices::default()
            },
        )?;
        let management = ManagementServiceAdapter::new(
            ManagementServices {
                artifacts: catalogs.artifacts,
                deployments: catalogs.deployments.clone(),
                routes: catalogs.deployments.clone(),
                inventory: node.inventory.clone(),
                principals: Arc::new(LocalPrincipalPolicy),
                authorization: Arc::new(LocalManagementPolicy),
                clock: Arc::clone(&node.clock),
            },
            settings.management.clone(),
        )?;
        node.sampler = Some(load::LoadSampler::start(
            Arc::clone(&node.load),
            settings.load_sample_interval,
            &control_runtime,
        ));
        let transport = transport::Transport::start(
            settings.transport.clone(),
            invocation,
            management,
            Arc::clone(&node.clock),
            control_runtime,
        )
        .await?;
        let topology = Arc::new(observations::TopologySource::new(
            &settings,
            node.backend.clone(),
            node.scheduler.clone(),
            transport.handle(),
            threads.invocation,
            threads.control,
        ));
        let mut descriptor = settings.node.clone();
        descriptor.endpoint = format!("http://{}", transport.local_addr());
        node.inventory
            .install(Arc::new(StandaloneInventoryReporter::new(
                settings.inventory.clone(),
                descriptor,
                StandaloneInventorySources {
                    scheduler: node.scheduler.clone(),
                    routes: catalogs.deployments,
                    quotas: node.quotas.clone(),
                    load: node.load.clone(),
                    cache: Arc::new(observations::CacheSource::new(node.backend.clone())),
                    topology,
                    clock: Arc::clone(&node.clock),
                },
            )?))?;
        node.load.start_accepting();
        transport.handle().start_accepting()?;
        node.transport = Some(transport);
        Ok(node)
    }

    fn compose(settings: &NodeSettings, catalogs: &Catalogs) -> Result<Self, PlatformError> {
        let clock: Arc<dyn ActivationClock> = Arc::new(SystemActivationClock);
        let sink = Arc::new(StructuredLocalSink::new(settings.local_sink)?);
        let (telemetry, telemetry_runtime) =
            TelemetryRuntime::spawn(settings.telemetry, sink.clone())?;
        let observer = Arc::new(SharedActivationObserver::new(
            telemetry.clone(),
            settings.observer.clone(),
        )?);
        let factory = WasmtimeComponentEngineFactory::with_host_services(
            settings.wasmtime.clone(),
            WasmtimeHostServices {
                clock: Arc::clone(&clock),
                log_sink: Some(Arc::new(TelemetryLogSink::new(
                    observer.clone(),
                    Arc::clone(&clock),
                ))),
            },
        )?;
        let backend = Arc::new(factory.create_backend_instance());
        let quotas = LocalQuotaProvider::new(settings.admission.clone())?;
        let scheduler = Arc::new(LocalScheduler::new(
            settings.scheduler.clone(),
            quotas.clone(),
        )?);
        let load = Arc::new(load::HostLoad::default());
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
        })
    }
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
