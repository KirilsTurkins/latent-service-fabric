use super::{component, support};
use latent_artifacts::{
    ArtifactRepository, LifecycleScope, ManagedPublicationUpload, ReleaseActor, ReleaseActorKind,
    ReleaseMutationContext, ReleaseOperationPrecondition, ReleaseUseEligibility,
};
pub use latent_artifacts::{DirectoryArtifactRepository, DirectoryArtifactRepositoryConfig};
pub use latent_capabilities::broker::*;
use latent_capabilities::broker::{
    io::{IoLimits, IoRuntime},
    pools::{ProviderPoolLimits, ProviderPools},
};
use latent_core::{ActivationBudget, EffectiveActivationBudget};
pub use latent_core::{
    ActivationClock, ActivationId, CapabilityId, ClockSample, ContractId, Metadata, PlatformError,
    RevisionId, RouteGeneration, TenantId,
};
use latent_executor::{
    BoundImport, ExecutionCancellation, ExecutionCancellationProbe, ExecutionRequest,
    PreparedComponent,
};
pub use latent_executor::{ExecutionBackend, ExecutionCleanup, GuestOutcome};
use latent_http::{
    HttpAddressPolicy, HttpDestination, HttpLimits, HttpProviderConfig, HttpResolution,
    HttpStreamLimits, StreamingHttpProvider,
};
use latent_manifest::ContractImport;
use latent_policy::capability::{MutationRequest, RecordKind};
pub use latent_policy::capability::{PolicyStore, PolicyStoreLimits};
use latent_routing::ResolvedRevision;
use latent_wasmtime::WasmtimeBackend;
pub use latent_wasmtime::{WasmtimeComponentEngineFactory, WasmtimeHostServices};
use serde_json::json;
use std::sync::{
    atomic::{AtomicBool, AtomicUsize},
    Mutex,
};
pub use std::{
    sync::{atomic::Ordering, Arc},
    time::{Duration, Instant},
};

pub struct Clock {
    pub calls: AtomicUsize,
    pub hook: Mutex<Option<Box<dyn FnOnce() + Send>>>,
}
impl ActivationClock for Clock {
    fn monotonic_now(&self) -> Instant {
        Instant::now()
    }
    fn sample(&self) -> ClockSample {
        self.calls.fetch_add(1, Ordering::AcqRel);
        let hook = self.hook.lock().unwrap().take();
        if let Some(hook) = hook {
            hook();
        }
        ClockSample::system_now()
    }
}
struct Plans(Arc<CompiledCapabilityPlan>);
impl CapabilityPlanSource for Plans {
    fn plan(&self, _: &ResolvedRevision) -> Result<Arc<CompiledCapabilityPlan>, PlatformError> {
        Ok(self.0.clone())
    }
}
pub struct Probe(pub AtomicBool);
impl ExecutionCancellationProbe for Probe {
    fn is_cancelled(&self) -> bool {
        self.0.load(Ordering::Acquire)
    }
    fn reason(&self) -> Option<String> {
        None
    }
}
pub struct Control {
    pub id: ActivationId,
    pub budget: ActivationBudget,
    pub probe: Arc<Probe>,
}
impl ExecutionCancellation for Control {
    fn activation_id(&self) -> &ActivationId {
        &self.id
    }
    fn is_cancelled(&self) -> bool {
        self.probe.is_cancelled()
    }
    fn reason(&self) -> Option<String> {
        None
    }
    fn budget_accounting(&self) -> Option<&ActivationBudget> {
        Some(&self.budget)
    }
    fn probe(&self) -> Option<Arc<dyn ExecutionCancellationProbe>> {
        Some(self.probe.clone())
    }
}
pub struct Fixture {
    ceiling: latent_core::ResourceBudget,
    _guest_runtime: support::guest_runtime::Runtime,
    _factory: WasmtimeComponentEngineFactory,
    pub backend: WasmtimeBackend,
    pub prepared: PreparedComponent,
    catalog: Arc<DirectoryArtifactRepository>,
    pub policies: Arc<PolicyStore>,
    pub broker: Arc<ActivationCapabilityBroker>,
    _runtime: Arc<ActivationCapabilityRuntime>,
    _clock: Arc<Clock>,
    pub revision: ResolvedRevision,
    _provider: StreamingHttpProvider,
    pub pools: Arc<ProviderPools>,
    pub io: Arc<IoRuntime>,
    directory: tempfile::TempDir,
}
impl Fixture {
    pub async fn new(port: u16, path: &str) -> Self {
        Self::with_publication(port, path, None).await
    }
    #[expect(
        clippy::too_many_lines,
        reason = "compose the real catalog, grants, provider and fresh Store with explicit owner lifetimes"
    )]
    pub async fn with_publication(
        port: u16,
        path: &str,
        publication: Option<(
            Arc<DirectoryArtifactRepository>,
            latent_core::ReleaseDigest,
            latent_artifacts::ManagedPublicationReceipt,
        )>,
    ) -> Self {
        let mut ceiling = support::budget();
        ceiling.outbound_requests = 8;
        ceiling.wall_time_limit_millis = Some(5000);
        let directory = tempfile::TempDir::new().unwrap();
        let (catalog, release, receipt) = if let Some(publication) = publication {
            publication
        } else {
            let catalog = Arc::new(
                DirectoryArtifactRepository::open(
                    directory.path().join("catalog"),
                    DirectoryArtifactRepositoryConfig::default(),
                )
                .unwrap(),
            );
            let mut artifact = support::artifact_bytes(
                component::bytes(&format!("http://localhost:{port}{path}")),
                &[component::CONTRACT],
            );
            artifact.contracts = super::packages::artifact(&super::packages::capsule(&format!(
                "http://localhost:{port}{path}"
            )))
            .contracts;
            artifact.manifest.execution.resource_budget_ceiling = ceiling.clone();
            artifact.manifest.imports.push(ContractImport {
                contract: ContractId(component::CAP.into()),
                optional: false,
            });
            let release = artifact.descriptor.release_digest.clone();
            let receipt = catalog
                .publish_managed(
                    ReleaseMutationContext {
                        scope: LifecycleScope::Tenant(TenantId("tests".into())),
                        actor: ReleaseActor {
                            subject: "broker-test".into(),
                            kind: ReleaseActorKind::Host,
                        },
                        operation: Some(ReleaseOperationPrecondition {
                            operation_id: "publish".into(),
                            expected_generation: 0,
                        }),
                    },
                    ManagedPublicationUpload::Local(artifact),
                    &mut |_| Ok(()),
                )
                .await
                .unwrap();
            (catalog, release, receipt)
        };
        let publication = catalog
            .execution_eligibility_selected(&release, Some(&receipt.publication.id))
            .unwrap()
            .unwrap();
        ceiling = ceiling.intersect(
            &catalog
                .fetch_verified_metadata_selected(&release, Some(&receipt.publication.id))
                .await
                .unwrap()
                .manifest()
                .execution
                .resource_budget_ceiling,
        );
        let policies = Arc::new(
            PolicyStore::open(
                &directory.path().join("policies"),
                PolicyStoreLimits::default(),
                catalog.lifecycle_authority(),
            )
            .unwrap(),
        );
        let clock = Arc::new(Clock {
            calls: AtomicUsize::new(0),
            hook: Mutex::new(None),
        });
        let broker = Arc::new(
            ActivationCapabilityBroker::new(
                catalog.lifecycle_authority(),
                policies.clone(),
                clock.clone(),
                CapabilityBrokerLimits::default(),
            )
            .unwrap(),
        );
        let io = Arc::new(IoRuntime::new(IoLimits::default()).unwrap());
        let pools = Arc::new(
            ProviderPools::new(
                broker.clone(),
                io.clone(),
                tokio::runtime::Handle::current(),
                ProviderPoolLimits::default(),
            )
            .unwrap(),
        );
        let config = HttpProviderConfig {
            format_version: 1,
            limits: HttpLimits::default(),
            public_roots: false,
            extra_roots: vec![],
            destinations: vec![HttpDestination {
                origin: latent_policy::capability::HttpOrigin {
                    scheme: "http".into(),
                    host: "localhost".into(),
                    port,
                },
                addresses: HttpAddressPolicy {
                    networks: vec!["127.0.0.0/8".parse().unwrap()],
                    special_addresses: vec!["127.0.0.1".parse().unwrap()],
                },
                resolution: HttpResolution::Static {
                    addresses: vec!["127.0.0.1".parse().unwrap()],
                },
                allowed_request_headers: vec![],
                redirect_destinations: vec![],
            }],
        };
        let provider = StreamingHttpProvider::install(
            pools.clone(),
            "http-stream",
            1,
            0,
            config,
            HttpStreamLimits {
                maximum_input_bytes: 1024,
                maximum_output_bytes: 1024,
                maximum_chunk_bytes: 4,
                maximum_outstanding_chunks: 2,
            },
            &[],
        )
        .unwrap();
        install(
            &policies,
            &publication,
            provider.reference().configuration_digest(),
            port,
        );
        let revision = ResolvedRevision {
            target: latent_routing::InvocationTarget {
                tenant: TenantId("tests".into()),
                service: latent_core::ServiceId("generic".into()),
                contract: ContractId(component::CONTRACT.into()),
                function: latent_core::FunctionId("run".into()),
                route: None,
            },
            revision: RevisionId("revision-1".into()),
            release,
            publication: Some(receipt.publication.id),
            route_generation: RouteGeneration(1),
            attributes: Metadata::new(),
        };
        let guest_runtime =
            support::guest_runtime::Runtime::new(&broker, &policies, &publication, component::CAP);
        let plan = broker
            .compile_plan(
                &revision,
                &guest_runtime.bindings(&[CapabilityBindingSpec {
                    definition_digest: None,
                    provider: &provider.reference(),
                    imported_operations: &["open".into()],
                    policy_ids: &["p".into()],
                    provider_binding_id: "binding",
                    deployment_restriction_json: br#"{"operations":[]}"#,
                }]),
                &publication,
                Instant::now() + Duration::from_secs(10),
            )
            .unwrap();
        let runtime = Arc::new(ActivationCapabilityRuntime::new(
            broker.clone(),
            Arc::new(Plans(plan)),
        ));
        runtime
            .install_streaming_http(Arc::new(provider.clone()))
            .unwrap();
        guest_runtime.install(&runtime);
        let factory = WasmtimeComponentEngineFactory::with_catalog(
            support::config(),
            WasmtimeHostServices {
                clock: clock.clone(),
                log_sink: None,
                capabilities: Some(runtime.clone()),
                currentness_read_wait: Some(Arc::new(latent_node::CurrentnessReadTimer)),
            },
            catalog.lifecycle_authority(),
        )
        .unwrap();
        let backend = factory.create_backend_instance();
        let mut key = factory.preparation_key(revision.release.clone());
        key.publication = revision.publication.clone();
        let ready = backend
            .prepare_ready_from_repository(catalog.clone(), key)
            .await
            .unwrap();
        let prepared = ready.descriptor().clone();
        drop(ready);
        Self {
            ceiling,
            _guest_runtime: guest_runtime,
            _factory: factory,
            backend,
            prepared,
            catalog,
            policies,
            broker,
            _runtime: runtime,
            _clock: clock,
            revision,
            _provider: provider,
            pools,
            io,
            directory,
        }
    }
    pub fn request(&self, id: &str, method: u32) -> (ExecutionRequest, Control) {
        let id = ActivationId(id.into());
        let mut grant = self.ceiling.clone();
        grant.outbound_requests = 8;
        grant.wall_time_limit_millis = Some(5000);
        let budget = ActivationBudget::with_profile(
            EffectiveActivationBudget::admit_profile_at(
                latent_core::BudgetProfile::Phase3,
                &grant,
                &grant,
                &grant,
                None,
                ClockSample::system_now(),
            )
            .unwrap(),
            latent_core::BudgetProfile::Phase3,
        )
        .unwrap();
        let mut request = support::request(
            self.prepared.clone(),
            &id,
            component::CONTRACT,
            "run",
            format!("[{method}]").as_bytes(),
            grant,
        );
        request.activation.resolved_revision = Some(self.revision.clone());
        request.imports.push(BoundImport {
            capability: CapabilityId(component::CAP.into()),
            contract: component::CAP.into(),
            opaque_handle: "descriptive-only".into(),
        });
        (
            request,
            Control {
                id,
                budget,
                probe: Arc::new(Probe(AtomicBool::new(false))),
            },
        )
    }
    pub async fn dormant_deployments(&self) {
        use latent_control_store::{
            DeploymentStore, DirectoryDeploymentRepository, DirectoryDeploymentRepositoryConfig,
        };
        use latent_manifest::{
            AvailabilityPolicy, DeploymentManifest, ObjectMetadata, PlacementPolicy,
        };
        let store = DirectoryDeploymentRepository::open(
            self.directory.path().join("dormant-deployments"),
            self.catalog.clone(),
            DirectoryDeploymentRepositoryConfig::default(),
        )
        .await
        .unwrap();
        let before = (
            self.io.snapshot(),
            self.pools.snapshot().unwrap(),
            self.broker.snapshot(),
        );
        let mut resources = support::budget();
        resources.outbound_requests = 8;
        resources.wall_time_limit_millis = Some(5000);
        let deployments = (0..256)
            .map(|i| DeploymentManifest {
                publication: self.revision.publication.clone(),
                api_version: latent_manifest::MANIFEST_API_VERSION.into(),
                id: latent_core::DeploymentId(format!("stream-dormant-{i}")),
                metadata: ObjectMetadata {
                    name: format!("stream-dormant-{i}"),
                    tenant: Some(TenantId("tests".into())),
                    namespace: None,
                    labels: Metadata::new(),
                    annotations: Metadata::new(),
                },
                service: latent_core::ServiceId("generic-capsule".into()),
                release: self.revision.release.clone(),
                route_weight: 1,
                grants: vec![],
                resources: resources.clone(),
                availability: AvailabilityPolicy {
                    minimum_cached_copies: 1,
                    minimum_zones: 1,
                },
                placement: PlacementPolicy {
                    trust_class: "local".into(),
                    architectures: vec!["x86_64".into()],
                    regions: vec![],
                    zones: vec![],
                    required_features: vec![],
                },
            })
            .collect();
        store.apply_many(deployments).await.unwrap();
        assert_eq!(store.list().await.unwrap().len(), 256);
        assert_eq!(self.io.snapshot(), before.0);
        assert_eq!(self.pools.snapshot().unwrap(), before.1);
        assert_eq!(self.broker.snapshot(), before.2);
        assert_eq!(self.backend.resource_snapshot().stores_created, 0);
        self.idle();
    }
    pub fn idle(&self) {
        let resources = self.backend.resource_snapshot();
        assert_eq!(resources.live_stores, 0);
        assert_eq!(resources.live_host_states, 0);
        assert_eq!(self.backend.active_instance_reservations(), 0);
        let broker = self.broker.snapshot();
        assert_eq!(
            (
                broker.sessions,
                broker.handles,
                broker.calls,
                broker.results,
                broker.buffer_bytes
            ),
            (0, 0, 0, 0, 0)
        );
    }
}
fn install(store: &PolicyStore, publication: &ReleaseUseEligibility, digest: &str, port: u16) {
    for (id, kind, value) in [
        (
            "p",
            RecordKind::Policy,
            json!({"formatVersion":1,"tenant":"tests","rules":[{
                "id":"allow", "effect":"allow","principals":[{"kind":"service","subject":"generic-test"}],
                "services":["generic"], "publications":[publication.publication().as_str()], "capability":component::CAP,
                "operations":["open"], "resources":{"kind":"http","origins":[{"scheme":"http","host":"localhost","port":port}],"methods":["GET","HEAD","POST","PUT","PATCH","DELETE","OPTIONS"],"paths":["/allowed"],"pathPrefixes":[]},
                "ceiling":{"operations":1,"inputBytes":65536,"outputBytes":65536,"wallTimeMillis":5000}
            }]}),
        ),
        (
            "binding",
            RecordKind::ProviderBinding,
            json!({"formatVersion":1,"tenant":"tests","capability":component::CAP,
            "providerProfile":"bounded-streaming-http-identity-v1","configurationDigest":digest,"configurationEpoch":1,"restriction":{"operations":[]}}),
        ),
    ] {
        store
            .mutate(
                MutationRequest {
                    tenant: "tests",
                    actor: "operator",
                    id,
                    kind,
                    operation_id: id,
                    expected_revision: 0,
                    document: Some(&serde_json::to_vec(&value).unwrap()),
                },
                Instant::now() + Duration::from_secs(10),
                |_| Ok(()),
            )
            .unwrap();
    }
}
