#![allow(
    clippy::similar_names,
    reason = "caller and callee name the two component roles"
)]
use super::{component, packages};
use latent_activation::{ActivationIdSource, ActivationRequest};
use latent_admission::{
    LocalAdmissionController, LocalQuotaProvider, NodeLoadSnapshot, NodeLoadSource,
};
use latent_artifacts::{ArtifactRepository, DirectoryArtifactRepository, PackageAdmissionUpload};
use latent_capabilities::broker::*;
use latent_control_store::{
    bindings::{BindingDefinition, ConfiguredBindingProvider},
    DeploymentStore, DirectoryDeploymentRepository,
};
use latent_core::{
    ActivationClock, ActivationId, BudgetProfile, ContractId, DeploymentId, FunctionId,
    PlatformError, PolicyId, PrincipalKind, PublicationId, ServiceId, SystemActivationClock,
    TenantId,
};
use latent_manifest::{
    BindingMode, CapabilityGrantSpec, DeploymentManifest, JsonManifestCodec, ManifestCodec,
};
use latent_node::{LocalActivationDependencies, LocalActivationManager, LocalActivationServices};
use latent_policy::capability::{MutationRequest, PolicyStore, RecordKind};
use latent_scheduler::{CellClass, LocalScheduler, LocalSchedulerConfig};
use latent_wasmtime::{
    WasmtimeBackend, WasmtimeComponentEngineFactory, WasmtimeConfig, WasmtimeHostServices,
};
use serde_json::json;
use std::{
    collections::BTreeMap,
    sync::{
        atomic::{AtomicU64, Ordering},
        Arc, Mutex,
    },
    time::{Duration, Instant},
};
#[path = "../../../latent-node/tests/activation_lifecycle/model.rs"]
#[allow(dead_code)]
mod admission_fixture;
#[path = "../../../latent-control-store/tests/admission/support.rs"]
mod authority;
#[path = "diagnostics.rs"]
mod diagnostics;
#[path = "../guest_sdk/runtime.rs"]
mod guest_runtime;

pub struct Observations {
    pub starts: Mutex<Vec<latent_telemetry::ActivationObservationContext>>,
    pub terminals: Mutex<
        Vec<(
            latent_telemetry::ActivationObservationContext,
            latent_telemetry::ActivationTerminalObservation,
        )>,
    >,
    pub child_running: tokio::sync::Notify,
    pub child_failures: Arc<diagnostics::Recorder>,
}
impl latent_telemetry::ActivationObserver for Observations {
    fn on_observation(
        &self,
        context: &latent_telemetry::ActivationObservationContext,
        event: &latent_telemetry::ActivationObservation,
    ) {
        use latent_telemetry::ActivationObservationKind;
        match &event.kind {
            ActivationObservationKind::Received => {
                let mut starts = self.starts.lock().unwrap();
                assert!(starts.len() < 32);
                starts.push(context.clone());
            }
            ActivationObservationKind::Phase {
                phase: latent_core::ActivationPhase::Running,
                ..
            } if context.parent_activation_id.is_some() => self.child_running.notify_one(),
            ActivationObservationKind::Terminal(terminal) => {
                let mut terminals = self.terminals.lock().unwrap();
                assert!(terminals.len() < 32);
                terminals.push((context.clone(), terminal.clone()));
            }
            _ => (),
        }
    }
}
struct Ids(AtomicU64);
impl ActivationIdSource for Ids {
    fn next_id(&self) -> Result<ActivationId, PlatformError> {
        Ok(ActivationId(format!(
            "child-{}",
            self.0.fetch_add(1, Ordering::Relaxed) + 1
        )))
    }
}
pub struct Fixture {
    _guest_runtime: guest_runtime::Runtime,
    pub manager: LocalActivationManager,
    pub backend: Arc<WasmtimeBackend>,
    _factory: WasmtimeComponentEngineFactory,
    pub store: Arc<DirectoryDeploymentRepository>,
    pub catalog: Arc<DirectoryArtifactRepository>,
    pub quotas: LocalQuotaProvider,
    pub broker: Arc<ActivationCapabilityBroker>,
    _policies: Arc<PolicyStore>,
    _provider: ProviderRegistration,
    pub target: DeploymentManifest,
    pub observations: Arc<Observations>,
    _root: tempfile::TempDir,
}
impl Fixture {
    pub async fn new(cells: u32, foreign: bool, permit_target: bool) -> Self {
        Self::with_audit(cells, foreign, permit_target, None).await
    }
    pub async fn with_audit(
        cells: u32,
        foreign: bool,
        permit_target: bool,
        audit: Option<latent_audit::AuditHandle>,
    ) -> Self {
        Self::with_packages(cells, foreign, permit_target, audit, None).await
    }
    pub async fn with_packages(
        cells: u32,
        foreign: bool,
        permit_target: bool,
        audit: Option<latent_audit::AuditHandle>,
        provided: Option<(
            Arc<DirectoryArtifactRepository>,
            latent_packaging::PackageBundle,
            latent_packaging::PackageBundle,
        )>,
    ) -> Self {
        Self::with_packages_and_load(
            cells,
            foreign,
            permit_target,
            audit,
            provided,
            Arc::new(SyntheticFixtureLoad),
        )
        .await
    }
    pub async fn with_load_source(load: Arc<dyn NodeLoadSource>) -> Self {
        Self::with_packages_and_load(2, false, true, None, None, load).await
    }
    #[expect(
        clippy::too_many_lines,
        reason = "one explicit real catalog, broker and node ownership composition for integration tests"
    )]
    async fn with_packages_and_load(
        cells: u32,
        foreign: bool,
        permit_target: bool,
        audit: Option<latent_audit::AuditHandle>,
        provided: Option<(
            Arc<DirectoryArtifactRepository>,
            latent_packaging::PackageBundle,
            latent_packaging::PackageBundle,
        )>,
        load: Arc<dyn NodeLoadSource>,
    ) -> Self {
        let root = tempfile::tempdir().unwrap();
        let target_tenant = if foreign { "tenant-b" } else { "tenant-a" };
        let (catalog, caller, callee) = if let Some(provided) = provided {
            provided
        } else {
            let caller = packages::caller(foreign.then_some(target_tenant));
            let callee = packages::callee(42);
            let authority = authority::Authority::new_many(vec![
                packages::artifact(&caller),
                packages::artifact(&callee),
            ]);
            let catalog = Arc::new(
                DirectoryArtifactRepository::open_enforced(
                    root.path().join("artifacts"),
                    latent_artifacts::DirectoryArtifactRepositoryConfig::default(),
                    latent_artifacts::AdmissionStorageLimits::default(),
                    authority,
                )
                .unwrap(),
            );
            for (tenant, bundle) in [("tenant-a", &caller), (target_tenant, &callee)] {
                catalog
                    .admit_package(
                        &TenantId(tenant.into()),
                        PackageAdmissionUpload {
                            manifest: bundle.manifest_bytes().to_vec(),
                            configuration: bundle.config_bytes().to_vec(),
                            layers: bundle
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
            }
            (catalog, caller, callee)
        };
        let config = WasmtimeConfig {
            java_guest: guest_runtime::java(),
            fuel_async_yield_interval: guest_runtime::java().then_some(10_000),
            maximum_memory_bytes: packages::budget().memory_bytes,
            maximum_fuel: packages::budget().cpu_fuel,
            prepared_cache_maximum_entries: 4,
            epoch_tick_interval_millis: 1,
            ..Default::default()
        };
        let store = Arc::new(
            DirectoryDeploymentRepository::open_with_catalog(
                root.path().join("routes"),
                catalog.clone(),
                latent_control_store::DirectoryDeploymentRepositoryConfig::default(),
                catalog.lifecycle_authority(),
                Arc::new(config.detected_runtime_profile().unwrap()),
            )
            .await
            .unwrap(),
        );
        let caller_publication = catalog
            .execution_eligibility_selected(&packages::release(&caller), None)
            .unwrap()
            .unwrap()
            .publication()
            .clone();
        let callee_publication = catalog
            .execution_eligibility_selected(&packages::release(&callee), None)
            .unwrap()
            .unwrap()
            .publication()
            .clone();
        let mut consumer = deployment("caller", "tenant-a", &caller, &caller_publication);
        consumer.resources = catalog
            .fetch(&packages::release(&caller))
            .await
            .unwrap()
            .manifest
            .execution
            .resource_budget_ceiling;
        consumer.grants = vec![CapabilityGrantSpec::new(
            latent_core::CapabilityId(SERVICE_INVOCATION_CAPABILITY.into()),
            PolicyId("local-calls".into()),
        )];
        consumer.grants.extend(guest_runtime::grants());
        let mut target = deployment("callee", target_tenant, &callee, &callee_publication);
        target.grants = guest_runtime::grants();
        target.resources = catalog
            .fetch(&packages::release(&callee))
            .await
            .unwrap()
            .manifest
            .execution
            .resource_budget_ceiling;
        store.apply(target.clone()).await.unwrap();
        store.apply(consumer).await.unwrap();
        let policies = Arc::new(
            PolicyStore::open(
                &root.path().join("policies"),
                latent_policy::capability::PolicyStoreLimits::default(),
                catalog.lifecycle_authority(),
            )
            .unwrap(),
        );
        let digest = format!("sha256:{}", "7".repeat(64));
        let allowed_target = if permit_target {
            callee_publication.as_str()
        } else {
            caller_publication.as_str()
        };
        for (id, kind, document) in [
            (
                "local-calls",
                RecordKind::Policy,
                json!({"formatVersion":1,"tenant":"tenant-a","rules":[{
                "id":"call","effect":"allow","principals":[{"kind":"user","subject":"alice"}],"services":["caller"],
                "publications":[caller_publication.as_str()],"capability":SERVICE_INVOCATION_CAPABILITY,"operations":["call"],
                "resources":{"kind":"service","services":["callee"],"publications":[allowed_target]},
                "ceiling":{"operations":8,"inputBytes":65536,"outputBytes":65536,"wallTimeMillis":packages::budget().wall_time_limit_millis.unwrap_or(5000)},"requireAudit":audit.is_some()}]}),
            ),
            (
                "installed",
                RecordKind::ProviderBinding,
                json!({"formatVersion":1,"tenant":"tenant-a","capability":SERVICE_INVOCATION_CAPABILITY,
                "providerProfile":LOCAL_SERVICE_INVOCATION_PROFILE,"configurationDigest":digest,"configurationEpoch":1,"restriction":{"operations":[]}}),
            ),
        ] {
            let bytes = serde_json::to_vec(&document).unwrap();
            policies
                .mutate(
                    MutationRequest {
                        tenant: "tenant-a",
                        actor: "operator",
                        id,
                        kind,
                        operation_id: id,
                        expected_revision: 0,
                        document: Some(&bytes),
                    },
                    Instant::now() + Duration::from_secs(10),
                    |_| Ok(()),
                )
                .unwrap();
        }
        let clock: Arc<dyn ActivationClock> = Arc::new(SystemActivationClock);
        let broker = ActivationCapabilityBroker::new(
            catalog.lifecycle_authority(),
            policies.clone(),
            clock.clone(),
            CapabilityBrokerLimits::default(),
        )
        .unwrap();
        let broker = Arc::new(match audit {
            Some(audit) => broker.with_audit(audit, false).unwrap(),
            None => broker,
        });
        let provider = broker
            .register_provider(ProviderConfiguration {
                capability: SERVICE_INVOCATION_CAPABILITY,
                profile: LOCAL_SERVICE_INVOCATION_PROFILE,
                configuration_digest: &digest,
                configuration_epoch: 1,
                restriction_json: br#"{"operations":[]}"#,
                minimum_call_charges: &[],
            })
            .unwrap();
        let guest_runtime = guest_runtime::Runtime::scoped(
            &broker,
            &policies,
            "tenant-a",
            &[
                guest_runtime::Scope {
                    services: &["caller"],
                    publications: std::slice::from_ref(&caller_publication),
                    principal: ("user", "alice"),
                },
                // Local invocation deliberately derives a service principal;
                // the child does not inherit Alice's user authority.
                guest_runtime::Scope {
                    services: &["callee"],
                    publications: std::slice::from_ref(&callee_publication),
                    principal: ("service", "service:8:tenant-a:6:caller"),
                },
            ],
            false,
        );
        let definition = BindingDefinition { manifest: JsonManifestCodec::default().decode_binding(&serde_json::to_vec(&json!({
            "apiVersion":"latent.dev/v1alpha1","kind":"Binding","metadata":{"name":"local-call","tenant":"tenant-a"},
            "spec":{"consumer":{"service":"caller","contract":SERVICE_INVOCATION_CAPABILITY},"provider":{"service":"callee","contract":component::CALLEE,"route":"callee"},"mode":"isolated-local"}})).unwrap()).unwrap(),
            provider_binding_id: "installed".into(), allowed_modes: vec![BindingMode::IsolatedLocal], restriction_json: br#"{"operations":[]}"#.to_vec() };
        let mut definitions = vec![definition];
        definitions.extend(guest_runtime.definitions("tenant-a", &["caller", "callee"]));
        let mut providers = vec![ConfiguredBindingProvider {
            tenant: TenantId("tenant-a".into()),
            service: ServiceId("callee".into()),
            reference: provider.reference(),
            local_deployment: Some(DeploymentId("callee".into())),
        }];
        providers.extend(guest_runtime.providers("tenant-a"));
        let (generation, transaction) = store.binding_version().unwrap();
        let update = store
            .prepare_binding_update(
                generation,
                transaction,
                definitions,
                broker.clone(),
                providers,
                latent_control_store::bindings::BindingLimits::default(),
            )
            .await
            .unwrap();
        store.commit_binding_update(update).unwrap();
        let capabilities = Arc::new(ActivationCapabilityRuntime::new(
            broker.clone(),
            store.clone(),
        ));
        guest_runtime.install(&capabilities);
        let factory = WasmtimeComponentEngineFactory::with_catalog(
            config,
            WasmtimeHostServices {
                clock: clock.clone(),
                capabilities: Some(capabilities.clone()),
                currentness_read_wait: Some(Arc::new(latent_node::CurrentnessReadTimer)),
                log_sink: None,
            },
            catalog.lifecycle_authority(),
        )
        .unwrap();
        let backend = Arc::new(factory.create_backend_instance());
        let quotas = LocalQuotaProvider::with_profile(
            node_policy(cells),
            BudgetProfile::Phase3,
            latent_core::DelegationLimits::default(),
        )
        .unwrap();
        let scheduler = Arc::new(
            LocalScheduler::new(
                LocalSchedulerConfig {
                    node: latent_core::NodeId("local-call-node".into()),
                    queue_capacity_per_class: BTreeMap::from([(CellClass::Tiny, 8)]),
                    starvation_after: Duration::from_secs(1),
                },
                quotas.clone(),
            )
            .unwrap(),
        );
        let admission =
            LocalAdmissionController::new(Arc::new(store.pin().unwrap()), quotas.clone(), load);
        let observations = Arc::new(Observations {
            starts: Mutex::new(vec![]),
            terminals: Mutex::new(vec![]),
            child_running: tokio::sync::Notify::new(),
            child_failures: Arc::new(diagnostics::Recorder::default()),
        });
        let manager = LocalActivationManager::with_services(
            latent_node::LocalActivationManagerConfig::default(),
            LocalActivationDependencies {
                catalog: store.clone(),
                admission,
                scheduler,
                artifacts: catalog.clone(),
                backend: backend.clone(),
            },
            LocalActivationServices {
                clock,
                ids: Arc::new(Ids(AtomicU64::new(0))),
                observer: Some(observations.clone()),
                canary: None,
            },
        )
        .unwrap();
        capabilities
            .install_local_services(Arc::new(diagnostics::ObservedInvoker {
                inner: manager.local_service_invoker(packages::budget()).unwrap(),
                recorder: observations.child_failures.clone(),
            }))
            .unwrap();
        Self {
            _guest_runtime: guest_runtime,
            manager,
            backend,
            _factory: factory,
            store,
            catalog,
            quotas,
            broker,
            _policies: policies,
            _provider: provider,
            target,
            observations,
            _root: root,
        }
    }
    pub fn request(&self, id: &str, which: u32) -> ActivationRequest {
        let mut request = admission_fixture::request(id);
        request.target.service = ServiceId("caller".into());
        request.target.contract = ContractId(component::CALLER.into());
        request.target.function = FunctionId("run".into());
        request.budget = packages::budget();
        request.input = format!("[{which}]").into_bytes();
        request.input_media_type = "application/vnd.latent.wit-values.v1+json".into();
        request
    }
    pub async fn idle(&self) {
        tokio::time::timeout(Duration::from_secs(2), async {
            loop {
                let broker = self.broker.snapshot();
                if self.quotas.usage().unwrap().active_activations == 0
                    && self.manager.cancellation_snapshot().active_registrations == 0
                    && self.backend.active_instance_reservations() == 0
                    && broker.calls == 0
                    && broker.sessions == 0
                    && broker.handles == 0
                    && broker.results == 0
                    && broker.buffer_bytes == 0
                {
                    return;
                }
                tokio::task::yield_now().await;
            }
        })
        .await
        .expect("all activation, store, call and result owners reclaimed");
    }
    pub fn revoke_target(&self) {
        use latent_artifacts::*;
        let scope = LifecycleScope::Tenant(self.target.metadata.tenant.clone().unwrap());
        self.catalog
            .change_publication_lifecycle(
                ReleaseMutationContext {
                    scope: scope.clone(),
                    actor: ReleaseActor {
                        subject: "local-call-test".into(),
                        kind: ReleaseActorKind::Host,
                    },
                    operation: Some(ReleaseOperationPrecondition {
                        operation_id: "revoke-target".into(),
                        expected_generation: 1,
                    }),
                },
                &PublicationRef {
                    id: self.target.publication.clone().unwrap(),
                    scope,
                },
                ReleaseLifecycleAction::Revoke,
                ReleaseLifecycleReason::OperatorRevocation,
                &mut |_| Ok(()),
            )
            .unwrap();
    }
}
/// This test composition has no production node monitor. Its fixed synthetic
/// healthy profile is sampled at every admission, including nested children
/// after a slow cold parent compile. Real quota accounting and admission's
/// normal freshness checks remain in force; no failed invocation is retried.
pub struct SyntheticFixtureLoad;
impl NodeLoadSource for SyntheticFixtureLoad {
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
    document["metadata"] = json!({"name":name,"tenant":tenant});
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
fn node_policy(cells: u32) -> latent_admission::NodeAdmissionPolicy {
    let mut policy = admission_fixture::node_policy(cells);
    policy.budget_ceiling = packages::budget();
    policy.architecture = std::env::consts::ARCH.into();
    policy.limits.maximum_reserved_cpu_fuel = packages::budget().cpu_fuel * 8;
    policy.limits.maximum_reserved_memory_bytes = packages::budget().memory_bytes * 8;
    for tenant in policy.tenants.values_mut() {
        tenant.limits = policy.limits;
        tenant
            .allowed_subjects
            .insert("service:8:tenant-a:6:caller".into());
        tenant.allowed_principal_kinds.push(PrincipalKind::Service);
    }
    // A forwarded user credential cannot satisfy the foreign callee's normal
    // admission policy. It accepts only this exact host-derived service actor.
    let foreign = policy
        .tenants
        .get_mut(&TenantId("tenant-b".into()))
        .unwrap();
    foreign.allowed_subjects = ["service:8:tenant-a:6:caller".into()].into();
    foreign.allowed_principal_kinds = vec![PrincipalKind::Service];
    for trust in policy.trust_classes.values_mut() {
        trust.limits = policy.limits;
    }
    for cell in policy.cell_classes.values_mut() {
        cell.maximum_memory_bytes = packages::budget().memory_bytes;
    }
    policy
}
