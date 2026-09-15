use super::{component, support};
use latent_artifacts::{
    ArtifactRepository, LifecycleScope, ManagedPublicationUpload, ReleaseActor, ReleaseActorKind,
    ReleaseMutationContext, ReleaseOperationPrecondition, ReleaseUseEligibility,
};
pub use latent_artifacts::{DirectoryArtifactRepository, DirectoryArtifactRepositoryConfig};
pub use latent_capabilities::broker::*;
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
    pub plan: Arc<CompiledCapabilityPlan>,
    pub provider: Arc<latent_capabilities::broker::random::RandomProvider>,
    pub factory: WasmtimeComponentEngineFactory,
    pub backend: WasmtimeBackend,
    pub prepared: PreparedComponent,
    pub catalog: Arc<DirectoryArtifactRepository>,
    pub policies: Arc<PolicyStore>,
    pub broker: Arc<ActivationCapabilityBroker>,
    pub runtime: Arc<ActivationCapabilityRuntime>,
    pub clock: Arc<Clock>,
    pub revision: ResolvedRevision,
    _directory: tempfile::TempDir,
}
impl Fixture {
    pub async fn new(
        source: Option<Arc<dyn latent_capabilities::broker::random::TestEntropy>>,
        limits: latent_capabilities::broker::random::RandomLimits,
    ) -> Self {
        Self::configured(source, limits, None).await
    }
    #[expect(
        clippy::too_many_lines,
        reason = "one real catalog, policy and runtime composition fixture in dependency order"
    )]
    pub async fn configured(
        source: Option<Arc<dyn latent_capabilities::broker::random::TestEntropy>>,
        limits: latent_capabilities::broker::random::RandomLimits,
        audit: Option<latent_audit::AuditHandle>,
    ) -> Self {
        let required = audit.is_some();
        let ceiling = support::budget();
        let directory = tempfile::TempDir::new().unwrap();
        let catalog = Arc::new(
            DirectoryArtifactRepository::open(
                directory.path().join("catalog"),
                DirectoryArtifactRepositoryConfig::default(),
            )
            .unwrap(),
        );
        let mut artifact = support::artifact_bytes(component::bytes(), &[component::CONTRACT]);
        artifact.manifest.execution.resource_budget_ceiling = ceiling;
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
        let publication = catalog
            .execution_eligibility_selected(&release, Some(&receipt.publication.id))
            .unwrap()
            .unwrap();
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
        let mut broker = ActivationCapabilityBroker::new(
            catalog.lifecycle_authority(),
            policies.clone(),
            clock.clone(),
            CapabilityBrokerLimits::default(),
        )
        .unwrap();
        if let Some(audit) = audit {
            broker = broker.with_audit(audit, false).unwrap();
        }
        let broker = Arc::new(broker);
        let provider = match source {
            Some(source) => latent_capabilities::broker::random::RandomProvider::for_test(
                &broker, 1, limits, source,
            ),
            None => latent_capabilities::broker::random::RandomProvider::system(&broker, 1, limits),
        }
        .unwrap();
        install(&policies, &publication, &provider.reference(), required);
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
        let plan = broker
            .compile_invocation_plan(
                &revision,
                Some(&latent_core::DeploymentId("random-deployment".into())),
                &[CapabilityBindingSpec {
                    definition_digest: Some(&latent_artifacts::package::artifact_blob_digest(
                        b"random-fixture-binding-v1",
                    )),
                    provider: &provider.reference(),
                    imported_operations: &["bytes".into(), "u64-value".into()],
                    policy_ids: &["p".into()],
                    provider_binding_id: "binding",
                    deployment_restriction_json: br#"{"operations":[]}"#,
                }],
                &publication,
                &[],
                &[],
                &[],
                None,
                Instant::now() + Duration::from_secs(10),
            )
            .unwrap();
        let runtime = Arc::new(ActivationCapabilityRuntime::new(
            broker.clone(),
            Arc::new(Plans(plan.clone())),
        ));
        runtime.install_random(provider.clone()).unwrap();
        let factory = WasmtimeComponentEngineFactory::with_catalog(
            support::config(),
            WasmtimeHostServices {
                clock: clock.clone(),
                log_sink: None,
                capabilities: Some(runtime.clone()),
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
            plan,
            factory,
            backend,
            prepared,
            catalog,
            policies,
            broker,
            runtime,
            clock,
            revision,
            provider,
            _directory: directory,
        }
    }
    pub fn services(&self) -> WasmtimeHostServices {
        WasmtimeHostServices {
            clock: self.clock.clone(),
            log_sink: None,
            capabilities: Some(self.runtime.clone()),
        }
    }
    pub fn request(
        &self,
        id: &str,
        mode: u32,
        length: u32,
        count: u32,
    ) -> (ExecutionRequest, Control) {
        let id = ActivationId(id.into());
        let grant = support::budget();
        let budget = ActivationBudget::new(
            EffectiveActivationBudget::admit_at(
                &grant,
                &grant,
                &grant,
                None,
                ClockSample::system_now(),
            )
            .unwrap(),
        );
        let mut request = support::request(
            self.prepared.clone(),
            &id,
            component::CONTRACT,
            "run",
            format!("[{mode},{length},{count}]").as_bytes(),
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
fn install(
    store: &PolicyStore,
    publication: &ReleaseUseEligibility,
    provider: &ProviderReference,
    required: bool,
) {
    for (id, kind, value) in [
        (
            "p",
            RecordKind::Policy,
            json!({"formatVersion":1,"tenant":"tests","rules":[{
                "id":"allow", "effect":"allow", "requireAudit":required,"principals":[{"kind":"service","subject":"generic-test"}],
                "services":["generic"], "publications":[publication.publication().as_str()], "capability":component::CAP,
                "operations":["bytes","u64-value"], "resources":{"kind":"random"},
                "ceiling":{"operations":1,"inputBytes":1024,"outputBytes":4096,"wallTimeMillis":5000}
            }]}),
        ),
        (
            "binding",
            RecordKind::ProviderBinding,
            json!({"formatVersion":1,"tenant":"tests","capability":component::CAP,
            "providerProfile":provider.profile(),"configurationDigest":provider.configuration_digest(),"configurationEpoch":1,"restriction":{"operations":[]}}),
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
pub fn revoke(store: &PolicyStore) {
    store
        .mutate(
            MutationRequest {
                tenant: "tests",
                actor: "operator",
                id: "p",
                kind: RecordKind::Policy,
                operation_id: "revoke",
                expected_revision: 2,
                document: None,
            },
            Instant::now() + Duration::from_secs(5),
            |_| Ok(()),
        )
        .unwrap();
}
