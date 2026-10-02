use super::{admission_fixture, artifact, guest_runtime, http, policy, signing};
use latent_artifacts::{ArtifactRepository, DirectoryArtifactRepository};
use latent_capabilities::{broker::*, namespace::RecoverySelection};
use latent_control_store::{DeploymentStore, DirectoryDeploymentRepository};
use latent_core::{BudgetProfile, Metadata, ResourceBudget, TenantId};
use latent_effects::{authority::*, runtime::*};
use latent_executor::ExecutionBackend;
use latent_manifest::{JsonManifestCodec, ManifestCodec, TransactionOperationMode};
use latent_node::transaction_runtime::{
    NativeTransactionAdmission, OwnedTransactionCompletion, TransactionAdmissionOwners,
    TransactionInstallation, TransactionSelection,
};
use latent_node::{LocalActivationDependencies, LocalActivationManager, LocalActivationServices};
use latent_policy::capability::{MutationRequest, PolicyStore, RecordKind};
use latent_scheduler::{CellClass, LocalScheduler, LocalSchedulerConfig};
use latent_state::{
    embedded::Family, namespace::catalog::*, protected_store::*, store_io::StoreIoKind,
};
use latent_wasmtime::{
    WasmtimeBackend, WasmtimeComponentEngineFactory, WasmtimeConfig, WasmtimeHostServices,
};
use serde_json::{json, Value};
use std::{
    collections::BTreeMap,
    os::unix::fs::PermissionsExt,
    sync::Arc,
    time::{Duration, Instant},
};

pub fn principal(tenant: &TenantId) -> latent_core::InvocationPrincipal {
    latent_core::InvocationPrincipal {
        subject: "alice".into(),
        kind: latent_core::PrincipalKind::User,
        tenant: Some(tenant.clone()),
        service: None,
        claims: Metadata::new(),
    }
}
struct Clock;
impl EffectTimeSource for Clock {
    fn observe(&self) -> EffectTime {
        EffectTime {
            unix_millis: 1000,
            continuity_proven: true,
        }
    }
}
struct Load;
impl latent_admission::NodeLoadSource for Load {
    fn snapshot(&self) -> Result<latent_admission::NodeLoadSnapshot, latent_core::PlatformError> {
        Ok(latent_admission::NodeLoadSnapshot {
            accepting: true,
            cpu_pressure_milli: 0,
            memory_pressure_milli: 0,
            queue_delay_millis: 0,
            observed_at: Instant::now(),
        })
    }
}

pub struct Fixture {
    _root: tempfile::TempDir,
    _catalog: Arc<DirectoryArtifactRepository>,
    _runtime: guest_runtime::Runtime,
    _factory: WasmtimeComponentEngineFactory,
    pub backend: Arc<WasmtimeBackend>,
    pub manager: LocalActivationManager,
    budget: ResourceBudget,
    tenant: TenantId,
    service: String,
    namespace: String,
    binding: Arc<TransactionInstallation>,
    owners: Arc<TransactionAdmissionOwners>,
    policies: Arc<PolicyStore>,
    store: Arc<ProtectedStoreOwner>,
    dispatcher: DispatcherOwner,
    quotas: latent_admission::LocalQuotaProvider,
    broker: Arc<ActivationCapabilityBroker>,
    http: Option<http::HttpOwner>,
}

impl Fixture {
    pub async fn new() -> Self {
        Self::variant("aggregate").await
    }

    #[expect(
        clippy::too_many_lines,
        reason = "One explicit native manager, namespace, role, broker and store ownership composition"
    )]
    pub async fn variant(variant: &str) -> Self {
        let storage_root = std::env::var_os("LATENT_STATE_TEST_ROOT")
            .expect("set LATENT_STATE_TEST_ROOT to the qualified Linux ext4 volume");
        let root = tempfile::tempdir_in(storage_root).unwrap();
        std::fs::set_permissions(root.path(), std::fs::Permissions::from_mode(0o700)).unwrap();
        let prepared = artifact::prepared(variant);
        let budget = prepared.manifest.execution.resource_budget_ceiling.clone();
        let tenant = prepared.manifest.metadata.tenant.clone().unwrap();
        let service = prepared.manifest.metadata.name.clone();
        let config = WasmtimeConfig {
            transactional_state: true,
            java_guest: guest_runtime::java(),
            fuel_async_yield_interval: guest_runtime::java().then_some(10_000),
            maximum_memory_bytes: budget.memory_bytes,
            maximum_fuel: budget.cpu_fuel,
            epoch_tick_interval_millis: 1,
            prepared_cache_maximum_entries: 2,
            ..Default::default()
        };
        let manifest_profile = artifact::profile();
        let (catalog, release, receipt) =
            signing::publish(root.path(), &prepared, variant, &config, &tenant).await;
        let declaration = prepared.declaration;
        let publication = catalog
            .execution_eligibility_selected(&release, Some(&receipt.publication.id))
            .unwrap()
            .unwrap();
        let metadata = catalog
            .fetch_verified_metadata_selected(&release, Some(&receipt.publication.id))
            .await
            .unwrap();
        let (policies, state, intents) =
            policy::create(root.path(), &catalog, &publication, &declaration);
        let policies = Arc::new(policies);
        let clock: Arc<dyn latent_core::ActivationClock> =
            Arc::new(latent_core::SystemActivationClock);
        let broker = Arc::new(
            ActivationCapabilityBroker::new(
                catalog.lifecycle_authority(),
                policies.clone(),
                clock.clone(),
                CapabilityBrokerLimits::default(),
            )
            .unwrap(),
        );
        let http = (variant == "forbidden-http")
            .then(|| http::HttpOwner::new(&broker, &policies, &publication, &service));
        let runtime = guest_runtime::Runtime::scoped(
            &broker,
            &policies,
            tenant.0.as_str(),
            &[guest_runtime::Scope {
                services: &[&service],
                publications: std::slice::from_ref(publication.publication()),
                principal: ("user", "alice"),
            }],
            false,
        );
        let routes = Arc::new(
            DirectoryDeploymentRepository::open_with_catalog(
                root.path().join("routes"),
                catalog.clone(),
                latent_control_store::DirectoryDeploymentRepositoryConfig {
                    manifest_profile,
                    ..Default::default()
                },
                catalog.lifecycle_authority(),
                Arc::new(config.detected_runtime_profile().unwrap()),
            )
            .await
            .unwrap(),
        );
        let mut document: Value = serde_json::from_slice(include_bytes!(
            "../../../../examples/echo-contract/deployment.json"
        ))
        .unwrap();
        document["metadata"] = json!({"name":declaration.deployment,"tenant":tenant.0.as_str()});
        document["spec"]["service"] = json!(service);
        document["spec"]["release"] = json!(release.0.as_str());
        document["spec"]["publication"] = json!(publication.publication().as_str());
        let mut deployment = JsonManifestCodec::default()
            .decode_deployment(&serde_json::to_vec(&document).unwrap())
            .unwrap();
        deployment.resources = budget.clone();
        deployment.grants = guest_runtime::grants();
        if let Some(http) = &http {
            deployment.grants.push(http.grant());
        }
        deployment.placement.architectures = vec![std::env::consts::ARCH.into()];
        routes.apply(deployment.clone()).await.unwrap();
        let mut definitions = runtime.definitions(tenant.0.as_str(), &[&service]);
        let mut providers = runtime.providers(tenant.0.as_str());
        if let Some(http) = &http {
            definitions.push(http.definition(&tenant, &service));
            providers.push(http.configured(&tenant));
        }
        if !definitions.is_empty() {
            let (generation, transaction) = routes.binding_version().unwrap();
            let update = routes
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
            routes.commit_binding_update(update).unwrap();
        }
        let capabilities = Arc::new(ActivationCapabilityRuntime::new(
            broker.clone(),
            routes.clone(),
        ));
        runtime.install(&capabilities);
        if let Some(http) = &http {
            http.install(&capabilities);
        }
        let factory = WasmtimeComponentEngineFactory::with_catalog(
            config,
            WasmtimeHostServices {
                clock: clock.clone(),
                capabilities: Some(capabilities),
                currentness_read_wait: Some(Arc::new(latent_node::CurrentnessReadTimer)),
                log_sink: None,
            },
            catalog.lifecycle_authority(),
        )
        .unwrap();
        let backend = Arc::new(factory.create_backend_instance());
        // Prepare the exact verified component before admitting any command or
        // acquiring a finite state view. A cache miss creates no guest Store,
        // extends no caller deadline and supplies no business authority.
        let mut preparation = backend.preparation_key(&release).unwrap();
        preparation.publication = Some(publication.publication().clone());
        drop(
            backend
                .prepare_ready_from_repository(catalog.clone(), preparation)
                .await
                .unwrap(),
        );
        assert_eq!(backend.resource_snapshot().stores_created, 0);
        let native = latent_core::native_capacity::NativeCapacityOwner::new(
            latent_core::native_capacity::NativeCapacityLimits::default(),
        )
        .unwrap();
        let state_root = root.path().join("state");
        std::fs::create_dir(&state_root).unwrap();
        std::fs::set_permissions(&state_root, std::fs::Permissions::from_mode(0o700)).unwrap();
        let mut store_config = ProtectedStoreConfig::bounded_linux(state_root);
        store_config.create_if_missing = true;
        let store = Arc::new(
            ProtectedStoreOwner::start(store_config)
                .unwrap()
                .await
                .unwrap(),
        );
        store.bind_native_capacity(&native).unwrap();
        let namespaces = Arc::new(NamespaceCatalog::new());
        create_namespace(&store, &namespaces, &tenant, &declaration).await;
        let effects = EffectAuthorityOwner::new(128, 16, 100).unwrap();
        effects
            .publish(EffectRule {
                scope: EffectScope {
                    tenant: tenant.0.as_str().into(),
                    namespace: declaration.namespace.clone(),
                    incarnation: 1,
                    publication: publication.publication().as_str().into(),
                    binding: "approved-event".into(),
                    operation: "event".into(),
                },
                profile: DispatchProfile {
                    provider: "campaign-pending-provider".into(),
                    destination: "approved-event".into(),
                    adapter: "campaign-v1".into(),
                    intent_format: 1,
                    payload_format: "lsf.aggregate-v1".into(),
                    idempotency_profile: "none.v1".into(),
                },
                policy_revision: 1,
                credential_epoch: 1,
                protected_credential_reference: "campaign-provider".into(),
                ceiling: DispatchCeiling {
                    maximum_payload_bytes: 1024,
                    maximum_response_bytes: 1024,
                    maximum_attempts: 3,
                    maximum_age_millis: 60_000,
                    attempt_timeout_millis: 1000,
                },
                enabled: true,
            })
            .unwrap();
        let dispatcher = DispatcherOwner::start(
            DispatcherConfig::default(),
            store.clone(),
            effects,
            Vec::new(),
            Arc::new(Clock),
            None,
        )
        .await
        .unwrap();
        dispatcher.bind_native_capacity(&native).unwrap();
        let owners = Arc::new(
            TransactionAdmissionOwners::new(
                store.clone(),
                namespaces,
                policies.clone(),
                dispatcher.command_admission_source(),
            )
            .unwrap(),
        );
        let namespace = declaration.namespace.clone();
        let binding = Arc::new(
            TransactionInstallation::new(
                metadata,
                declaration,
                &deployment,
                publication,
                Arc::new(state),
                Some(Arc::new(intents)),
                RecoverySelection::OriginalCaller,
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
        let quotas = latent_admission::LocalQuotaProvider::with_profile(
            node_policy(&budget, &tenant),
            BudgetProfile::Phase4,
            latent_core::DelegationLimits::default(),
        )
        .unwrap();
        let scheduler = Arc::new(
            LocalScheduler::new(
                LocalSchedulerConfig {
                    node: latent_core::NodeId("native-guest-node".into()),
                    queue_capacity_per_class: BTreeMap::from([(CellClass::Tiny, 8)]),
                    starvation_after: Duration::from_secs(1),
                },
                quotas.clone(),
            )
            .unwrap(),
        );
        let admission = latent_admission::LocalAdmissionController::new(
            Arc::new(routes.pin().unwrap()),
            quotas.clone(),
            Arc::new(Load),
        );
        let manager = LocalActivationManager::with_services(
            Default::default(),
            LocalActivationDependencies {
                catalog: routes,
                admission,
                scheduler,
                artifacts: catalog.clone(),
                backend: backend.clone(),
            },
            LocalActivationServices {
                clock,
                ..Default::default()
            },
        )
        .unwrap();
        Self {
            _root: root,
            _catalog: catalog,
            _runtime: runtime,
            _factory: factory,
            backend,
            manager,
            budget,
            tenant,
            service,
            namespace,
            binding,
            owners,
            policies,
            store,
            dispatcher,
            quotas,
            broker,
            http,
        }
    }

    pub async fn invoke(
        &self,
        operation: &str,
        id: &str,
        input: Value,
        minimum: Option<Vec<u8>>,
    ) -> OwnedTransactionCompletion {
        let query = operation != "update";
        let admission = Arc::new(
            NativeTransactionAdmission::new(
                self.owners.clone(),
                self.binding.clone(),
                TransactionSelection {
                    namespace: self.namespace.clone(),
                    incarnation: 1,
                    entity: None,
                    operation: operation.into(),
                    mode: if query {
                        TransactionOperationMode::FreshQuery
                    } else {
                        TransactionOperationMode::StrictCommand
                    },
                    client_key: (!query).then(|| id.into()),
                    expected_versions: Vec::new(),
                    minimum_view_version: minimum,
                    input_format: "lsf-wit-values-v1".into(),
                    retry: None,
                },
            )
            .unwrap(),
        );
        let mut request = admission_fixture::request(id);
        request.principal = principal(&self.tenant);
        request.target.tenant = self.tenant.clone();
        request.target.service = latent_core::ServiceId(self.service.clone());
        request.target.contract =
            latent_core::ContractId("examples:transactional-aggregate/api@1.0.0".into());
        request.target.function = latent_core::FunctionId(operation.into());
        request.input = serde_json::to_vec(&input).unwrap();
        request.input_media_type = "application/vnd.latent.wit-values.v1+json".into();
        request.budget = self.budget.clone();
        if query {
            request.budget.state_write_bytes = 0;
            request.budget.effect_count = 0;
        }
        let receipt = self
            .manager
            .start_transaction_with_deadline(request, None, admission.clone())
            .unwrap()
            .await;
        assert!(
            !matches!(
                &receipt.outcome,
                latent_activation::ActivationOutcome::Failed { .. }
            ),
            "actual node failure: {:?}",
            receipt.outcome
        );
        let completion = admission
            .take_owned_completion()
            .unwrap()
            .expect("actual manager affine completion");
        assert!(admission.take_owned_completion().unwrap().is_none());
        completion.authority.with_current(&mut || {}).unwrap();
        completion
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
    pub fn assert_no_http_start(&self) {
        self.http
            .as_ref()
            .expect("the forbidden-HTTP fixture installs a real provider")
            .assert_not_started();
    }
    pub fn revoke(&self) {
        let deadline = Instant::now() + Duration::from_secs(10);
        let current = self
            .policies
            .get(
                self.tenant.0.as_str(),
                RecordKind::Policy,
                "state",
                64 * 1024,
                deadline,
            )
            .unwrap();
        let revision = current.value().as_ref().unwrap().revision;
        drop(current);
        self.policies
            .mutate(
                MutationRequest {
                    tenant: self.tenant.0.as_str(),
                    actor: "operator",
                    kind: RecordKind::Policy,
                    id: "state",
                    operation_id: "revoke-state",
                    expected_revision: revision,
                    document: None,
                },
                deadline,
                |_| Ok(()),
            )
            .unwrap();
    }
    pub async fn idle(&self) {
        tokio::time::timeout(Duration::from_secs(2), async {
            loop {
                let broker = self.broker.snapshot();
                if self.quotas.usage().unwrap().active_activations == 0
                    && self.manager.cancellation_snapshot().active_registrations == 0
                    && self.backend.active_instance_reservations() == 0
                    && broker.sessions == 0
                    && broker.calls == 0
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
        .expect("all actual node, broker and guest owners physically retire");
    }
    pub async fn shutdown(mut self) {
        let deadline = Instant::now() + Duration::from_secs(10);
        assert!(self.dispatcher.shutdown(deadline).await.unwrap().clean);
        if let Some(http) = self.http.take() {
            http.shutdown(deadline).await;
        }
        let report = self
            .store
            .drain_async(deadline, tokio::time::sleep_until(deadline.into()))
            .unwrap()
            .await;
        assert!(report.clean && report.snapshot.physically_retired());
        self.store.reap_retired_threads().unwrap();
    }
}

async fn create_namespace(
    store: &ProtectedStoreOwner,
    namespaces: &Arc<NamespaceCatalog>,
    tenant: &TenantId,
    declaration: &latent_manifest::TransactionBinding,
) {
    let namespaces = namespaces.clone();
    let tenant = tenant.clone();
    let namespace = declaration.namespace.clone();
    let schema = declaration.state_schema.clone();
    store
        .with_store(StoreIoKind::Write, 8192, move |store| {
            let plan = namespaces
                .prepare(
                    store,
                    NamespaceOperationContext {
                        tenant,
                        actor: "campaign-operator".into(),
                        operation_id: "namespace-create".into(),
                    },
                    &NamespaceMutation::Create {
                        id: latent_core::StateNamespaceId(namespace),
                        state_schema: schema,
                        quota: latent_state::namespace::NamespaceQuota::default(),
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
}

fn node_policy(
    budget: &ResourceBudget,
    tenant: &TenantId,
) -> latent_admission::NodeAdmissionPolicy {
    let mut policy = admission_fixture::node_policy(1);
    policy.budget_ceiling = budget.clone();
    policy.architecture = std::env::consts::ARCH.into();
    policy.limits.maximum_reserved_cpu_fuel = budget.cpu_fuel * 8;
    policy.limits.maximum_reserved_memory_bytes = budget.memory_bytes * 8;
    let mut selected = policy.tenants.values().next().unwrap().clone();
    selected.limits = policy.limits;
    policy.tenants = BTreeMap::from([(tenant.clone(), selected)]);
    for trust in policy.trust_classes.values_mut() {
        trust.limits = policy.limits;
    }
    for cell in policy.cell_classes.values_mut() {
        cell.maximum_memory_bytes = budget.memory_bytes;
    }
    policy
}
