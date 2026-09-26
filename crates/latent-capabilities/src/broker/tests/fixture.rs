use super::*;
use latent_activation::{ActivationEnvelope, TraceContext};
use latent_artifacts::{
    ArtifactDescriptor, ArtifactRepository, CapsuleArtifact, DirectoryArtifactRepository,
    DirectoryArtifactRepositoryConfig, LifecycleScope, ManagedPublicationReceipt,
    ManagedPublicationUpload, ReleaseActor, ReleaseActorKind, ReleaseMutationContext,
    ReleaseOperationPrecondition, ReleaseUseEligibility,
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
    pin::Pin,
    sync::{
        atomic::{AtomicBool, Ordering},
        Arc,
    },
    task::{Context, Poll, Waker},
    time::{Duration, Instant},
};
use tempfile::TempDir;

pub const CAP: &str = "latent:secrets/reader@0.1.0";
pub fn resource() -> ResourceTarget<'static> {
    ResourceTarget::Secrets {
        reference: "test-key",
    }
}
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
pub fn pending<F: Future>(future: Pin<&mut F>) {
    assert!(future
        .poll(&mut Context::from_waker(Waker::noop()))
        .is_pending());
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
    pub broker: Arc<ActivationCapabilityBroker>,
    pub provider: ProviderRegistration,
    pub plan: Arc<CompiledCapabilityPlan>,
    pub policies: Arc<PolicyStore>,
    pub catalog: DirectoryArtifactRepository,
    pub publication: ReleaseUseEligibility,
    pub revision: ResolvedRevision,
    pub _dir: TempDir,
}
impl Fixture {
    pub fn new(limits: CapabilityBrokerLimits) -> Self {
        Self::with_minimum(limits, &[])
    }
    pub fn with_minimum(
        limits: CapabilityBrokerLimits,
        minimum_call_charges: &[ProviderBudgetRequirement<'_>],
    ) -> Self {
        Self::configured(
            limits,
            minimum_call_charges,
            None,
            false,
            false,
            Arc::new(SystemActivationClock),
        )
    }
    pub fn audited(
        limits: CapabilityBrokerLimits,
        audit: latent_audit::AuditHandle,
        required: bool,
        observations: bool,
    ) -> Self {
        Self::configured(
            limits,
            &[],
            Some(audit),
            required,
            observations,
            Arc::new(SystemActivationClock),
        )
    }
    pub fn with_activation_clock(clock: Arc<dyn latent_core::ActivationClock>) -> Self {
        Self::configured(
            CapabilityBrokerLimits::default(),
            &[],
            None,
            false,
            false,
            clock,
        )
    }
    fn configured(
        limits: CapabilityBrokerLimits,
        minimum_call_charges: &[ProviderBudgetRequirement<'_>],
        audit: Option<latent_audit::AuditHandle>,
        required: bool,
        observations: bool,
        clock: Arc<dyn latent_core::ActivationClock>,
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
        let mut document = json!({"formatVersion":1,"tenant":"a","rules":[{
            "id":"allow","effect":"allow","principals":[{"kind":"user","subject":"alice"}],
            "services":["echo"],"publications":[publication.publication().as_str()],"capability":CAP,
            "operations":["read"],"resources":{"kind":"secrets","references":["test-key"]},
            "ceiling":{"operations":4,"inputBytes":128,"outputBytes":256,"wallTimeMillis":5000}
        }]});
        if required {
            document["rules"][0]["requireAudit"] = true.into();
        }
        let digest = format!("sha256:{}", "2".repeat(64));
        for (id, kind, value) in [
            ("p", RecordKind::Policy, document),
            (
                "binding",
                RecordKind::ProviderBinding,
                json!({"formatVersion":1,"tenant":"a","capability":CAP,"providerProfile":"local-secrets-v1",
                "configurationDigest":digest,"configurationEpoch":1,"restriction":{"operations":[]}}),
            ),
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
        let broker = ActivationCapabilityBroker::new(
            catalog.lifecycle_authority(),
            policies.clone(),
            clock,
            limits,
        )
        .unwrap();
        let broker = Arc::new(match audit {
            Some(audit) => broker.with_audit(audit, observations).unwrap(),
            None => broker,
        });
        let provider = broker
            .register_provider(ProviderConfiguration {
                capability: CAP,
                profile: "local-secrets-v1",
                configuration_digest: &digest,
                configuration_epoch: 1,
                restriction_json: br#"{"operations":[]}"#,
                minimum_call_charges,
            })
            .unwrap();
        let revision = revision(&publication);
        let plan = broker
            .compile_invocation_plan(
                &revision,
                Some(&latent_core::DeploymentId("echo-deployment".into())),
                &[CapabilityBindingSpec {
                    definition_digest: Some(&latent_artifacts::package::artifact_blob_digest(
                        b"fixture local secrets binding v1",
                    )),
                    provider: &provider.reference(),
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
        Self {
            broker,
            provider,
            plan,
            policies,
            catalog,
            publication,
            revision,
            _dir: dir,
        }
    }
    pub fn request(&self, id: &str) -> (ExecutionRequest, Control) {
        let grant = ResourceBudget {
            cpu_fuel: 100_000,
            memory_bytes: 1024 * 1024,
            wall_time_limit_millis: Some(30_000),
            log_bytes: 1024,
            child_calls: 0,
            outbound_requests: 0,
            state_read_bytes: 0,
            state_write_bytes: 0,
            blob_read_bytes: 0,
            blob_write_bytes: 0,
            effect_count: 0,
        };
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
    pub fn session(&self, request: &ExecutionRequest, control: &Control) -> CapabilitySession {
        self.broker
            .open_session(self.plan.clone(), request, control, &self.publication)
            .unwrap()
    }
    pub fn revoke_policy(&self) {
        self.policies
            .mutate(
                MutationRequest {
                    tenant: "a",
                    actor: "operator",
                    id: "p",
                    kind: RecordKind::Policy,
                    operation_id: "revoke",
                    expected_revision: 2,
                    document: None,
                },
                Instant::now() + Duration::from_secs(10),
                |_| Ok(()),
            )
            .unwrap();
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
