use crate::*;
use latent_activation::{ActivationEnvelope, TraceContext};
use latent_artifacts::{
    ArtifactDescriptor, ArtifactRepository, CapsuleArtifact, DirectoryArtifactRepository,
    DirectoryArtifactRepositoryConfig, LifecycleScope, ManagedPublicationReceipt,
    ManagedPublicationUpload, ReleaseActor, ReleaseActorKind, ReleaseMutationContext,
    ReleaseOperationPrecondition, ReleaseUseEligibility,
};
use latent_capabilities::broker::{
    http::HTTP_CAPABILITY,
    io::{IoLimits, IoRuntime},
    pools::{ProviderPoolLimits, ProviderPools},
    ActivationCapabilityBroker, CapabilityBindingSpec, CapabilityBrokerLimits, CapabilitySession,
    CompiledCapabilityPlan,
};
use latent_core::{
    ActivationBudget, ActivationId, ArtifactReference, CapabilityId, CellId, ClockSample,
    ContractId, EffectiveActivationBudget, FunctionId, InvocationPrincipal, Metadata,
    PrincipalKind, ResourceBudget, RevisionId, RouteGeneration, ServiceId, SpanId,
    SystemActivationClock, TenantId, TraceId,
};
use latent_executor::{
    BoundImport, ExecutionCancellation, ExecutionCancellationProbe, ExecutionCell,
    ExecutionRequest, PreparationKey, PreparedComponent,
};
use latent_manifest::{JsonManifestCodec, ManifestCodec};
use latent_policy::capability::{MutationRequest, PolicyStore, PolicyStoreLimits, RecordKind};
use latent_routing::{InvocationTarget, ResolvedRevision};
use serde_json::json;
use std::{
    future::Future,
    sync::{
        atomic::{AtomicBool, Ordering},
        Arc,
    },
    task::{Context, Poll, Waker},
    time::{Duration, Instant},
};
use tempfile::TempDir;

pub fn ready<T>(future: impl Future<Output = T>) -> T {
    let mut future = Box::pin(future);
    match future
        .as_mut()
        .poll(&mut Context::from_waker(Waker::noop()))
    {
        Poll::Ready(value) => value,
        Poll::Pending => panic!("synchronous fixture unexpectedly waited"),
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
pub const CAP: &str = HTTP_CAPABILITY;
pub struct Fixture {
    pub broker: Arc<ActivationCapabilityBroker>,
    pub provider: HttpProvider,
    pub io: Arc<IoRuntime>,
    pub pools: Arc<ProviderPools>,
    pub plan: Arc<CompiledCapabilityPlan>,
    pub policies: Arc<PolicyStore>,
    _catalog: DirectoryArtifactRepository,
    pub publication: ReleaseUseEligibility,
    pub revision: ResolvedRevision,
    pub _dir: TempDir,
}
impl Fixture {
    pub fn new(config: HttpProviderConfig) -> Self {
        Self::configured(config, &[], ProviderPoolLimits::default(), None)
    }
    #[expect(
        clippy::too_many_lines,
        reason = "one explicit catalog, policy, broker and pool composition"
    )]
    pub fn configured(
        config: HttpProviderConfig,
        credentials: &[HttpCredential<'_>],
        pool_limits: ProviderPoolLimits,
        audit: Option<latent_audit::AuditHandle>,
    ) -> Self {
        let dir = TempDir::new().unwrap();
        let catalog = DirectoryArtifactRepository::open(
            dir.path().join("artifacts"),
            DirectoryArtifactRepositoryConfig::default(),
        )
        .unwrap();
        let receipt = publish(&catalog, "first", "a");
        let publication = catalog
            .execution_eligibility_selected(
                &receipt.operation.record.as_ref().unwrap().release,
                Some(&receipt.publication.id),
            )
            .unwrap()
            .unwrap();
        let policies = Arc::new(
            PolicyStore::open(
                &dir.path().join("policies"),
                PolicyStoreLimits::default(),
                catalog.lifecycle_authority(),
            )
            .unwrap(),
        );
        let mut broker = ActivationCapabilityBroker::new(
            catalog.lifecycle_authority(),
            policies.clone(),
            Arc::new(SystemActivationClock),
            CapabilityBrokerLimits {
                maximum_input_bytes: 1024 * 1024,
                maximum_output_bytes: 1024 * 1024,
                ..CapabilityBrokerLimits::default()
            },
        )
        .unwrap();
        let required = audit.is_some();
        if let Some(audit) = audit {
            broker = broker.with_audit(audit, false).unwrap();
        }
        let broker = Arc::new(broker);
        let io = Arc::new(
            IoRuntime::new(IoLimits {
                maximum_chunk_bytes: 1024 * 1024,
                ..IoLimits::default()
            })
            .unwrap(),
        );
        let pools = Arc::new(
            ProviderPools::new(
                broker.clone(),
                io.clone(),
                tokio::runtime::Handle::current(),
                pool_limits,
            )
            .unwrap(),
        );
        let origins: Vec<_> = config
            .destinations
            .iter()
            .map(|d| d.origin.clone())
            .collect();
        let provider =
            HttpProvider::install(pools.clone(), "http", 1, 0, config, credentials).unwrap();
        let reference = provider.reference();
        let policy = json!({"formatVersion":1,"tenant":"a","rules":[{
            "id":"allow","effect":"allow","principals":[{"kind":"user","subject":"alice"}],
            "services":["echo"],"publications":[publication.publication().as_str()],"capability":CAP,
            "operations":["send"],"resources":{"kind":"http","origins":origins,"methods":["GET","HEAD","POST","PUT","PATCH","DELETE","OPTIONS"],"paths":["/allowed"],"pathPrefixes":["/allowed/"]},
            "requireAudit":required,"ceiling":{"operations":32,"inputBytes":1_048_576,"outputBytes":1_048_576,"wallTimeMillis":30000}
        }]});
        let binding = json!({"formatVersion":1,"tenant":"a","capability":CAP,"providerProfile":HTTP_PROVIDER_PROFILE,"configurationDigest":reference.configuration_digest(),"configurationEpoch":1,"restriction":{"operations":[]}});
        for (id, kind, value) in [
            ("p", RecordKind::Policy, policy),
            ("binding", RecordKind::ProviderBinding, binding),
        ] {
            let bytes = serde_json::to_vec(&value).unwrap();
            policies
                .mutate(
                    MutationRequest {
                        tenant: "a",
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
        let revision = revision(&publication);
        let plan = broker
            .compile_invocation_plan(
                &revision,
                Some(&latent_core::DeploymentId("http-deployment".into())),
                &[CapabilityBindingSpec {
                    definition_digest: Some(&latent_artifacts::package::artifact_blob_digest(
                        b"http-fixture-binding-v1",
                    )),
                    provider: &reference,
                    imported_operations: &["send".into()],
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
        Self {
            broker,
            provider,
            io,
            pools,
            plan,
            policies,
            _catalog: catalog,
            publication,
            revision,
            _dir: dir,
        }
    }
    pub fn session(&self, millis: u64) -> (CapabilitySession, Control) {
        let (request, control) = self.request("http-test", millis);
        let session = self
            .broker
            .open_session(self.plan.clone(), &request, &control, &self.publication)
            .unwrap();
        (session, control)
    }
    pub async fn clean(&self) {
        let snapshot = self
            .pools
            .shutdown(Instant::now() + Duration::from_secs(2))
            .await
            .unwrap();
        assert!(snapshot.is_clean(), "{snapshot:?}");
        assert_eq!(
            self.io.snapshot(),
            latent_capabilities::broker::io::IoSnapshot::default()
        );
    }
    pub fn request(&self, id: &str, millis: u64) -> (ExecutionRequest, Control) {
        let grant = ResourceBudget {
            cpu_fuel: 100_000,
            memory_bytes: 1024 * 1024,
            wall_time_limit_millis: Some(millis),
            log_bytes: 1024,
            child_calls: 0,
            outbound_requests: 32,
            state_read_bytes: 0,
            state_write_bytes: 0,
            blob_read_bytes: 0,
            blob_write_bytes: 0,
            effect_count: 0,
        };
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
        let id = ActivationId(id.into());
        let request = ExecutionRequest {
            activation: ActivationEnvelope {
                activation_id: id.clone(),
                parent_activation_id: None,
                root_activation_id: id.clone(),
                principal: InvocationPrincipal {
                    subject: "alice".into(),
                    kind: PrincipalKind::User,
                    tenant: Some(TenantId("a".into())),
                    service: None,
                    claims: Metadata::new(),
                },
                target: self.revision.target.clone(),
                resolved_revision: Some(self.revision.clone()),
                deadline_unix_millis: budget.deadline().unix_millis(),
                priority: 0,
                trace: TraceContext {
                    trace_id: TraceId("1".repeat(32)),
                    span_id: SpanId("2".repeat(16)),
                    trace_flags: 0,
                    baggage: Metadata::new(),
                },
                idempotency_key: None,
                retry_attempt: 0,
                budget: grant.clone(),
                metadata: Metadata::new(),
                input: Vec::new(),
                input_media_type: "application/json".into(),
            },
            prepared: PreparedComponent {
                key: PreparationKey {
                    release: self.publication.release().clone(),
                    publication: Some(self.publication.publication().clone()),
                    engine_version: "test".into(),
                    engine_configuration_digest: "test".into(),
                    target_triple: "test".into(),
                    cpu_feature_set: "test".into(),
                },
                backend: "test".into(),
                opaque_handle: "descriptive".into(),
                metadata: Metadata::new(),
            },
            cell: ExecutionCell {
                id: CellId("reused-cell".into()),
                class: "generic".into(),
                maximum_memory_bytes: grant.memory_bytes,
                metadata: Metadata::new(),
            },
            imports: vec![BoundImport {
                capability: CapabilityId(CAP.into()),
                contract: CAP.into(),
                opaque_handle: "not-authority".into(),
            }],
            budget: grant,
        };
        (
            request,
            Control {
                id,
                budget,
                probe: Arc::new(Probe(AtomicBool::new(false))),
            },
        )
    }
}
pub fn context(id: &str, tenant: &str, generation: u64) -> ReleaseMutationContext {
    ReleaseMutationContext {
        scope: LifecycleScope::Tenant(TenantId(tenant.into())),
        actor: ReleaseActor {
            subject: "operator".into(),
            kind: ReleaseActorKind::Administrator,
        },
        operation: Some(ReleaseOperationPrecondition {
            operation_id: id.into(),
            expected_generation: generation,
        }),
    }
}
pub fn publish(
    catalog: &DirectoryArtifactRepository,
    label: &str,
    tenant: &str,
) -> ManagedPublicationReceipt {
    // Valid empty Component Model bytes: authority tests do not claim execution.
    let component_bytes = b"\0asm\r\0\x01\0".to_vec();
    let digest = latent_artifacts::content_digest(&component_bytes);
    let mut value: serde_json::Value = serde_json::from_str(include_str!(concat!(
        env!("CARGO_MANIFEST_DIR"),
        "/../latent-manifest/tests/fixtures/valid-capsule-v1alpha1.json"
    )))
    .unwrap();
    value["component"]["digest"] = digest.0.clone().into();
    value["metadata"]["tenant"] = tenant.into();
    value["metadata"]["name"] = format!("{tenant}/echo").into();
    value["component"]["world"] = format!("{tenant}:echo/service@0.1.0").into();
    value["exports"] = json!([format!("{tenant}:echo/api@0.1.0")]);
    let artifact = CapsuleArtifact {
        descriptor: ArtifactDescriptor {
            reference: ArtifactReference(format!("local://tests/{label}")),
            release_digest: digest,
            media_type: "application/vnd.wasm.component.v1+wasm".into(),
            size_bytes: component_bytes.len() as u64,
            publisher: None,
            layers: vec![],
            annotations: Metadata::new(),
        },
        manifest: JsonManifestCodec::default()
            .decode_capsule(&serde_json::to_vec(&value).unwrap())
            .unwrap(),
        contracts: vec![],
        component_bytes,
    };
    ready(catalog.publish_managed(
        context(label, tenant, 0),
        ManagedPublicationUpload::Local(artifact),
        &mut |_| Ok(()),
    ))
    .unwrap()
}

fn revision(publication: &ReleaseUseEligibility) -> ResolvedRevision {
    ResolvedRevision {
        target: InvocationTarget {
            tenant: TenantId("a".into()),
            service: ServiceId("echo".into()),
            contract: ContractId("a:echo/api@0.1.0".into()),
            function: FunctionId("echo".into()),
            route: None,
        },
        revision: RevisionId("rev-1".into()),
        release: publication.release().clone(),
        publication: Some(publication.publication().clone()),
        route_generation: RouteGeneration(1),
        attributes: Metadata::new(),
    }
}
