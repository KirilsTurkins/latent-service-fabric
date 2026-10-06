use super::*;
use crate::invocation::{
    ActivationCleanupOwner, InvocationLimits, LocalPrincipalPolicy, SystemInvocationTraceSource,
};
use crate::management::{LocalManagementPolicy, ManagementLimits};
use crate::phase4::{Phase4ServiceAdapter, Phase4Services};
use latent_admission::{
    LocalAdmissionController, LocalQuotaProvider, NodeLoadSnapshot, NodeLoadSource,
};
use latent_artifacts::{
    ArtifactRepository, DirectoryArtifactRepository, DirectoryArtifactRepositoryConfig,
};
use latent_control_store::{
    DeploymentStore, DirectoryDeploymentRepository, DirectoryDeploymentRepositoryConfig,
};
use latent_core::{BudgetProfile, NodeId, SystemActivationClock, TenantId};
use latent_effects::authority::{EffectAuthorityOwner, EffectTime};
use latent_effects::runtime::{DispatcherConfig, DispatcherOwner, EffectTimeSource};
use latent_node::transaction_runtime::{TransactionAdmissionOwners, TransactionInstallation};
use latent_node::{
    LocalActivationDependencies, LocalActivationManager, LocalActivationManagerConfig,
};
use latent_policy::capability::{PolicyStore, PolicyStoreLimits};
use latent_routing::ActivationCatalogSource;
use latent_scheduler::{CellClass, LocalScheduler, LocalSchedulerConfig};
use latent_state::namespace::{
    catalog::{NamespaceCatalog, NamespaceMutation, NamespaceOperationContext},
    NamespaceQuota,
};
use latent_state::protected_store::{ProtectedStoreConfig, ProtectedStoreOwner};
use latent_state::store_io::StoreIoKind;
use latent_wasmtime::{WasmtimeComponentEngineFactory, WasmtimeConfig, WasmtimeHostServices};
use std::{
    collections::BTreeMap,
    fs,
    os::unix::fs::PermissionsExt,
    path::PathBuf,
    sync::atomic::{AtomicU64, Ordering},
};

#[path = "../../../../../latent-node/tests/activation_lifecycle/model.rs"]
#[allow(dead_code)]
mod admission_model;

struct Load;
impl NodeLoadSource for Load {
    fn snapshot(&self) -> Result<NodeLoadSnapshot, PlatformError> {
        Ok(NodeLoadSnapshot {
            accepting: true,
            cpu_pressure_milli: 0,
            memory_pressure_milli: 0,
            queue_delay_millis: 0,
            observed_at: Instant::now(),
        })
    }
}
pub(super) struct Clock(pub AtomicU64);
impl EffectTimeSource for Clock {
    fn observe(&self) -> EffectTime {
        EffectTime {
            unix_millis: self.0.load(Ordering::SeqCst),
            continuity_proven: true,
        }
    }
}
struct Management;
impl Phase4Runtime for Management {
    fn execute(
        &self,
        _call: Phase4Call,
    ) -> BoxFuture<'_, Result<OwnedPhase4Response, PlatformError>> {
        Box::pin(async { Err(error(PlatformErrorCode::PermissionDenied)) })
    }
}

pub(super) struct Fixture {
    pub adapter: Option<Phase4ServiceAdapter>,
    pub backend: Arc<backend::Backend>,
    pub store: Arc<ProtectedStoreOwner>,
    pub policy: Arc<PolicyStore>,
    pub clock: Arc<Clock>,
    pub quotas: LocalQuotaProvider,
    pub manager: LocalActivationManager,
    catalog: Arc<DirectoryArtifactRepository>,
    routes: Arc<DirectoryDeploymentRepository>,
    installation: Arc<TransactionInstallation>,
    deployment: latent_manifest::DeploymentManifest,
    native: latent_core::native_capacity::NativeCapacityOwner,
    effects: EffectAuthorityOwner,
    dispatcher: Option<DispatcherOwner>,
    cleanup: Option<ActivationCleanupOwner>,
    config: ProtectedStoreConfig,
    _factory: WasmtimeComponentEngineFactory,
    _root: tempfile::TempDir,
}
impl Fixture {
    pub async fn new(paused: bool) -> Self {
        Self::with_quota(paused, NamespaceQuota::default()).await
    }

    #[expect(
        clippy::too_many_lines,
        reason = "One real runtime composition captures each independent owner before admission"
    )]
    pub async fn with_quota(paused: bool, quota: NamespaceQuota) -> Self {
        let base = std::env::var_os("LATENT_STATE_TEST_ROOT")
            .map_or_else(std::env::temp_dir, PathBuf::from);
        let root = tempfile::tempdir_in(base).unwrap();
        fs::set_permissions(root.path(), fs::Permissions::from_mode(0o700)).unwrap();
        let manifest_profile = latent_manifest::ManifestValidationProfile::phase4(
            BudgetProfile::Phase4,
            latent_core::PHASE4_HOST_ABI_V1,
            &latent_manifest::phase4_host_abi_digest(),
        )
        .unwrap();
        let catalog = Arc::new(
            DirectoryArtifactRepository::open(
                root.path().join("artifacts"),
                DirectoryArtifactRepositoryConfig {
                    manifest_profile,
                    ..Default::default()
                },
            )
            .unwrap(),
        );
        let (publication, metadata, deployment, declaration) = publication::publish(&catalog).await;
        let effects = EffectAuthorityOwner::new(128, 16, 100).unwrap();
        let policy = Arc::new(
            PolicyStore::open(
                &root.path().join("policy"),
                PolicyStoreLimits::default(),
                catalog.lifecycle_authority(),
            )
            .unwrap(),
        );
        let (state, intents) = policy::install(&policy, &publication, &effects);
        let mut config = ProtectedStoreConfig::bounded_linux(root.path().join("state"));
        fs::create_dir(&config.root).unwrap();
        fs::set_permissions(&config.root, fs::Permissions::from_mode(0o700)).unwrap();
        config.create_if_missing = true;
        let store = Arc::new(
            ProtectedStoreOwner::start(config.clone())
                .unwrap()
                .await
                .unwrap(),
        );
        let native =
            latent_core::native_capacity::NativeCapacityOwner::new(Default::default()).unwrap();
        store.bind_native_capacity(&native).unwrap();
        let schema = declaration.state_schema.clone();
        store
            .with_store(StoreIoKind::Write, 8192, move |store| {
                let plan = NamespaceCatalog::new()
                    .prepare(
                        store,
                        NamespaceOperationContext {
                            tenant: TenantId(publication::TENANT.into()),
                            actor: "operator".into(),
                            operation_id: "create".into(),
                        },
                        &NamespaceMutation::Create {
                            id: latent_core::StateNamespaceId(publication::NAMESPACE.into()),
                            state_schema: schema,
                            quota,
                        },
                        0,
                    )
                    .unwrap();
                store.apply(plan.batch)
            })
            .unwrap()
            .await
            .unwrap()
            .unwrap();
        let installation = Arc::new(
            TransactionInstallation::new(
                metadata,
                declaration,
                &deployment,
                publication.clone(),
                state,
                Some(intents),
                latent_capabilities::namespace::RecoverySelection::OriginalCaller,
                "visibility-v1".into(),
                latent_commit::atomic::ResultPolicy {
                    replay: latent_commit::atomic::ReplayPolicy::Full,
                    maximum_result_bytes: 4096,
                    result_millis: 10_000,
                    identity_millis: 20_000,
                    maximum_attempts: 3,
                },
            )
            .unwrap(),
        );
        let runtime_config = WasmtimeConfig {
            transactional_state: true,
            maximum_memory_bytes: budget().memory_bytes,
            maximum_fuel: budget().cpu_fuel,
            prepared_cache_maximum_entries: 2,
            epoch_tick_interval_millis: 1,
            ..Default::default()
        };
        let routes = Arc::new(
            DirectoryDeploymentRepository::open_with_catalog(
                root.path().join("routes"),
                catalog.clone(),
                DirectoryDeploymentRepositoryConfig::default(),
                catalog.lifecycle_authority(),
                Arc::new(runtime_config.detected_runtime_profile().unwrap()),
            )
            .await
            .unwrap(),
        );
        routes.apply(deployment.clone()).await.unwrap();
        let factory = WasmtimeComponentEngineFactory::with_catalog(
            runtime_config,
            WasmtimeHostServices {
                clock: Arc::new(SystemActivationClock),
                capabilities: None,
                currentness_read_wait: Some(Arc::new(latent_node::CurrentnessReadTimer)),
                log_sink: None,
            },
            catalog.lifecycle_authority(),
        )
        .unwrap();
        let real = Arc::new(factory.create_backend_instance());
        use latent_executor::ExecutionBackend;
        let mut key = real.preparation_key(publication.release()).unwrap();
        key.publication = Some(publication.publication().clone());
        let prepared = tokio::time::timeout(
            Duration::from_secs(600),
            real.prepare_ready_from_repository(catalog.clone(), key),
        )
        .await
        .unwrap()
        .unwrap();
        drop(real.materialize_ready(prepared).unwrap());
        assert_eq!(
            real.resource_snapshot().stores_created,
            0,
            "preparation is never counted as guest execution"
        );
        let imports = Arc::new(backend::Imports::default());
        imports.pause_read.store(paused, Ordering::SeqCst);
        let backend = Arc::new(backend::Backend { real, imports });
        let mut node_policy = admission_model::node_policy(1);
        node_policy.budget_ceiling = budget();
        node_policy.architecture = std::env::consts::ARCH.into();
        node_policy.limits.maximum_reserved_cpu_fuel = budget().cpu_fuel * 8;
        node_policy.limits.maximum_reserved_memory_bytes = budget().memory_bytes * 8;
        let mut tenant = node_policy
            .tenants
            .remove(&TenantId(admission_model::TENANT.into()))
            .unwrap();
        tenant.limits = node_policy.limits;
        node_policy.tenants = BTreeMap::from([(TenantId(publication::TENANT.into()), tenant)]);
        for trust in node_policy.trust_classes.values_mut() {
            trust.limits = node_policy.limits;
        }
        for cell in node_policy.cell_classes.values_mut() {
            cell.maximum_memory_bytes = budget().memory_bytes;
        }
        let quotas = LocalQuotaProvider::with_profile(
            node_policy,
            BudgetProfile::Phase4,
            Default::default(),
        )
        .unwrap();
        let manager = manager(&routes, &catalog, &backend, &quotas);
        let clock = Arc::new(Clock(AtomicU64::new(1000)));
        let mut fixture = Self {
            adapter: None,
            backend,
            store,
            policy,
            clock,
            quotas,
            manager,
            catalog,
            routes,
            installation,
            deployment,
            native,
            effects,
            dispatcher: None,
            cleanup: None,
            config,
            _factory: factory,
            _root: root,
        };
        fixture.wire().await;
        fixture
    }
    async fn wire(&mut self) {
        let dispatcher = DispatcherOwner::start(
            DispatcherConfig::default(),
            Arc::clone(&self.store),
            self.effects.clone(),
            Vec::new(),
            self.clock.clone(),
            None,
        )
        .await
        .unwrap();
        dispatcher.bind_native_capacity(&self.native).unwrap();
        let owners = Arc::new(
            TransactionAdmissionOwners::new(
                Arc::clone(&self.store),
                Arc::new(NamespaceCatalog::new()),
                Arc::clone(&self.policy),
                dispatcher.command_admission_source(),
            )
            .unwrap(),
        );
        let cleanup = ActivationCleanupOwner::start(
            8,
            Duration::from_millis(100),
            &tokio::runtime::Handle::current(),
        )
        .unwrap();
        let limits = InvocationLimits {
            budget_profile: BudgetProfile::Phase4,
            max_state_read_bytes: budget().state_read_bytes,
            max_state_write_bytes: budget().state_write_bytes,
            max_effect_count: budget().effect_count,
            ..Default::default()
        };
        let runtime = LocalTransactionRuntime::new(
            self.manager.clone(),
            cleanup.handle(),
            owners,
            vec![Arc::clone(&self.installation)],
            Arc::new(Management),
            limits.clone(),
            LocalTransactionServices {
                clock: Arc::new(SystemActivationClock),
                principals: Arc::new(LocalPrincipalPolicy),
                traces: Arc::new(SystemInvocationTraceSource::default()),
            },
        )
        .unwrap();
        self.adapter = Some(
            Phase4ServiceAdapter::with_services(
                Arc::new(runtime),
                ManagementLimits {
                    auth: limits,
                    ..Default::default()
                },
                Phase4Services {
                    principals: Arc::new(LocalPrincipalPolicy),
                    management: Arc::new(LocalManagementPolicy),
                    clock: Arc::new(SystemActivationClock),
                },
            )
            .unwrap(),
        );
        self.cleanup = Some(cleanup);
        self.dispatcher = Some(dispatcher);
    }
    pub fn adapter(&self) -> Phase4ServiceAdapter {
        self.adapter.as_ref().unwrap().clone()
    }
    pub fn executions(&self) -> u64 {
        self.backend.imports.commands.load(Ordering::SeqCst)
    }
    pub async fn drop_duplicate_during_native_lookup(&self) {
        use std::{
            future::{poll_fn, Future},
            sync::{Condvar, Mutex},
            task::Poll,
        };
        let gate = Arc::new((Mutex::new(false), Condvar::new()));
        let retained = Arc::clone(&gate);
        let (entered, entry) = tokio::sync::oneshot::channel();
        let worker = self
            .store
            .with_store(StoreIoKind::Read, 64, move |_store| {
                entered.send(()).unwrap();
                let lock = retained.0.lock().unwrap();
                let (lock, timeout) = retained
                    .1
                    .wait_timeout_while(lock, Duration::from_secs(5), |released| !*released)
                    .unwrap();
                assert!(*lock && !timeout.timed_out());
                Ok(())
            })
            .unwrap();
        tokio::time::timeout(Duration::from_secs(5), entry)
            .await
            .unwrap()
            .unwrap();
        let adapter = self.adapter();
        let mut duplicate =
            Box::pin(adapter.invoke_command(context("alice").request(command("same", 1, false))));
        poll_fn(|cx| {
            assert!(
                duplicate.as_mut().poll(cx).is_pending(),
                "the real native lookup remains blocked"
            );
            Poll::Ready(())
        })
        .await;
        drop(duplicate);
        *gate.0.lock().unwrap() = true;
        gate.1.notify_one();
        worker.await.unwrap().unwrap();
        tokio::time::timeout(Duration::from_secs(5), async {
            while self.quotas.usage().unwrap().active_activations != 1 {
                tokio::task::yield_now().await;
            }
        })
        .await
        .unwrap();
        assert_eq!(
            self.executions(),
            1,
            "a dropped duplicate never enters guest acquisition"
        );
    }
    pub async fn rows(&self, family: Family) -> usize {
        self.store
            .with_store(StoreIoKind::Read, 128 * 1024, move |store| {
                Ok(store.snapshot()?.scan(family, b"", 256, 128 * 1024)?.len())
            })
            .unwrap()
            .await
            .unwrap()
            .unwrap()
    }
    pub async fn restart(&mut self) {
        self.retire().await;
        self.store = Arc::new(
            ProtectedStoreOwner::start(self.config.clone())
                .unwrap()
                .await
                .unwrap(),
        );
        self.store.bind_native_capacity(&self.native).unwrap();
        self.manager = manager(&self.routes, &self.catalog, &self.backend, &self.quotas);
        self.wire().await;
    }
    pub async fn deploy_compatible_revision(&mut self) -> latent_routing::ResolvedRevision {
        // A transport ceiling is mutable and changes the actual deployment
        // revision while preserving the command's immutable business inputs.
        self.deployment.resources.cpu_fuel -= 1;
        self.routes.apply(self.deployment.clone()).await.unwrap();
        use latent_routing::RouteResolver;
        let resolved = self
            .routes
            .pin()
            .unwrap()
            .resolve(
                &latent_routing::InvocationTarget {
                    tenant: TenantId(publication::TENANT.into()),
                    service: latent_core::ServiceId(publication::SERVICE.into()),
                    contract: latent_core::ContractId(publication::CONTRACT.into()),
                    function: latent_core::FunctionId("update".into()),
                    route: None,
                },
                Some("rollout-probe"),
            )
            .unwrap();
        self.restart().await;
        resolved
    }
    async fn retire(&mut self) {
        drop(self.adapter.take());
        self.cleanup
            .take()
            .unwrap()
            .shutdown((Instant::now() + Duration::from_secs(10)).into())
            .await
            .unwrap();
        assert_eq!(self.manager.cancellation_snapshot().active_registrations, 0);
        assert_eq!(self.quotas.usage().unwrap().active_activations, 0);
        let report = self
            .dispatcher
            .take()
            .unwrap()
            .shutdown(Instant::now() + Duration::from_secs(10))
            .await
            .unwrap();
        assert!(report.clean, "{report:?}");
        let deadline = Instant::now() + Duration::from_secs(10);
        let report = self
            .store
            .drain_async(deadline, tokio::time::sleep_until(deadline.into()))
            .unwrap()
            .await;
        assert!(
            report.clean && report.snapshot.physically_retired(),
            "{report:?}"
        );
        self.store.reap_retired_threads().unwrap();
    }
    pub async fn shutdown(mut self) {
        self.retire().await;
        let runtime = self.backend.real.resource_snapshot();
        assert_eq!(
            runtime.live_stores
                + runtime.live_host_states
                + runtime.live_component_instances
                + runtime.active_invocations,
            0
        );
        assert_eq!(
            runtime.stores_created,
            self.executions() + self.backend.imports.queries.load(Ordering::SeqCst)
        );
        eprintln!("actual-guest command-executions={} query-executions={} stores-created={} live-stores={}",self.executions(),self.backend.imports.queries.load(Ordering::SeqCst),runtime.stores_created,runtime.live_stores);
    }
}

fn manager(
    routes: &Arc<DirectoryDeploymentRepository>,
    catalog: &Arc<DirectoryArtifactRepository>,
    backend: &Arc<backend::Backend>,
    quotas: &LocalQuotaProvider,
) -> LocalActivationManager {
    let admission = LocalAdmissionController::new(
        Arc::new(routes.pin().unwrap()),
        quotas.clone(),
        Arc::new(Load),
    );
    let scheduler = Arc::new(
        LocalScheduler::new(
            LocalSchedulerConfig {
                node: NodeId("compiled-command-node".into()),
                queue_capacity_per_class: BTreeMap::from([(CellClass::Tiny, 8)]),
                starvation_after: Duration::from_secs(1),
            },
            quotas.clone(),
        )
        .unwrap(),
    );
    LocalActivationManager::new(
        LocalActivationManagerConfig::default(),
        LocalActivationDependencies {
            catalog: routes.clone(),
            admission,
            scheduler,
            artifacts: catalog.clone(),
            backend: backend.clone(),
        },
    )
    .unwrap()
}
