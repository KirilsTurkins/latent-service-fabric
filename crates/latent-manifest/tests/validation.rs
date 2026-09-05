use latent_core::{CapabilityId, ContractId, ReleaseDigest, ResourceBudget, ServiceId, TenantId};
use latent_manifest::{
    ExecutionBackendKind, JsonManifestCodec, ManifestCodec, ManifestResult, ManifestValidator,
    Phase1ManifestValidator, StateModel,
};

const ECHO_CAPSULE: &[u8] = include_bytes!("../../../examples/echo-contract/capsule.json");
const COUNTER_CAPSULE: &[u8] = include_bytes!("../../../examples/counter-contract/capsule.json");
const ECHO_DEPLOYMENT: &[u8] = include_bytes!("../../../examples/echo-contract/deployment.json");
const ECHO_BINDING: &[u8] = include_bytes!("../../../examples/bindings/gateway-to-echo.json");
const ECHO_TRIGGER: &[u8] = include_bytes!("../../../examples/echo-contract/http-trigger.json");
const LOG_POLICY: &[u8] = include_bytes!("../../../examples/policies/default-log-policy.json");

#[test]
fn phase1_examples_validate_independently_and_as_a_release_pair() {
    let codec = JsonManifestCodec::default();
    let validator = Phase1ManifestValidator::new();
    let capsule = codec.decode_capsule(ECHO_CAPSULE).expect("capsule");
    let deployment = codec
        .decode_deployment(ECHO_DEPLOYMENT)
        .expect("deployment");

    validator.validate_capsule(&capsule).expect("valid capsule");
    validator
        .validate_deployment(&deployment)
        .expect("valid deployment");
    validator
        .validate_deployment_against_capsule(&deployment, &capsule)
        .expect("compatible deployment and capsule");

    validator
        .validate_binding(&codec.decode_binding(ECHO_BINDING).expect("binding"))
        .expect("valid binding");
    validator
        .validate_trigger(&codec.decode_trigger(ECHO_TRIGGER).expect("trigger"))
        .expect("valid trigger");
    validator
        .validate_policy(&codec.decode_policy(LOG_POLICY).expect("policy"))
        .expect("valid policy");
}

#[test]
fn unsupported_state_and_backend_are_deterministic() {
    let codec = JsonManifestCodec::default();
    let validator = Phase1ManifestValidator::new();
    let counter = codec
        .decode_capsule(COUNTER_CAPSULE)
        .expect("structurally valid counter");
    assert_violation(
        validator.validate_capsule(&counter),
        "$.execution.stateModel",
        "unsupported-state-model",
    );

    let mut capsule = codec.decode_capsule(ECHO_CAPSULE).expect("capsule");
    capsule.execution.backend = ExecutionBackendKind::Container;
    assert_violation(
        validator.validate_capsule(&capsule),
        "$.execution.backend",
        "unsupported-execution-backend",
    );

    capsule.execution.backend = ExecutionBackendKind::WasmComponent;
    capsule.execution.state_model = StateModel::Entity;
    assert_violation(
        validator.validate_capsule(&capsule),
        "$.execution.stateModel",
        "unsupported-state-model",
    );
}

#[test]
fn versions_digests_and_identifiers_are_checked() {
    let codec = JsonManifestCodec::default();
    let validator = Phase1ManifestValidator::new();
    let mut capsule = codec.decode_capsule(ECHO_CAPSULE).expect("capsule");

    capsule.api_version = "latent.dev/v2".to_owned();
    assert_violation(
        validator.validate_capsule(&capsule),
        "$.apiVersion",
        "unsupported-api-version",
    );

    capsule.api_version = "latent.dev/v1alpha1".to_owned();
    capsule.component_digest = ReleaseDigest("sha256:abc".to_owned());
    assert_violation(
        validator.validate_capsule(&capsule),
        "$.component.digest",
        "invalid-digest",
    );

    capsule.component_digest = ReleaseDigest(format!("sha256:{}", "a".repeat(64)));
    capsule.semantic_version = "01.0.0".to_owned();
    assert_violation(
        validator.validate_capsule(&capsule),
        "$.component.version",
        "invalid-semantic-version",
    );

    capsule.semantic_version = "1.0.0".to_owned();
    capsule.minimum_fabric_version = "0.1.1".to_owned();
    assert_violation(
        validator.validate_capsule(&capsule),
        "$.compatibility.minimumFabricVersion",
        "unsupported-minimum-fabric-version",
    );

    capsule.minimum_fabric_version = "0.1.0-alpha.1".to_owned();
    capsule.world = ContractId("not-a-contract".to_owned());
    assert_violation(
        validator.validate_capsule(&capsule),
        "$.component.world",
        "invalid-identifier",
    );
}

#[test]
fn zero_and_relative_budget_semantics_are_unambiguous() {
    let codec = JsonManifestCodec::default();
    let validator = Phase1ManifestValidator::new();
    let mut capsule = codec.decode_capsule(ECHO_CAPSULE).expect("capsule");
    let mut deployment = codec
        .decode_deployment(ECHO_DEPLOYMENT)
        .expect("deployment");

    capsule.execution.resource_budget_ceiling = zero_budget(Some(0));
    deployment.resources = zero_budget(Some(0));
    validator
        .validate_capsule(&capsule)
        .expect("zero is an exact valid ceiling");
    validator
        .validate_deployment(&deployment)
        .expect("zero is an exact valid deployment ceiling");
    validator
        .validate_deployment_against_capsule(&deployment, &capsule)
        .expect("equal zero ceilings");

    capsule
        .execution
        .resource_budget_ceiling
        .wall_time_limit_millis = Some(100);
    deployment.resources.wall_time_limit_millis = None;
    validator
        .validate_deployment(&deployment)
        .expect("None is an independently valid unconstrained relative ceiling");
    assert_violation(
        validator.validate_deployment_against_capsule(&deployment, &capsule),
        "$.spec.resources.wallTimeLimitMillis",
        "budget-exceeds-capsule",
    );

    deployment.resources.wall_time_limit_millis = Some(101);
    assert_violation(
        validator.validate_deployment_against_capsule(&deployment, &capsule),
        "$.spec.resources.wallTimeLimitMillis",
        "budget-exceeds-capsule",
    );

    deployment.resources.wall_time_limit_millis = Some(100);
    validator
        .validate_deployment_against_capsule(&deployment, &capsule)
        .expect("equal relative ceiling");
}

#[test]
fn stateless_state_budgets_are_rejected() {
    let codec = JsonManifestCodec::default();
    let validator = Phase1ManifestValidator::new();
    let mut deployment = codec
        .decode_deployment(ECHO_DEPLOYMENT)
        .expect("deployment");
    deployment.resources.state_read_bytes = 1;
    deployment.resources.state_write_bytes = 2;

    let violations = validator
        .validate_deployment(&deployment)
        .expect_err("state budgets must fail");
    assert!(violations.iter().any(|violation| {
        violation.path == "$.spec.resources.stateReadBytes"
            && violation.code == "invalid-stateless-budget"
    }));
    assert!(violations.iter().any(|violation| {
        violation.path == "$.spec.resources.stateWriteBytes"
            && violation.code == "invalid-stateless-budget"
    }));
}

#[test]
fn route_identity_and_tenant_scope_rules_are_stable() {
    let codec = JsonManifestCodec::default();
    let validator = Phase1ManifestValidator::new();
    let mut deployment = codec
        .decode_deployment(ECHO_DEPLOYMENT)
        .expect("deployment");

    deployment.route_weight = 0;
    assert_violation(
        validator.validate_deployment(&deployment),
        "$.spec.route.weight",
        "invalid-route-weight",
    );

    deployment.route_weight = 10_000;
    deployment.id.0 = "different".to_owned();
    assert_violation(
        validator.validate_deployment(&deployment),
        "$.metadata.name",
        "identity-mismatch",
    );

    deployment.id.0 = deployment.metadata.name.clone();
    deployment.service = ServiceId("other/echo".to_owned());
    assert_violation(
        validator.validate_deployment(&deployment),
        "$.spec.service",
        "tenant-scope-mismatch",
    );

    deployment.service = ServiceId("examples/echo".to_owned());
    deployment.metadata.tenant = None;
    deployment.metadata.namespace = Some("production".to_owned());
    let violations = validator
        .validate_deployment(&deployment)
        .expect_err("missing tenant must fail");
    assert!(violations.iter().any(|violation| {
        violation.path == "$.metadata.tenant" && violation.code == "missing-tenant"
    }));
    assert!(violations.iter().any(|violation| {
        violation.path == "$.metadata.namespace" && violation.code == "namespace-requires-tenant"
    }));
}

#[test]
fn cross_manifest_ceiling_and_capability_checks_are_complete() {
    let codec = JsonManifestCodec::default();
    let validator = Phase1ManifestValidator::new();
    let capsule = codec.decode_capsule(ECHO_CAPSULE).expect("capsule");
    let mut deployment = codec
        .decode_deployment(ECHO_DEPLOYMENT)
        .expect("deployment");

    deployment.resources.memory_bytes = capsule
        .execution
        .resource_budget_ceiling
        .memory_bytes
        .saturating_add(1);
    assert_violation(
        validator.validate_deployment_against_capsule(&deployment, &capsule),
        "$.spec.resources.memoryBytes",
        "budget-exceeds-capsule",
    );

    deployment.resources.memory_bytes = capsule.execution.resource_budget_ceiling.memory_bytes;
    deployment.grants[0].capability = CapabilityId("latent:unknown/api@0.1.0".to_owned());
    assert_violation(
        validator.validate_deployment_against_capsule(&deployment, &capsule),
        "$.spec.grants[0].capability",
        "capability-not-imported",
    );

    deployment.grants[0].capability = CapabilityId("latent:context/context@0.1.0".to_owned());
    deployment.release = ReleaseDigest(format!("sha256:{}", "f".repeat(64)));
    assert_violation(
        validator.validate_deployment_against_capsule(&deployment, &capsule),
        "$.spec.release",
        "release-mismatch",
    );
}

#[test]
fn repeated_validation_returns_identical_ordered_violations() {
    let codec = JsonManifestCodec::default();
    let validator = Phase1ManifestValidator::new();
    let mut deployment = codec
        .decode_deployment(ECHO_DEPLOYMENT)
        .expect("deployment");
    deployment.api_version = "bad".to_owned();
    deployment.route_weight = 0;
    deployment.metadata.tenant = Some(TenantId("other".to_owned()));

    let first = validator
        .validate_deployment(&deployment)
        .expect_err("invalid deployment");
    let second = validator
        .validate_deployment(&deployment)
        .expect_err("invalid deployment");
    assert_eq!(first, second);
}

fn zero_budget(wall_time_limit_millis: Option<u64>) -> ResourceBudget {
    ResourceBudget {
        cpu_fuel: 0,
        memory_bytes: 0,
        wall_time_limit_millis,
        child_calls: 0,
        outbound_requests: 0,
        state_read_bytes: 0,
        state_write_bytes: 0,
        blob_read_bytes: 0,
        blob_write_bytes: 0,
        log_bytes: 0,
        effect_count: 0,
    }
}

fn assert_violation(result: ManifestResult<()>, expected_path: &str, expected_code: &str) {
    let violations = result.expect_err("validation unexpectedly succeeded");
    assert!(
        violations
            .iter()
            .any(|violation| violation.path == expected_path && violation.code == expected_code),
        "missing {expected_path} [{expected_code}] in {violations:#?}"
    );
}
