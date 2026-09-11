use latent_activation::{ActivationEnvelope, TraceContext};
use latent_core::{
    ActivationId, CapabilityId, CellId, ContractId, FunctionId, InvocationPrincipal, Metadata,
    PlatformErrorCode, PrincipalKind, ReleaseDigest, ResourceBudget, RevisionId, RouteGeneration,
    ServiceId, SpanId, TenantId, TraceId,
};
use latent_executor::{
    BoundImport, ExecutionCell, ExecutionRequest, PreparationKey, PreparedComponent,
};
use latent_routing::{InvocationTarget, ResolvedRevision};

use super::{context_charge, validate_request_context};

#[test]
fn diagnostic_charge_matches_the_existing_validator_at_its_exact_boundary() {
    let request = request();
    let charge = context_charge(&request, LIMIT).expect("bounded context");
    assert_eq!(charge.maximum_bytes, LIMIT);
    assert_eq!(charge.charged_bytes + charge.remaining_bytes, LIMIT);
    assert!(charge.charged_bytes > 0);
    let exact = context_charge(&request, charge.charged_bytes).expect("exact validated charge");
    assert_eq!(exact.charged_bytes, charge.charged_bytes);
    assert_eq!(exact.remaining_bytes, 0);
    validate_request_context(&request, exact.maximum_bytes).expect("same validation path");
    let diagnostic = context_charge(&request, exact.maximum_bytes - 1).unwrap_err();
    let validation = validate_request_context(&request, exact.maximum_bytes - 1).unwrap_err();
    assert_eq!(diagnostic, validation);
}

const LIMIT: usize = 16 * 1024;

#[test]
fn rejects_each_context_owner_without_copying_or_exposing_oversized_text() {
    type Mutation = fn(&mut ExecutionRequest);
    let mutations: &[Mutation] = &[
        |r| r.activation.activation_id.0 = oversized(),
        |r| r.activation.root_activation_id.0 = oversized(),
        |r| r.activation.parent_activation_id = Some(ActivationId(oversized())),
        |r| r.activation.principal.subject = oversized(),
        |r| {
            r.activation
                .principal
                .claims
                .insert("claim".to_owned(), oversized());
        },
        |r| {
            r.activation
                .trace
                .baggage
                .insert("trace".to_owned(), oversized());
        },
        |r| {
            r.activation
                .metadata
                .insert("metadata".to_owned(), oversized());
        },
        |r| r.activation.target.route = Some(oversized()),
        |r| r.prepared.key.engine_configuration_digest = oversized(),
        |r| {
            r.prepared
                .metadata
                .insert("prepared".to_owned(), oversized());
        },
        |r| {
            r.cell.metadata.insert("cell".to_owned(), oversized());
        },
        |r| r.imports[0].opaque_handle = oversized(),
        |r| {
            r.activation
                .resolved_revision
                .as_mut()
                .expect("revision")
                .release
                .0 = oversized();
        },
    ];
    for mutate in mutations {
        let mut request = request();
        validate_request_context(&request, LIMIT).expect("bounded baseline");
        mutate(&mut request);
        let error = validate_request_context(&request, LIMIT).expect_err("bounded context owner");
        assert_eq!(error.code, PlatformErrorCode::ResourceExhausted);
        assert_eq!(
            error.message,
            "activation context exceeds configured byte limit"
        );
        assert!(!error.retryable);
        assert!(error.details.is_empty());
    }
}

#[test]
fn empty_metadata_values_still_consume_structural_budget_and_input_is_separate() {
    let mut request = request();
    request.activation.input = vec![0xff; 2 * LIMIT];
    validate_request_context(&request, LIMIT).expect("input bytes belong to the value codec");
    request.activation.metadata = (0..4)
        .map(|index| (index.to_string(), String::new()))
        .collect();
    let error = validate_request_context(&request, LIMIT).expect_err("map nodes consume budget");
    assert_eq!(error.code, PlatformErrorCode::ResourceExhausted);
    assert!(validate_request_context(&request, 0).is_err());
}

fn oversized() -> String {
    "private-context".repeat(LIMIT / 16 + 1)
}

fn request() -> ExecutionRequest {
    let budget = ResourceBudget {
        cpu_fuel: 1000,
        memory_bytes: 64 * 1024,
        wall_time_limit_millis: None,
        child_calls: 0,
        outbound_requests: 0,
        state_read_bytes: 0,
        state_write_bytes: 0,
        blob_read_bytes: 0,
        blob_write_bytes: 0,
        log_bytes: 1000,
        effect_count: 0,
    };
    let target = InvocationTarget {
        tenant: TenantId("tenant".to_owned()),
        service: ServiceId("service".to_owned()),
        contract: ContractId("tests:generic/values@0.1.0".to_owned()),
        function: FunctionId("identify".to_owned()),
        route: None,
    };
    ExecutionRequest {
        activation: ActivationEnvelope {
            activation_id: ActivationId("activation".to_owned()),
            root_activation_id: ActivationId("root".to_owned()),
            parent_activation_id: None,
            principal: InvocationPrincipal {
                subject: "subject".to_owned(),
                kind: PrincipalKind::Service,
                tenant: Some(target.tenant.clone()),
                service: Some(target.service.clone()),
                claims: Metadata::new(),
            },
            target: target.clone(),
            resolved_revision: Some(ResolvedRevision {
                target,
                revision: RevisionId("revision".to_owned()),
                release: ReleaseDigest("release".to_owned()),
                route_generation: RouteGeneration(1),
                attributes: Metadata::new(),
            }),
            deadline_unix_millis: None,
            priority: 0,
            trace: TraceContext {
                trace_id: TraceId("trace".to_owned()),
                span_id: SpanId("span".to_owned()),
                trace_flags: 0,
                baggage: Metadata::new(),
            },
            idempotency_key: None,
            retry_attempt: 0,
            budget: budget.clone(),
            metadata: Metadata::new(),
            input: b"[]".to_vec(),
            input_media_type: "application/json".to_owned(),
        },
        prepared: PreparedComponent {
            key: PreparationKey {
                release: ReleaseDigest("release".to_owned()),
                engine_version: "version".to_owned(),
                engine_configuration_digest: "config".to_owned(),
                target_triple: "target".to_owned(),
                cpu_feature_set: "cpu".to_owned(),
            },
            backend: "backend".to_owned(),
            opaque_handle: "handle".to_owned(),
            metadata: Metadata::new(),
        },
        cell: ExecutionCell {
            id: CellId("cell".to_owned()),
            class: "standard".to_owned(),
            maximum_memory_bytes: budget.memory_bytes,
            metadata: Metadata::new(),
        },
        imports: vec![BoundImport {
            capability: CapabilityId("context".to_owned()),
            contract: "latent:context/context@0.1.0".to_owned(),
            opaque_handle: "scope".to_owned(),
        }],
        budget,
    }
}
