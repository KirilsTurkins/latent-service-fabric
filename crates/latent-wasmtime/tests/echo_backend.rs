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
use sha2::{Digest, Sha256};

const MAX_MESSAGE_BYTES: usize = 64 * 1024;

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
#[ignore = "requires the component produced by tools/build_echo_capsule.py"]
async fn invokes_echo_through_the_execution_backend_and_enforces_the_phase_zero_boundary() {
    let component_bytes = load_component();

    let config = Phase0WasmtimeConfig {
        maximum_memory_bytes: 8 * 1024 * 1024,
        prepared_cache_maximum_entries: 2,
        ..Phase0WasmtimeConfig::default()
    };
    let factory = Phase0WasmtimeEngineFactory::new(config.clone()).expect("factory must build");
    let backend = factory.create_backend_instance();
    let release = ReleaseDigest("sha256:phase-zero-echo-release".to_owned());
    let artifact = artifact(component_bytes, release.clone(), 4 * 1024 * 1024);
    let key = factory.preparation_key(release);

    let prepared = backend
        .prepare(&artifact, &key)
        .await
        .expect("echo component must prepare");
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
            ),
            &NeverCancelled {
                activation_id: success_activation.clone(),
            },
        )
        .await
        .expect("echo invocation must complete");
    assert_returned(success, b"hello from Wasmtime", ECHO_SUCCESS_MEDIA_TYPE);

    let empty_activation = ActivationId("activation-empty".to_owned());
    let empty = backend
        .invoke(
            request(prepared.clone(), empty_activation.clone(), String::new()),
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

    assert_eq!(backend.stores_created(), 3);
    for activation_id in [success_activation, empty_activation, oversized_activation] {
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
    let mut unbound = request(prepared, activation_id.clone(), "unbound".to_owned());
    unbound.imports.pop();
    let error = backend
        .invoke(unbound, &NeverCancelled { activation_id })
        .await
        .expect_err("missing host import binding must be rejected");
    assert_eq!(error.code, PlatformErrorCode::IncompatibleContract);
}

#[tokio::test(flavor = "current_thread")]
#[ignore = "requires the component produced by tools/build_echo_capsule.py"]
async fn prepared_state_is_entry_bounded_and_evicts_without_retaining_an_instance() {
    let component_bytes = load_component();

    let config = Phase0WasmtimeConfig {
        prepared_cache_maximum_entries: 1,
        ..Phase0WasmtimeConfig::default()
    };
    let factory = Phase0WasmtimeEngineFactory::new(config).expect("factory must build");
    let backend = factory.create_backend_instance();

    let first_release = ReleaseDigest("sha256:phase-zero-echo-release-a".to_owned());
    let first_artifact = artifact(
        component_bytes.clone(),
        first_release.clone(),
        4 * 1024 * 1024,
    );
    let first = backend
        .prepare(&first_artifact, &factory.preparation_key(first_release))
        .await
        .expect("first component must prepare");

    let second_release = ReleaseDigest("sha256:phase-zero-echo-release-b".to_owned());
    let second_artifact = artifact(component_bytes, second_release.clone(), 4 * 1024 * 1024);
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
            request(first, first_activation.clone(), "first".to_owned()),
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

fn load_component() -> Vec<u8> {
    let path = env::var_os("LSF_ECHO_COMPONENT")
        .map(PathBuf::from)
        .expect("LSF_ECHO_COMPONENT must point to the generated echo component");
    fs::read(path).expect("LSF_ECHO_COMPONENT must identify a readable component")
}

fn artifact(
    component_bytes: Vec<u8>,
    release: ReleaseDigest,
    declared_memory_bytes: u64,
) -> CapsuleArtifact {
    let digest = ReleaseDigest(component_digest(&component_bytes));
    CapsuleArtifact {
        descriptor: ArtifactDescriptor {
            reference: ArtifactReference("local://phase-zero/echo".to_owned()),
            release_digest: release,
            media_type: "application/vnd.wasm.component.v1+wasm".to_owned(),
            size_bytes: u64::try_from(component_bytes.len()).expect("component size fits u64"),
            publisher: None,
            layers: Vec::new(),
            annotations: Metadata::new(),
        },
        manifest: CapsuleManifest {
            api_version: "latent.dev/v1alpha1".to_owned(),
            metadata: ObjectMetadata {
                name: "examples/echo".to_owned(),
                tenant: Some(TenantId("examples".to_owned())),
                namespace: None,
                labels: Metadata::new(),
                annotations: Metadata::new(),
            },
            semantic_version: "0.1.0".to_owned(),
            component_digest: digest,
            world: ContractId(ECHO_WORLD.to_owned()),
            exports: vec![ContractExport {
                contract: ContractId(ECHO_EXPORT.to_owned()),
            }],
            imports: vec![
                ContractImport {
                    contract: ContractId(CONTEXT_IMPORT.to_owned()),
                    optional: false,
                },
                ContractImport {
                    contract: ContractId(LOG_IMPORT.to_owned()),
                    optional: false,
                },
            ],
            execution: ExecutionRequirements {
                backend: ExecutionBackendKind::WasmComponent,
                threading: ThreadingModel::Reentrant,
                state_model: StateModel::Stateless,
                resource_budget_ceiling: budget(declared_memory_bytes),
                host_call_depth_maximum: 8,
                component_call_depth_maximum: 4,
                snapshot_eligible: false,
                fusion_eligible: false,
            },
            minimum_fabric_version: "0.1.0".to_owned(),
        },
        contracts: Vec::new(),
        component_bytes,
    }
}

fn request(
    prepared: latent_executor::PreparedComponent,
    activation_id: ActivationId,
    message: String,
) -> ExecutionRequest {
    let budget = budget(4 * 1024 * 1024);
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
            maximum_memory_bytes: 4 * 1024 * 1024,
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

fn budget(memory_bytes: u64) -> ResourceBudget {
    ResourceBudget {
        cpu_fuel: 2_000_000,
        memory_bytes,
        wall_deadline_unix_millis: None,
        child_calls: 0,
        outbound_requests: 0,
        state_read_bytes: 0,
        state_write_bytes: 0,
        blob_read_bytes: 0,
        blob_write_bytes: 0,
        log_bytes: 16 * 1024,
        effect_count: 0,
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
