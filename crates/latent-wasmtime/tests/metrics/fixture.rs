#[path = "fixture/configuration.rs"]
mod configuration;
#[path = "fixture/tenant.rs"]
mod tenant;
use super::{authority, component, support};
pub use configuration::config;
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
struct Plans(Mutex<Vec<Arc<CompiledCapabilityPlan>>>);
impl CapabilityPlanSource for Plans {
    fn plan(
        &self,
        revision: &ResolvedRevision,
    ) -> Result<Arc<CompiledCapabilityPlan>, PlatformError> {
        Ok(self
            .0
            .lock()
            .unwrap()
            .iter()
            .find(|p| p.matches_revision(revision))
            .unwrap()
            .clone())
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
    _guest_runtime: support::guest_runtime::Runtime,
    pub ceiling: latent_core::ResourceBudget,
    pub plan: Arc<CompiledCapabilityPlan>,
    plans: Arc<Plans>,
    pub provider: Arc<latent_capabilities::broker::metrics::MetricProvider>,
    pub telemetry: latent_telemetry::TelemetryHandle,
    pub exporter: Option<latent_telemetry::TelemetryRuntime>,
    pub sink: Arc<latent_telemetry::StructuredLocalSink>,
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
    pub async fn new(limits: latent_capabilities::broker::metrics::MetricActivationLimits) -> Self {
        Self::configured(limits, configuration::config(), None).await
    }
    pub async fn configured(
        limits: latent_capabilities::broker::metrics::MetricActivationLimits,
        config: latent_telemetry::custom::CustomMetricsConfig,
        audit: Option<latent_audit::AuditHandle>,
    ) -> Self {
        Self::with_publication(limits, config, audit, None).await
    }
    #[expect(
        clippy::too_many_lines,
        reason = "real catalog, policy and runtime composition in dependency order"
    )]
    pub async fn with_publication(
        limits: latent_capabilities::broker::metrics::MetricActivationLimits,
        config: latent_telemetry::custom::CustomMetricsConfig,
        audit: Option<latent_audit::AuditHandle>,
        publication: Option<(
            Arc<DirectoryArtifactRepository>,
            latent_core::ReleaseDigest,
            latent_artifacts::ManagedPublicationReceipt,
        )>,
    ) -> Self {
        let required = audit.is_some();
        let ceiling = support::budget();
        let directory = tempfile::TempDir::new().unwrap();
        let mut artifact = support::artifact_bytes(component::bytes(), &[component::CONTRACT]);
        artifact.manifest.execution.resource_budget_ceiling = ceiling;
        artifact.manifest.metadata.tenant = None;
        artifact.manifest.imports.push(ContractImport {
            contract: ContractId(component::CAP.into()),
            optional: false,
        });
        let (catalog, release, receipt) = if let Some(publication) = publication {
            publication
        } else {
            let authority = authority::Authority::new(artifact.clone());
            let catalog = Arc::new(
                DirectoryArtifactRepository::open_enforced(
                    directory.path().join("catalog"),
                    DirectoryArtifactRepositoryConfig::default(),
                    latent_artifacts::AdmissionStorageLimits::default(),
                    authority.clone(),
                )
                .unwrap(),
            );
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
                    ManagedPublicationUpload::Package(authority::upload(&artifact)),
                    &mut |_| Ok(()),
                )
                .await
                .unwrap();
            (catalog, release, receipt)
        };
        let ceiling = catalog
            .fetch(&release)
            .await
            .unwrap()
            .manifest
            .execution
            .resource_budget_ceiling;
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
        let sink =
            Arc::new(
                latent_telemetry::StructuredLocalSink::new(
                    latent_telemetry::LocalSinkConfig::default(),
                )
                .unwrap(),
            );
        let (telemetry, exporter) = latent_telemetry::TelemetryRuntime::spawn(
            latent_telemetry::TelemetryPipelineConfig::default(),
            sink.clone(),
        )
        .unwrap();
        let provider = latent_capabilities::broker::metrics::MetricProvider::install(
            &broker,
            telemetry.clone(),
            1,
            config,
            limits,
        )
        .unwrap();
        configuration::install(
            &policies,
            &publication,
            &provider.reference(),
            required,
            "tests",
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
        let plan = configuration::compile_with_runtime(
            &broker,
            &revision,
            &publication,
            &provider.reference(),
            &guest_runtime,
        );
        let plans = Arc::new(Plans(Mutex::new(vec![plan.clone()])));
        let runtime = Arc::new(ActivationCapabilityRuntime::new(
            broker.clone(),
            plans.clone(),
        ));
        runtime.install_metrics(provider.clone()).unwrap();
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
            _guest_runtime: guest_runtime,
            ceiling,
            plan,
            plans,
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
            telemetry,
            exporter: Some(exporter),
            sink,
            _directory: directory,
        }
    }
    pub fn services(&self) -> WasmtimeHostServices {
        WasmtimeHostServices {
            clock: self.clock.clone(),
            log_sink: None,
            capabilities: Some(self.runtime.clone()),
            currentness_read_wait: Some(Arc::new(latent_node::CurrentnessReadTimer)),
        }
    }
    pub fn request(
        &self,
        id: &str,
        metric: serde_json::Value,
        count: u32,
        mode: u32,
    ) -> (ExecutionRequest, Control) {
        let id = ActivationId(id.into());
        let grant = self.ceiling.clone();
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
            serde_json::to_vec(&serde_json::Value::Array(vec![
                metric,
                count.into(),
                mode.into(),
            ]))
            .unwrap()
            .as_slice(),
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
