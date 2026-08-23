use std::env;
use std::fs;
use std::path::PathBuf;

use latent_activation::{ActivationEnvelope, TraceContext};
use latent_artifacts::{ArtifactDescriptor, CapsuleArtifact};
use latent_core::{
    ActivationId, ArtifactReference, CapabilityId, CellId, ContractId, FunctionId,
    InvocationPrincipal, Metadata, PlatformErrorCode, PrincipalKind, ReleaseDigest, ResourceBudget,
    ServiceId, SpanId, TenantId, TraceId,
};
use latent_executor::{
    BoundImport, ExecutionBackend, ExecutionCancellation, ExecutionCell, ExecutionRequest,
    GuestOutcome,
};
use latent_manifest::{
    CapsuleManifest, ContractExport, ContractImport, ExecutionBackendKind, ExecutionRequirements,
    ObjectMetadata, StateModel, ThreadingModel,
};
use latent_routing::InvocationTarget;
use latent_wasmtime::{
    Phase0WasmtimeConfig, Phase0WasmtimeEngineFactory, CONTEXT_IMPORT,
    ECHO_DOMAIN_ERROR_MEDIA_TYPE, ECHO_EXPORT, ECHO_SUCCESS_MEDIA_TYPE, ECHO_WORLD, LOG_IMPORT,
};
use serde_json::Value;
use sha2::{Digest, Sha256};

const MAX_MESSAGE_BYTES: usize = 64 * 1024;
const OVERSIZED_HOSTCALL_MESSAGE_BYTES: usize = 128 * 1024;

#[derive(Debug)]
struct NeverCancelled {
    activation_id: ActivationId,
}

impl ExecutionCancellation for NeverCancelled {
    fn activation_id(&self) -> &ActivationId {
        &self.activation_id
    }

    fn is_cancelled(&self) -> bool {
        false
    }

    fn reason(&self) -> Option<String> {
        None
    }
}

#[tokio::test(flavor = "current_thread")]
#[ignore = "requires the component and capsule metadata produced by tools/build_echo_capsule.py"]
async fn invokes_echo_through_the_execution_backend_and_enforces_the_phase_zero_boundary() {
    let artifact = load_issue19_artifact();
    let invocation_budget = artifact.manifest.execution.resource_budget_ceiling.clone();

    let config = Phase0WasmtimeConfig {
        maximum_memory_bytes: 8 * 1024 * 1024,
        prepared_cache_maximum_entries: 2,
        ..Phase0WasmtimeConfig::default()
    };
    let factory = Phase0WasmtimeEngineFactory::new(config.clone()).expect("factory must build");
    let backend = factory.create_backend_instance();
    let key = factory.preparation_key(artifact.descriptor.release_digest.clone());

    let prepared = backend
        .prepare(&artifact, &key)
        .await
        .expect("Issue #19 echo artifact must prepare");
    assert_eq!(
        prepared.metadata.get("world").map(String::as_str),
        Some(ECHO_WORLD)
    );
    assert_eq!(
        prepared
            .metadata
            .get("ambient-authority")
            .map(String::as_str),
        Some("none")
    );
    assert_eq!(backend.cache_snapshot().entries, 1);

    let success_activation = ActivationId("activation-success".to_owned());
    let success = backend
        .invoke(
            request(
                prepared.clone(),
                success_activation.clone(),
                "hello from Wasmtime".to_owned(),
                &invocation_budget,
            ),
            &NeverCancelled {
                activation_id: success_activation.clone(),
            },
        )
        .await
        .expect("echo invocation must complete");
    assert_returned(success, b"hello from Wasmtime", ECHO_SUCCESS_MEDIA_TYPE);

    let maximum_message = "m".repeat(MAX_MESSAGE_BYTES);
    let maximum_activation = ActivationId("activation-maximum".to_owned());
    let maximum = backend
        .invoke(
            request(
                prepared.clone(),
                maximum_activation.clone(),
                maximum_message.clone(),
                &invocation_budget,
            ),
            &NeverCancelled {
                activation_id: maximum_activation.clone(),
            },
        )
        .await
        .expect("the exact 64 KiB echo boundary must complete");
    assert_returned(maximum, maximum_message.as_bytes(), ECHO_SUCCESS_MEDIA_TYPE);

    let empty_activation = ActivationId("activation-empty".to_owned());
    let empty = backend
        .invoke(
            request(
                prepared.clone(),
                empty_activation.clone(),
                String::new(),
                &invocation_budget,
            ),
            &NeverCancelled {
                activation_id: empty_activation.clone(),
            },
        )
        .await
        .expect("declared empty-message result must complete");
    assert_returned(
        empty,
        br#"{"error":"empty-message"}"#,
        ECHO_DOMAIN_ERROR_MEDIA_TYPE,
    );

    let oversized_activation = ActivationId("activation-oversized".to_owned());
    let oversized = backend
        .invoke(
            request(
                prepared.clone(),
                oversized_activation.clone(),
                "x".repeat(MAX_MESSAGE_BYTES + 1),
                &invocation_budget,
            ),
            &NeverCancelled {
                activation_id: oversized_activation.clone(),
            },
        )
        .await
        .expect("declared message-too-large result must complete");
    assert_returned(
        oversized,
        br#"{"error":"message-too-large"}"#,
        ECHO_DOMAIN_ERROR_MEDIA_TYPE,
    );

    assert_eq!(backend.stores_created(), 4);
    for activation_id in [
        success_activation,
        maximum_activation,
        empty_activation,
        oversized_activation,
    ] {
        let logs = backend.log_sink().snapshot_for(&activation_id);
        assert_eq!(
            logs.len(),
            1,
            "each fresh host state publishes one guest log"
        );
        assert_eq!(logs[0].fields.get("activation_id"), Some(&activation_id.0));
    }

    let mut unexpected_world = artifact.clone();
    unexpected_world.manifest.world = ContractId("examples:other/service@0.1.0".to_owned());
    let error = backend
        .prepare(&unexpected_world, &key)
        .await
        .expect_err("unexpected world must be rejected");
    assert_eq!(error.code, PlatformErrorCode::IncompatibleContract);

    let mut missing_export = artifact.clone();
    missing_export.manifest.exports.clear();
    let error = backend
        .prepare(&missing_export, &key)
        .await
        .expect_err("missing echo export must be rejected");
    assert_eq!(error.code, PlatformErrorCode::IncompatibleContract);

    let mut unresolved_import = artifact.clone();
    unresolved_import.manifest.imports.push(ContractImport {
        contract: ContractId("latent:random/random@0.1.0".to_owned()),
        optional: false,
    });
    let error = backend
        .prepare(&unresolved_import, &key)
        .await
        .expect_err("undeclared host authority must be rejected");
    assert_eq!(error.code, PlatformErrorCode::IncompatibleContract);

    let mut invalid = artifact.clone();
    invalid.component_bytes = vec![0, 1, 2, 3];
    invalid.manifest.component_digest = ReleaseDigest(component_digest(&invalid.component_bytes));
    let error = backend
        .prepare(&invalid, &key)
        .await
        .expect_err("invalid component bytes must be rejected");
    assert_eq!(error.code, PlatformErrorCode::CorruptArtifact);

    let mut excessive = artifact.clone();
    excessive
        .manifest
        .execution
        .resource_budget_ceiling
        .memory_bytes = config.maximum_memory_bytes + 1;
    let error = backend
        .prepare(&excessive, &key)
        .await
        .expect_err("excessive declared limits must be rejected");
    assert_eq!(error.code, PlatformErrorCode::ResourceExhausted);

    let activation_id = ActivationId("activation-unbound".to_owned());
    let mut unbound = request(
        prepared,
        activation_id.clone(),
        "unbound".to_owned(),
        &invocation_budget,
    );
    unbound.imports.pop();
    let error = backend
        .invoke(unbound, &NeverCancelled { activation_id })
        .await
        .expect_err("missing host import binding must be rejected");
    assert_eq!(error.code, PlatformErrorCode::IncompatibleContract);
}

#[tokio::test(flavor = "current_thread")]
#[ignore = "requires the component and capsule metadata produced by tools/build_echo_capsule.py"]
async fn prepared_state_is_entry_bounded_and_evicts_without_retaining_an_instance() {
    let base_artifact = load_issue19_artifact();
    let invocation_budget = base_artifact
        .manifest
        .execution
        .resource_budget_ceiling
        .clone();

    let config = Phase0WasmtimeConfig {
        prepared_cache_maximum_entries: 1,
        ..Phase0WasmtimeConfig::default()
    };
    let factory = Phase0WasmtimeEngineFactory::new(config).expect("factory must build");
    let backend = factory.create_backend_instance();

    let first_release = ReleaseDigest("sha256:phase-zero-echo-release-a".to_owned());
    let first_artifact = with_release(base_artifact.clone(), first_release.clone());
    let first = backend
        .prepare(&first_artifact, &factory.preparation_key(first_release))
        .await
        .expect("first component must prepare");

    let second_release = ReleaseDigest("sha256:phase-zero-echo-release-b".to_owned());
    let second_artifact = with_release(base_artifact, second_release.clone());
    let second = backend
        .prepare(&second_artifact, &factory.preparation_key(second_release))
        .await
        .expect("second component must prepare");

    let snapshot = backend.cache_snapshot();
    assert_eq!(snapshot.entries, 1);
    assert_eq!(snapshot.maximum_entries, 1);
    assert_eq!(
        backend.stores_created(),
        0,
        "preparation must not instantiate a store"
    );

    let first_activation = ActivationId("activation-evicted".to_owned());
    let error = backend
        .invoke(
            request(
                first,
                first_activation.clone(),
                "first".to_owned(),
                &invocation_budget,
            ),
            &NeverCancelled {
                activation_id: first_activation,
            },
        )
        .await
        .expect_err("the least-recently-used prepared entry must be evicted");
    assert_eq!(error.code, PlatformErrorCode::NotFound);

    let second_activation = ActivationId("activation-retained".to_owned());
    let outcome = backend
        .invoke(
            request(
                second.clone(),
                second_activation.clone(),
                "second".to_owned(),
                &invocation_budget,
            ),
            &NeverCancelled {
                activation_id: second_activation,
            },
        )
        .await
        .expect("retained prepared state must invoke");
    assert_returned(outcome, b"second", ECHO_SUCCESS_MEDIA_TYPE);
    assert_eq!(backend.stores_created(), 1);

    backend
        .release(second)
        .await
        .expect("release must remove prepared state");
    assert_eq!(backend.cache_snapshot().entries, 0);
}

#[tokio::test(flavor = "current_thread")]
#[ignore = "requires the oversized-log component built by tools/validate_contracts.sh"]
async fn oversized_canonical_abi_log_payload_is_rejected_by_hostcall_fuel() {
    let base_artifact = load_issue19_artifact();
    let attack_component = load_bytes_from_env("LSF_OVERSIZED_LOG_COMPONENT");
    let attack_artifact = replace_component(
        base_artifact,
        attack_component,
        ReleaseDigest("sha256:phase-zero-oversized-log".to_owned()),
    );
    let invocation_budget = attack_artifact
        .manifest
        .execution
        .resource_budget_ceiling
        .clone();

    let factory = Phase0WasmtimeEngineFactory::new(Phase0WasmtimeConfig::default())
        .expect("factory must build");
    let backend = factory.create_backend_instance();
    let key = factory.preparation_key(attack_artifact.descriptor.release_digest.clone());
    let prepared = backend
        .prepare(&attack_artifact, &key)
        .await
        .expect("same-interface attack fixture must prepare");

    assert!(OVERSIZED_HOSTCALL_MESSAGE_BYTES > MAX_MESSAGE_BYTES);
    let activation_id = ActivationId("activation-hostcall-fuel".to_owned());
    let outcome = backend
        .invoke(
            request(
                prepared,
                activation_id.clone(),
                "x".repeat(OVERSIZED_HOSTCALL_MESSAGE_BYTES),
                &invocation_budget,
            ),
            &NeverCancelled {
                activation_id: activation_id.clone(),
            },
        )
        .await
        .expect("hostcall fuel exhaustion is a guest outcome");

    match outcome {
        GuestOutcome::Trapped { consumption, .. } => {
            assert_eq!(consumption.log_bytes, 0);
        }
        other => panic!("oversized guest-to-host transfer must trap, got {other:?}"),
    }
    assert!(backend.log_sink().snapshot_for(&activation_id).is_empty());
}

fn load_issue19_artifact() -> CapsuleArtifact {
    let component_path = required_env_path("LSF_ECHO_COMPONENT");
    let capsule_path = required_env_path("LSF_ECHO_CAPSULE");
    let component_bytes =
        fs::read(&component_path).expect("LSF_ECHO_COMPONENT must identify a readable component");
    let document: Value = serde_json::from_slice(
        &fs::read(&capsule_path).expect("LSF_ECHO_CAPSULE must identify readable JSON"),
    )
    .expect("LSF_ECHO_CAPSULE must contain valid JSON");
    let manifest = parse_capsule_manifest(&document);
    assert_eq!(
        manifest.component_digest.0,
        component_digest(&component_bytes)
    );

    CapsuleArtifact {
        descriptor: ArtifactDescriptor {
            reference: ArtifactReference(format!("file://{}", component_path.display())),
            release_digest: manifest.component_digest.clone(),
            media_type: "application/vnd.wasm.component.v1+wasm".to_owned(),
            size_bytes: u64::try_from(component_bytes.len()).expect("component size fits u64"),
            publisher: None,
            layers: Vec::new(),
            annotations: manifest.metadata.annotations.clone(),
        },
        manifest,
        contracts: Vec::new(),
        component_bytes,
    }
}

fn required_env_path(name: &str) -> PathBuf {
    env::var_os(name)
        .map(PathBuf::from)
        .unwrap_or_else(|| panic!("{name} must be set by the contract validation gate"))
}

fn load_bytes_from_env(name: &str) -> Vec<u8> {
    let path = required_env_path(name);
    fs::read(path).unwrap_or_else(|error| panic!("failed to read {name}: {error}"))
}

fn with_release(mut artifact: CapsuleArtifact, release: ReleaseDigest) -> CapsuleArtifact {
    artifact.descriptor.release_digest = release;
    artifact
}

fn replace_component(
    mut artifact: CapsuleArtifact,
    component_bytes: Vec<u8>,
    release: ReleaseDigest,
) -> CapsuleArtifact {
    artifact.descriptor.release_digest = release;
    artifact.descriptor.size_bytes =
        u64::try_from(component_bytes.len()).expect("component size fits u64");
    artifact.manifest.component_digest = ReleaseDigest(component_digest(&component_bytes));
    artifact.component_bytes = component_bytes;
    artifact
}

fn parse_capsule_manifest(document: &Value) -> CapsuleManifest {
    let limits = required_value(document, "/execution/limits");
    CapsuleManifest {
        api_version: required_string(document, "/apiVersion"),
        metadata: ObjectMetadata {
            name: required_string(document, "/metadata/name"),
            tenant: optional_string(document, "/metadata/tenant").map(TenantId),
            namespace: optional_string(document, "/metadata/namespace"),
            labels: parse_metadata(document.pointer("/metadata/labels")),
            annotations: parse_metadata(document.pointer("/metadata/annotations")),
        },
        semantic_version: required_string(document, "/component/version"),
        component_digest: ReleaseDigest(required_string(document, "/component/digest")),
        world: ContractId(required_string(document, "/component/world")),
        exports: required_array(document, "/exports")
            .iter()
            .map(|value| ContractExport {
                contract: ContractId(
                    value
                        .as_str()
                        .expect("every capsule export must be a string")
                        .to_owned(),
                ),
            })
            .collect(),
        imports: required_array(document, "/imports")
            .iter()
            .map(|value| ContractImport {
                contract: ContractId(required_string(value, "/contract")),
                optional: required_bool(value, "/optional"),
            })
            .collect(),
        execution: ExecutionRequirements {
            backend: match required_str(document, "/execution/backend") {
                "wasm-component" => ExecutionBackendKind::WasmComponent,
                other => panic!("unsupported generated backend: {other}"),
            },
            threading: match required_str(document, "/execution/threading") {
                "single-threaded" => ThreadingModel::SingleThreaded,
                "reentrant" => ThreadingModel::Reentrant,
                "cooperative" => ThreadingModel::Cooperative,
                other => panic!("unsupported generated threading model: {other}"),
            },
            state_model: match required_str(document, "/execution/stateModel") {
                "stateless" => StateModel::Stateless,
                "transactional-keyed" => StateModel::TransactionalKeyed,
                "entity" => StateModel::Entity,
                "durable-workflow" => StateModel::DurableWorkflow,
                other => panic!("unsupported generated state model: {other}"),
            },
            resource_budget_ceiling: ResourceBudget {
                cpu_fuel: required_u64(limits, "/cpuFuel"),
                memory_bytes: required_u64(limits, "/memoryBytes"),
                wall_deadline_unix_millis: optional_u64(limits, "/wallDeadlineUnixMillis"),
                child_calls: required_u32(limits, "/childCalls"),
                outbound_requests: required_u32(limits, "/outboundRequests"),
                state_read_bytes: required_u64(limits, "/stateReadBytes"),
                state_write_bytes: required_u64(limits, "/stateWriteBytes"),
                blob_read_bytes: required_u64(limits, "/blobReadBytes"),
                blob_write_bytes: required_u64(limits, "/blobWriteBytes"),
                log_bytes: required_u64(limits, "/logBytes"),
                effect_count: required_u32(limits, "/effectCount"),
            },
            host_call_depth_maximum: required_u32(document, "/execution/hostCallDepthMaximum"),
            component_call_depth_maximum: required_u32(
                document,
                "/execution/componentCallDepthMaximum",
            ),
            snapshot_eligible: required_bool(document, "/execution/snapshotEligible"),
            fusion_eligible: required_bool(document, "/execution/fusionEligible"),
        },
        minimum_fabric_version: required_string(document, "/compatibility/minimumFabricVersion"),
    }
}

fn parse_metadata(value: Option<&Value>) -> Metadata {
    let Some(object) = value.and_then(Value::as_object) else {
        return Metadata::new();
    };
    object
        .iter()
        .map(|(name, value)| {
            (
                name.clone(),
                value
                    .as_str()
                    .unwrap_or_else(|| panic!("metadata value for {name} must be a string"))
                    .to_owned(),
            )
        })
        .collect()
}

fn required_value<'a>(document: &'a Value, pointer: &str) -> &'a Value {
    document
        .pointer(pointer)
        .unwrap_or_else(|| panic!("generated capsule is missing {pointer}"))
}

fn required_array<'a>(document: &'a Value, pointer: &str) -> &'a [Value] {
    required_value(document, pointer)
        .as_array()
        .unwrap_or_else(|| panic!("generated capsule value {pointer} must be an array"))
}

fn required_str<'a>(document: &'a Value, pointer: &str) -> &'a str {
    required_value(document, pointer)
        .as_str()
        .unwrap_or_else(|| panic!("generated capsule value {pointer} must be a string"))
}

fn required_string(document: &Value, pointer: &str) -> String {
    required_str(document, pointer).to_owned()
}

fn optional_string(document: &Value, pointer: &str) -> Option<String> {
    document
        .pointer(pointer)
        .filter(|value| !value.is_null())
        .map(|value| {
            value
                .as_str()
                .unwrap_or_else(|| panic!("generated capsule value {pointer} must be a string"))
                .to_owned()
        })
}

fn required_u64(document: &Value, pointer: &str) -> u64 {
    required_value(document, pointer)
        .as_u64()
        .unwrap_or_else(|| panic!("generated capsule value {pointer} must be a u64"))
}

fn optional_u64(document: &Value, pointer: &str) -> Option<u64> {
    document
        .pointer(pointer)
        .filter(|value| !value.is_null())
        .map(|value| {
            value
                .as_u64()
                .unwrap_or_else(|| panic!("generated capsule value {pointer} must be a u64"))
        })
}

fn required_u32(document: &Value, pointer: &str) -> u32 {
    u32::try_from(required_u64(document, pointer))
        .unwrap_or_else(|_| panic!("generated capsule value {pointer} must fit u32"))
}

fn required_bool(document: &Value, pointer: &str) -> bool {
    required_value(document, pointer)
        .as_bool()
        .unwrap_or_else(|| panic!("generated capsule value {pointer} must be a bool"))
}

fn request(
    prepared: latent_executor::PreparedComponent,
    activation_id: ActivationId,
    message: String,
    budget: &ResourceBudget,
) -> ExecutionRequest {
    let budget = budget.clone();
    ExecutionRequest {
        activation: ActivationEnvelope {
            activation_id: activation_id.clone(),
            parent_activation_id: None,
            root_activation_id: activation_id,
            principal: InvocationPrincipal {
                subject: "phase-zero-test".to_owned(),
                kind: PrincipalKind::User,
                tenant: Some(TenantId("examples".to_owned())),
                service: None,
                claims: Metadata::from([("role".to_owned(), "tester".to_owned())]),
            },
            target: InvocationTarget {
                tenant: TenantId("examples".to_owned()),
                service: ServiceId("echo".to_owned()),
                contract: ContractId(ECHO_EXPORT.to_owned()),
                function: FunctionId("echo".to_owned()),
                route: None,
            },
            resolved_revision: None,
            deadline_unix_millis: None,
            priority: 0,
            trace: TraceContext {
                trace_id: TraceId("trace-phase-zero".to_owned()),
                span_id: SpanId("span-phase-zero".to_owned()),
                trace_flags: 1,
                baggage: Metadata::from([("suite".to_owned(), "issue-21".to_owned())]),
            },
            idempotency_key: None,
            retry_attempt: 0,
            budget: budget.clone(),
            metadata: Metadata::from([("case".to_owned(), "echo".to_owned())]),
            input: message.into_bytes(),
            input_media_type: ECHO_SUCCESS_MEDIA_TYPE.to_owned(),
        },
        prepared,
        cell: ExecutionCell {
            id: CellId("cell-0".to_owned()),
            class: "phase-zero".to_owned(),
            maximum_memory_bytes: budget.memory_bytes,
            metadata: Metadata::new(),
        },
        imports: vec![
            BoundImport {
                capability: CapabilityId("context".to_owned()),
                contract: CONTEXT_IMPORT.to_owned(),
                opaque_handle: "activation-context".to_owned(),
            },
            BoundImport {
                capability: CapabilityId("log".to_owned()),
                contract: LOG_IMPORT.to_owned(),
                opaque_handle: "bounded-log".to_owned(),
            },
        ],
        budget,
    }
}

fn component_digest(bytes: &[u8]) -> String {
    let digest = Sha256::digest(bytes);
    format!(
        "sha256:{}",
        digest
            .iter()
            .map(|byte| format!("{byte:02x}"))
            .collect::<String>()
    )
}

fn assert_returned(outcome: GuestOutcome, expected: &[u8], expected_media_type: &str) {
    match outcome {
        GuestOutcome::Returned {
            output,
            output_media_type,
            ..
        } => {
            assert_eq!(output, expected);
            assert_eq!(output_media_type, expected_media_type);
        }
        other => panic!("expected returned outcome, got {other:?}"),
    }
}
