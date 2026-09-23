use super::{packages, provider};
use latent_activation::{ActivationIdSource, ActivationRequest};
use latent_admission::{
    LocalAdmissionController, LocalQuotaProvider, NodeLoadSnapshot, NodeLoadState,
};
use latent_artifacts::*;
use latent_capabilities::broker::pools::ProviderPools;
use latent_control_store::{DeploymentStore, DirectoryDeploymentRepository};
use latent_core::{
    ActivationId, BudgetProfile, PlatformError, PrincipalKind, PublicationId,
    SystemActivationClock, TenantId,
};
use latent_manifest::{DeploymentManifest, JsonManifestCodec, ManifestCodec};
use latent_nats::triggers::{NatsTriggers, TriggerConfig};
use latent_node::{LocalActivationDependencies, LocalActivationManager, LocalActivationServices};
use latent_scheduler::{CellClass, LocalScheduler, LocalSchedulerConfig};
use latent_wasmtime::{
    WasmtimeBackend, WasmtimeComponentEngineFactory, WasmtimeConfig, WasmtimeHostServices,
};
use serde_json::json;
use std::{
    collections::BTreeMap,
    sync::{
        atomic::{AtomicU64, Ordering},
        Arc,
    },
    time::{Duration, Instant},
};
#[path = "../../../latent-node/tests/activation_lifecycle/model.rs"]
#[allow(dead_code)]
mod admission_fixture;
#[path = "../../../latent-control-store/tests/admission/support.rs"]
mod authority;
struct Ids(AtomicU64);
impl ActivationIdSource for Ids {
    fn next_id(&self) -> Result<ActivationId, PlatformError> {
        Ok(ActivationId(format!(
            "fixture-{}",
            self.0.fetch_add(1, Ordering::Relaxed)
        )))
    }
}
pub struct Fixture {
    pub triggers: NatsTriggers,
    pub manager: LocalActivationManager,
    pub backend: Arc<WasmtimeBackend>,
    _factory: WasmtimeComponentEngineFactory,
    pub store: Arc<DirectoryDeploymentRepository>,
    pub catalog: Arc<DirectoryArtifactRepository>,
    pub quotas: LocalQuotaProvider,
    pub pools: Arc<ProviderPools>,
    secrets: latent_secrets::LocalSecretStore,
    pub targets: Vec<DeploymentManifest>,
    pub directory: tempfile::TempDir,
}
impl Fixture {
    pub async fn restart(self) -> Self {
        self.close().await;
        let bytes = self.triggers.config().to_json().unwrap();
        std::fs::write(self.directory.path().join("triggers.json"), &bytes).unwrap();
        let Self {
            directory,
            triggers,
            manager,
            backend,
            _factory: factory,
            store,
            catalog,
            quotas,
            pools,
            secrets,
            targets,
        } = self;
        drop((
            triggers, manager, backend, factory, store, catalog, quotas, pools, secrets, targets,
        ));
        let retained = std::fs::read(directory.path().join("triggers.json")).unwrap();
        Self::open(directory, TriggerConfig::from_json(&retained).unwrap()).await
    }
    pub async fn new(config: TriggerConfig) -> Self {
        Self::open(tempfile::tempdir().unwrap(), config).await
    }
    #[expect(
        clippy::too_many_lines,
        reason = "one explicit integration composition with a real publication catalog, route store and scheduler"
    )]
    pub async fn open(directory: tempfile::TempDir, trigger_config: TriggerConfig) -> Self {
        let package = packages::callee(42);
        let catalog = Arc::new(
            DirectoryArtifactRepository::open_enforced(
                directory.path().join("artifacts"),
                DirectoryArtifactRepositoryConfig::default(),
                AdmissionStorageLimits::default(),
                authority::Authority::new(packages::artifact(&package)),
            )
            .unwrap(),
        );
        let mut publications = vec![];
        for tenant in ["tenant-a", "tenant-b"] {
            let receipt = catalog
                .admit_package(
                    &TenantId(tenant.into()),
                    PackageAdmissionUpload {
                        manifest: package.manifest_bytes().to_vec(),
                        configuration: package.config_bytes().to_vec(),
                        layers: package
                            .layers()
                            .iter()
                            .map(|blob| (blob.path().into(), blob.bytes().to_vec()))
                            .collect(),
                        signatures: vec![],
                        provenance: vec![],
                        sboms: vec![],
                    },
                    &mut |_| Ok(()),
                )
                .await
                .unwrap();
            publications.push(receipt.publication.unwrap());
        }
        let config = WasmtimeConfig {
            maximum_memory_bytes: packages::budget().memory_bytes,
            maximum_fuel: packages::budget().cpu_fuel,
            prepared_cache_maximum_entries: 4,
            epoch_tick_interval_millis: 1,
            ..Default::default()
        };
        let store = Arc::new(
            DirectoryDeploymentRepository::open_with_catalog(
                directory.path().join("routes"),
                catalog.clone(),
                latent_control_store::DirectoryDeploymentRepositoryConfig::default(),
                catalog.lifecycle_authority(),
                Arc::new(config.detected_runtime_profile().unwrap()),
            )
            .await
            .unwrap(),
        );
        let mut targets = vec![];
        for (tenant, publication) in ["tenant-a", "tenant-b"].into_iter().zip(publications) {
            let manifest = deployment("callee", tenant, &package, &publication);
            store.apply(manifest.clone()).await.unwrap();
            targets.push(manifest);
        }
        let factory = WasmtimeComponentEngineFactory::with_catalog(
            config,
            WasmtimeHostServices {
                clock: Arc::new(SystemActivationClock),
                log_sink: None,
                capabilities: None,
            },
            catalog.lifecycle_authority(),
        )
        .unwrap();
        let backend = Arc::new(factory.create_backend_instance());
        let quotas = LocalQuotaProvider::with_profile(
            node_policy(),
            BudgetProfile::Phase3,
            latent_core::DelegationLimits::default(),
        )
        .unwrap();
        let scheduler = Arc::new(
            LocalScheduler::new(
                LocalSchedulerConfig {
                    node: latent_core::NodeId("trigger-node".into()),
                    queue_capacity_per_class: BTreeMap::from([(CellClass::Tiny, 8)]),
                    starvation_after: Duration::from_secs(1),
                },
                quotas.clone(),
            )
            .unwrap(),
        );
        let load = Arc::new(
            NodeLoadState::new(NodeLoadSnapshot {
                accepting: true,
                cpu_pressure_milli: 0,
                memory_pressure_milli: 0,
                queue_delay_millis: 0,
                observed_at: Instant::now(),
            })
            .unwrap(),
        );
        let admission =
            LocalAdmissionController::new(Arc::new(store.pin().unwrap()), quotas.clone(), load);
        let manager = LocalActivationManager::with_services(
            Default::default(),
            LocalActivationDependencies {
                catalog: store.clone(),
                admission,
                scheduler,
                artifacts: catalog.clone(),
                backend: backend.clone(),
            },
            LocalActivationServices {
                clock: Arc::new(SystemActivationClock),
                ids: Arc::new(Ids(AtomicU64::new(0))),
                observer: None,
                canary: None,
            },
        )
        .unwrap();
        let (triggers, pools, secrets) =
            provider::install(directory.path(), &catalog, trigger_config).await;
        Self {
            triggers,
            manager,
            backend,
            _factory: factory,
            store,
            catalog,
            quotas,
            pools,
            secrets,
            targets,
            directory,
        }
    }
    pub fn request(&self, id: &str) -> ActivationRequest {
        let mut request = admission_fixture::request(id);
        request.target.service = latent_core::ServiceId("callee".into());
        request.target.contract = latent_core::ContractId(super::component::CALLEE.into());
        request.target.function = latent_core::FunctionId("answer".into());
        request.principal.kind = PrincipalKind::Trigger;
        request.principal.subject = "event-ingress".into();
        request.budget = packages::budget();
        request.input = vec![];
        request.input_media_type = "application/vnd.latent.wit-values.v1+json".into();
        request
    }
    pub async fn idle(&self) {
        tokio::time::timeout(Duration::from_secs(2), async {
            loop {
                if self.quotas.usage().unwrap().active_activations == 0
                    && self.backend.active_instance_reservations() == 0
                    && self.manager.cancellation_snapshot().active_registrations == 0
                {
                    break;
                }
                tokio::task::yield_now().await;
            }
        })
        .await
        .unwrap();
        assert_eq!(self.backend.resource_snapshot().live_stores, 0);
        assert_eq!(self.pools.snapshot().unwrap().running_requests, 0);
    }
    pub async fn close(&self) {
        self.idle().await;
        self.triggers.close_idle().unwrap();
        self.secrets.close();
        assert!(self
            .pools
            .shutdown(Instant::now() + Duration::from_secs(2))
            .await
            .unwrap()
            .is_clean());
    }
    pub fn revoke(&self, index: usize) {
        let target = &self.targets[index];
        let scope = LifecycleScope::Tenant(target.metadata.tenant.clone().unwrap());
        self.catalog
            .change_publication_lifecycle(
                ReleaseMutationContext {
                    scope: scope.clone(),
                    actor: ReleaseActor {
                        subject: "fixture".into(),
                        kind: ReleaseActorKind::Host,
                    },
                    operation: Some(ReleaseOperationPrecondition {
                        operation_id: "revoke".into(),
                        expected_generation: 1,
                    }),
                },
                &PublicationRef {
                    id: target.publication.clone().unwrap(),
                    scope,
                },
                ReleaseLifecycleAction::Revoke,
                ReleaseLifecycleReason::OperatorRevocation,
                &mut |_| Ok(()),
            )
            .unwrap();
    }
}
fn deployment(
    name: &str,
    tenant: &str,
    package: &latent_packaging::PackageBundle,
    publication: &PublicationId,
) -> DeploymentManifest {
    let mut document: serde_json::Value = serde_json::from_slice(include_bytes!(
        "../../../../examples/echo-contract/deployment.json"
    ))
    .unwrap();
    document["metadata"] = json!({"name":format!("{name}-{tenant}"),"tenant":tenant});
    document["spec"]["service"] = json!(name);
    document["spec"]["release"] = json!(packages::release(package).0);
    document["spec"]["publication"] = json!(publication.as_str());
    document["spec"]["resources"] = packages::budget_json();
    document["spec"]["placement"] =
        json!({"trustClass":"sandbox","architectures":[std::env::consts::ARCH]});
    document["spec"]["grants"] = json!([]);
    JsonManifestCodec::default()
        .decode_deployment(&serde_json::to_vec(&document).unwrap())
        .unwrap()
}
fn node_policy() -> latent_admission::NodeAdmissionPolicy {
    let mut policy = admission_fixture::node_policy(2);
    policy.budget_ceiling = packages::budget();
    policy.architecture = std::env::consts::ARCH.into();
    policy.limits.maximum_reserved_cpu_fuel = packages::budget().cpu_fuel * 8;
    policy.limits.maximum_reserved_memory_bytes = packages::budget().memory_bytes * 8;
    for tenant in policy.tenants.values_mut() {
        tenant.limits = policy.limits;
        tenant.allowed_subjects = ["event-ingress".into()].into();
        tenant.allowed_principal_kinds = vec![PrincipalKind::Trigger];
    }
    for trust in policy.trust_classes.values_mut() {
        trust.limits = policy.limits;
    }
    for cell in policy.cell_classes.values_mut() {
        cell.maximum_memory_bytes = packages::budget().memory_bytes;
    }
    policy
}
