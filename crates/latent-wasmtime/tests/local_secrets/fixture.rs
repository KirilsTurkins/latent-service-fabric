use super::{component, support};
use latent_artifacts::{
    ArtifactRepository, LifecycleScope, ManagedPublicationUpload, ReleaseActor, ReleaseActorKind,
    ReleaseMutationContext, ReleaseOperationPrecondition, ReleaseUseEligibility,
};
pub use latent_artifacts::{DirectoryArtifactRepository, DirectoryArtifactRepositoryConfig};
use latent_secrets::{
    LocalSecretProvider, LocalSecretStore, SecretClock, SecretLimits, SecretPurpose, SecretSource,
    SecretSpec,
};
use std::os::unix::fs::PermissionsExt;

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
pub struct Fixture<P = LocalSecretProvider> {
    pub ceiling: latent_core::ResourceBudget,
    _factory: WasmtimeComponentEngineFactory,
    pub backend: WasmtimeBackend,
    pub prepared: PreparedComponent,
    catalog: Arc<DirectoryArtifactRepository>,
    pub policies: Arc<PolicyStore>,
    pub broker: Arc<ActivationCapabilityBroker>,
    _runtime: Arc<ActivationCapabilityRuntime>,
    _clock: Arc<Clock>,
    pub revision: ResolvedRevision,
    pub provider: P,
    pub secrets: LocalSecretStore,
    pub secret_clock: Arc<TestSecretClock>,
    pub gate: Arc<ReadGate>,
    pub plan: Arc<CompiledCapabilityPlan>,
    pub publication: ReleaseUseEligibility,
    pub pools: Arc<ProviderPools>,
    pub io: Arc<IoRuntime>,
    pub directory: tempfile::TempDir,
}
impl Fixture {
    pub async fn new() -> Self {
        Self::configured(None, ProviderPoolLimits::default()).await
    }
    pub async fn configured(
        audit: Option<latent_audit::AuditHandle>,
        pool_limits: ProviderPoolLimits,
    ) -> Self {
        Self::with_provider(
            audit,
            pool_limits,
            latent_secrets::LOCAL_SECRETS_PROFILE,
            |_, _, secrets, _| async move {
                let provider = LocalSecretProvider::install("secrets", 1, 0, &secrets).unwrap();
                let reference = provider.reference();
                (provider, reference)
            },
        )
        .await
    }
}
impl<P: latent_capabilities::broker::secrets::SecretInvoker + Clone + 'static> Fixture<P> {
    pub async fn with_provider<F: std::future::Future<Output = (P, ProviderReference)>>(
        audit: Option<latent_audit::AuditHandle>,
        pool_limits: ProviderPoolLimits,
        profile: &str,
        make: impl FnOnce(
            std::path::PathBuf,
            Arc<ProviderPools>,
            LocalSecretStore,
            Arc<TestSecretClock>,
        ) -> F,
    ) -> Self {
        Self::with_publication(audit, pool_limits, profile, make, None).await
    }
    #[expect(
        clippy::too_many_lines,
        reason = "compose the real catalog, grants, provider and fresh Store with explicit owner lifetimes"
    )]
    pub async fn with_publication<F: std::future::Future<Output = (P, ProviderReference)>>(
        audit: Option<latent_audit::AuditHandle>,
        pool_limits: ProviderPoolLimits,
        profile: &str,
        make: impl FnOnce(
            std::path::PathBuf,
            Arc<ProviderPools>,
            LocalSecretStore,
            Arc<TestSecretClock>,
        ) -> F,
        publication: Option<(
            Arc<DirectoryArtifactRepository>,
            latent_core::ReleaseDigest,
            latent_artifacts::ManagedPublicationReceipt,
        )>,
    ) -> Self {
        let required = audit.is_some();
        let mut ceiling = support::budget();
        ceiling.outbound_requests = 8;
        ceiling.blob_read_bytes = 65536;
        ceiling.blob_write_bytes = 65536;
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
            let mut artifact = support::artifact_bytes(component::bytes(), &[component::CONTRACT]);
            artifact.contracts = super::packages::artifact(&super::packages::capsule()).contracts;
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
        let io = Arc::new(IoRuntime::new(IoLimits::default()).unwrap());
        let pools = Arc::new(
            ProviderPools::new(
                broker.clone(),
                io.clone(),
                tokio::runtime::Handle::current(),
                pool_limits,
            )
            .unwrap(),
        );
        let root = directory.path().join("secrets");
        std::fs::create_dir(&root).unwrap();
        std::fs::set_permissions(&root, std::fs::Permissions::from_mode(0o700)).unwrap();
        write(&root.join("value"), b"Alpha");
        let secret_clock = Arc::new(TestSecretClock {
            now: AtomicUsize::new(1000),
            mono: AtomicUsize::new(1000),
            start: Instant::now(),
            hook: Mutex::new(None),
        });
        let secrets = LocalSecretStore::open(
            pools.clone(),
            root,
            SecretLimits::default(),
            vec![],
            secret_clock.clone(),
        )
        .unwrap()
        .await
        .unwrap();
        secrets.reload(0, specs("1")).unwrap().await.unwrap();
        let (provider, provider_reference) = make(
            directory.path().to_owned(),
            pools.clone(),
            secrets.clone(),
            secret_clock.clone(),
        )
        .await;
        install(
            &policies,
            &publication,
            provider_reference.configuration_digest(),
            required,
            profile,
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
        let plan = broker
            .compile_invocation_plan(
                &revision,
                Some(&latent_core::DeploymentId("secret-deployment".into())),
                &[CapabilityBindingSpec {
                    definition_digest: Some(&latent_artifacts::package::artifact_blob_digest(
                        b"secret-fixture-binding-v1",
                    )),
                    provider: &provider_reference,
                    imported_operations: &["read".into()],
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
        let gate = Arc::new(ReadGate::default());
        runtime
            .install_secrets(Arc::new(GatedProvider {
                provider: provider.clone(),
                gate: gate.clone(),
            }))
            .unwrap();
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
            ceiling,
            _factory: factory,
            backend,
            prepared,
            catalog,
            policies,
            broker,
            _runtime: runtime,
            _clock: clock,
            revision,
            provider,
            secrets,
            secret_clock,
            gate,
            plan,
            publication,
            pools,
            io,
            directory,
        }
    }
    pub fn request(&self, id: &str, method: u32) -> (ExecutionRequest, Control) {
        let id = ActivationId(id.into());
        let grant = self.ceiling.clone();
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
            serde_json::to_vec(&json!([method])).unwrap().as_slice(),
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
    pub fn session(&self, id: &str) -> (CapabilitySession, Control) {
        let (request, control) = self.request(id, 0);
        let session = self
            .broker
            .open_session(self.plan.clone(), &request, &control, &self.publication)
            .unwrap();
        (session, control)
    }
    pub fn revoke(&self) {
        self.policies
            .mutate(
                MutationRequest {
                    tenant: "tests",
                    actor: "operator",
                    id: "p",
                    kind: RecordKind::Policy,
                    operation_id: "revoke-secret",
                    expected_revision: 2,
                    document: None,
                },
                Instant::now() + Duration::from_secs(1),
                |_| Ok(()),
            )
            .unwrap();
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
        let stores_before = self.backend.resource_snapshot().stores_created;
        let before = (
            self.io.snapshot(),
            self.pools.snapshot().unwrap(),
            self.broker.snapshot(),
        );
        let mut resources = support::budget();
        resources.outbound_requests = 8;
        resources.blob_read_bytes = 65536;
        resources.blob_write_bytes = 65536;
        resources.wall_time_limit_millis = Some(5000);
        let deployments = (0..256)
            .map(|i| DeploymentManifest {
                publication: self.revision.publication.clone(),
                api_version: latent_manifest::MANIFEST_API_VERSION.into(),
                id: latent_core::DeploymentId(format!("blob-dormant-{i}")),
                metadata: ObjectMetadata {
                    name: format!("blob-dormant-{i}"),
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
        assert_eq!(
            self.backend.resource_snapshot().stores_created,
            stores_before
        );
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
fn install(
    store: &PolicyStore,
    publication: &ReleaseUseEligibility,
    digest: &str,
    required: bool,
    profile: &str,
) {
    for (id, kind, value) in [
        (
            "p",
            RecordKind::Policy,
            json!({"formatVersion":1,"tenant":"tests","rules":[{
                "id":"allow", "effect":"allow","requireAudit":required,"principals":[{"kind":"service","subject":"generic-test"}],
                "services":["generic"], "publications":[publication.publication().as_str()], "capability":component::CAP,
                "operations":["read"], "resources":{"kind":"secrets","references":["allowed","opaque","tenant-only","expired"]},
                "ceiling":{"operations":1,"inputBytes":65536,"outputBytes":65536,"wallTimeMillis":5000}
            }]}),
        ),
        (
            "binding",
            RecordKind::ProviderBinding,
            json!({"formatVersion":1,"tenant":"tests","capability":component::CAP,
            "providerProfile":profile,"configurationDigest":digest,"configurationEpoch":1,"restriction":{"operations":[]}}),
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

pub struct TestSecretClock {
    pub now: AtomicUsize,
    pub mono: AtomicUsize,
    pub hook: Mutex<Option<Box<dyn FnOnce() + Send>>>,
    start: Instant,
}
impl SecretClock for TestSecretClock {
    fn sample(&self) -> ClockSample {
        let hook = self.hook.lock().unwrap().take();
        if let Some(hook) = hook {
            hook();
        }
        ClockSample::new(
            self.now.load(Ordering::Acquire) as u64,
            self.start + Duration::from_millis(self.mono.load(Ordering::Acquire) as u64),
        )
    }
}
pub fn write(path: &std::path::Path, bytes: &[u8]) {
    std::fs::write(path, bytes).unwrap();
    std::fs::set_permissions(path, std::fs::Permissions::from_mode(0o600)).unwrap();
}
pub fn specs(version: &str) -> Vec<SecretSpec> {
    ["allowed", "opaque", "tenant-only", "expired"]
        .into_iter()
        .map(|name| SecretSpec {
            tenant: TenantId(
                if name == "tenant-only" {
                    "other"
                } else {
                    "tests"
                }
                .into(),
            ),
            reference: name.into(),
            source: SecretSource::File {
                name: "value".into(),
            },
            purpose: if name == "opaque" {
                SecretPurpose::ProviderCredential {
                    provider_id: "http".into(),
                    origin: latent_policy::capability::HttpOrigin {
                        scheme: "http".into(),
                        host: "127.0.0.1".into(),
                        port: 8080,
                    },
                }
            } else {
                SecretPurpose::GuestValue
            },
            media_type: "application/octet-stream".into(),
            version: version.into(),
            expires_at_unix_millis: (name == "expired").then_some(900),
        })
        .collect()
}

#[derive(Default)]
pub struct ReadGate {
    pub armed: AtomicBool,
    pub entered: tokio::sync::Notify,
    pub released: tokio::sync::Notify,
}
struct GatedProvider<P> {
    provider: P,
    gate: Arc<ReadGate>,
}
impl<P: latent_capabilities::broker::secrets::SecretInvoker>
    latent_capabilities::broker::secrets::SecretInvoker for GatedProvider<P>
{
    fn read(
        &self,
        session: &CapabilitySession,
        reference: String,
    ) -> Result<latent_capabilities::broker::secrets::SecretFuture, latent_secrets::SecretError>
    {
        let next = self.provider.read(session, reference)?;
        let gate = self.gate.clone();
        let wait = gate.armed.swap(false, Ordering::AcqRel);
        Ok(Box::pin(async move {
            let value = next.await?;
            if wait {
                gate.entered.notify_one();
                gate.released.notified().await;
            }
            Ok(value)
        }))
    }
}
