//! Actual node broker/catalog and TCP ownership for the native drain control.
//! The empty local publication supplies real sealed authority, not execution
//! qualification; admitted component evidence belongs to the signed cases.
use crate::standalone::{start::Catalogs, RuntimeThreads, StandaloneNode};
use latent_activation::{ActivationEnvelope, TraceContext};
use latent_artifacts::{
    ArtifactDescriptor, ArtifactRepository, CapsuleArtifact, DirectoryArtifactRepository,
    LifecycleScope, ManagedPublicationUpload, ReleaseActor, ReleaseActorKind,
    ReleaseMutationContext, ReleaseOperationPrecondition,
};
use latent_capabilities::broker::{CapabilityBindingSpec, CapabilitySession};
use latent_core::{
    ActivationBudget, ActivationId, ArtifactReference, BudgetProfile, CapabilityId, CellId,
    ClockSample, ContractId, DeploymentId, EffectiveActivationBudget, FunctionId,
    InvocationPrincipal, Metadata, PrincipalKind, ResourceBudget, RevisionId, RouteGeneration,
    ServiceId, SpanId, TenantId, TraceId,
};
use latent_executor::{
    BoundImport, ExecutionCancellation, ExecutionCancellationProbe, ExecutionCell,
    ExecutionRequest, PreparationKey, PreparedComponent,
};
use latent_manifest::{JsonManifestCodec, ManifestCodec};
use latent_policy::capability::{MutationRequest, RecordKind, StreamEndpoint};
use latent_routing::{InvocationTarget, ResolvedRevision};
use serde_json::json;
use std::{
    sync::Arc,
    time::{Duration, Instant},
};
use tokio::runtime::Runtime;

const CAPABILITY: &str = latent_capabilities::broker::network::STREAM_CAPABILITY;
const OPERATIONS: [&str; 8] = [
    "connect",
    "read",
    "write",
    "ready",
    "inspect",
    "shutdown",
    "close",
    "chunk-bytes",
];

pub(super) struct Control {
    id: ActivationId,
    pub budget: ActivationBudget,
}
struct Probe;
impl ExecutionCancellationProbe for Probe {
    fn is_cancelled(&self) -> bool {
        false
    }
    fn reason(&self) -> Option<String> {
        None
    }
}
impl ExecutionCancellation for Control {
    fn activation_id(&self) -> &ActivationId {
        &self.id
    }
    fn is_cancelled(&self) -> bool {
        false
    }
    fn reason(&self) -> Option<String> {
        None
    }
    fn budget_accounting(&self) -> Option<&ActivationBudget> {
        Some(&self.budget)
    }
    fn probe(&self) -> Option<Arc<dyn ExecutionCancellationProbe>> {
        Some(Arc::new(Probe))
    }
}

pub(super) fn node(
    fixture: &super::Fixture,
    control: &Runtime,
    invocation: &Runtime,
) -> (StandaloneNode, Arc<DirectoryArtifactRepository>) {
    let settings = fixture.settings();
    let catalogs = invocation
        .block_on(Catalogs::open_with_control(&settings, control.handle()))
        .unwrap();
    let artifacts = catalogs.artifacts.clone();
    let node = invocation
        .block_on(StandaloneNode::start_with_catalogs(
            settings,
            catalogs,
            control.handle().clone(),
            RuntimeThreads::default(),
        ))
        .unwrap();
    (node, artifacts)
}

#[expect(
    clippy::too_many_lines,
    reason = "one explicit real publication/policy/budget owner supplies the physical native control"
)]
pub(super) async fn session(
    node: &StandaloneNode,
    artifacts: &DirectoryArtifactRepository,
    endpoint: StreamEndpoint,
) -> (CapabilitySession, Control) {
    let component_bytes = b"\0asm\r\0\x01\0".to_vec();
    let digest = latent_artifacts::content_digest(&component_bytes);
    let mut manifest: serde_json::Value = serde_json::from_str(include_str!(concat!(
        env!("CARGO_MANIFEST_DIR"),
        "/../../crates/latent-manifest/tests/fixtures/valid-capsule-v1alpha1.json"
    )))
    .unwrap();
    manifest["component"]["digest"] = json!(digest.0);
    manifest["metadata"]["tenant"] = json!("tests");
    manifest["metadata"]["name"] = json!("tests/guest-stream");
    manifest["component"]["world"] = json!("tests:guest-stream/service@0.1.0");
    manifest["exports"] = json!(["tests:guest-stream/api@0.1.0"]);
    let artifact = CapsuleArtifact {
        descriptor: ArtifactDescriptor {
            reference: ArtifactReference("local://tests/stream-control-native".into()),
            release_digest: digest,
            media_type: "application/vnd.wasm.component.v1+wasm".into(),
            size_bytes: component_bytes.len() as u64,
            publisher: None,
            layers: vec![],
            annotations: Metadata::new(),
        },
        manifest: JsonManifestCodec::default()
            .decode_capsule(&serde_json::to_vec(&manifest).unwrap())
            .unwrap(),
        contracts: vec![],
        component_bytes,
    };
    let receipt = artifacts
        .publish_managed(
            ReleaseMutationContext {
                scope: LifecycleScope::Tenant(TenantId("tests".into())),
                actor: ReleaseActor {
                    subject: "operator".into(),
                    kind: ReleaseActorKind::Administrator,
                },
                operation: Some(ReleaseOperationPrecondition {
                    operation_id: "stream-control-native".into(),
                    expected_generation: 0,
                }),
            },
            ManagedPublicationUpload::Local(artifact),
            &mut |_| Ok(()),
        )
        .await
        .unwrap();
    let publication = artifacts
        .execution_eligibility_selected(
            &receipt.operation.record.as_ref().unwrap().release,
            Some(&receipt.publication.id),
        )
        .unwrap()
        .unwrap();
    let owner = node.providers.as_ref().unwrap();
    let reference = owner.stream_binding_reference.as_ref().unwrap();
    let policies = node.policies.as_ref().unwrap().handle();
    for (id, kind, value) in [
        (
            "physical-policy",
            RecordKind::Policy,
            json!({"formatVersion":1,"tenant":"tests","rules":[{
            "id":"physical","effect":"allow","principals":[{"kind":"user","subject":"alice"}],
            "services":["guest-stream"],"publications":[publication.publication().as_str()],"capability":CAPABILITY,
            "operations":OPERATIONS,"resources":{"kind":"stream","endpoints":[endpoint]},"requireAudit":true,
            "ceiling":{"operations":128,"inputBytes":1048576,"outputBytes":1048576,"wallTimeMillis":10000}}]}),
        ),
        (
            "physical-binding",
            RecordKind::ProviderBinding,
            json!({"formatVersion":1,"tenant":"tests",
            "capability":CAPABILITY,"providerProfile":latent_capabilities::broker::network::STREAM_PROFILE,
            "configurationDigest":reference.configuration_digest(),"configurationEpoch":reference.configuration_epoch(),
            "restriction":{"operations":OPERATIONS}}),
        ),
    ] {
        let bytes = serde_json::to_vec(&value).unwrap();
        policies
            .store()
            .mutate(
                MutationRequest {
                    tenant: "tests",
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
    let revision = ResolvedRevision {
        target: InvocationTarget {
            tenant: TenantId("tests".into()),
            service: ServiceId("guest-stream".into()),
            contract: ContractId("tests:guest-stream/api@0.1.0".into()),
            function: FunctionId("echo".into()),
            route: None,
        },
        revision: RevisionId("physical-1".into()),
        release: publication.release().clone(),
        publication: Some(publication.publication().clone()),
        route_generation: RouteGeneration(1),
        attributes: Metadata::new(),
    };
    let broker = owner.runtime.broker();
    let definition =
        latent_artifacts::package::artifact_blob_digest(b"stream-control-physical-binding-v1");
    let plan = broker
        .compile_invocation_plan(
            &revision,
            Some(&DeploymentId("physical-stream".into())),
            &[CapabilityBindingSpec {
                definition_digest: Some(&definition),
                provider: reference,
                imported_operations: &OPERATIONS.map(str::to_owned),
                policy_ids: &["physical-policy".into()],
                provider_binding_id: "physical-binding",
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
    let grant = ResourceBudget {
        cpu_fuel: 100_000,
        memory_bytes: 1024 * 1024,
        wall_time_limit_millis: Some(5000),
        log_bytes: 1024,
        child_calls: 0,
        outbound_requests: 8,
        state_read_bytes: 0,
        state_write_bytes: 0,
        blob_read_bytes: 0,
        blob_write_bytes: 0,
        effect_count: 0,
    };
    let budget = ActivationBudget::with_profile(
        EffectiveActivationBudget::admit_profile_at(
            BudgetProfile::Phase3,
            &grant,
            &grant,
            &grant,
            None,
            ClockSample::system_now(),
        )
        .unwrap(),
        BudgetProfile::Phase3,
    )
    .unwrap();
    let id = ActivationId("physical-stream".into());
    let control = Control {
        id: id.clone(),
        budget,
    };
    let request = ExecutionRequest {
        activation: ActivationEnvelope {
            activation_id: id.clone(),
            root_activation_id: id,
            parent_activation_id: None,
            principal: InvocationPrincipal {
                subject: "alice".into(),
                kind: PrincipalKind::User,
                tenant: Some(TenantId("tests".into())),
                service: None,
                claims: Metadata::new(),
            },
            target: revision.target.clone(),
            resolved_revision: Some(revision),
            deadline_unix_millis: control.budget.deadline().unix_millis(),
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
            input: vec![],
            input_media_type: "application/json".into(),
        },
        prepared: PreparedComponent {
            key: PreparationKey {
                release: publication.release().clone(),
                publication: Some(publication.publication().clone()),
                engine_version: "native-owner-control".into(),
                engine_configuration_digest: "native-owner-control".into(),
                target_triple: "native-owner-control".into(),
                cpu_feature_set: "native-owner-control".into(),
            },
            backend: "native-owner-control".into(),
            opaque_handle: "descriptive-only".into(),
            metadata: Metadata::new(),
        },
        cell: ExecutionCell {
            id: CellId("physical-cell".into()),
            class: "generic".into(),
            maximum_memory_bytes: grant.memory_bytes,
            metadata: Metadata::new(),
        },
        imports: vec![BoundImport {
            capability: CapabilityId(CAPABILITY.into()),
            contract: CAPABILITY.into(),
            opaque_handle: "not-authority".into(),
        }],
        budget: grant,
    };
    (
        broker
            .open_session(plan, &request, &control, &publication)
            .unwrap(),
        control,
    )
}
