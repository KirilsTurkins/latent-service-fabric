use latent_core::{CapabilityId, ContractId, ReleaseDigest, TenantId};
use latent_manifest::{
    validate_deployment_document, CapsuleManifest, ContractImport, DeploymentManifest,
    JsonManifestCodec, ManifestCodec, ManifestResult, ManifestValidator, Phase1ManifestValidator,
    Phase4TransactionManifestValidator, RendererRequirement, StateModel,
};

fn transaction() -> (CapsuleManifest, DeploymentManifest) {
    let codec = JsonManifestCodec::default();
    let mut capsule = codec
        .decode_capsule(include_bytes!(
            "../../../examples/echo-contract/capsule.json"
        ))
        .unwrap();
    let mut deployment = codec
        .decode_deployment(include_bytes!(
            "../../../examples/echo-contract/deployment.json"
        ))
        .unwrap();
    capsule.imports = [
        "latent:state/key-value@0.2.0",
        "latent:intents/staging@0.1.0",
    ]
    .into_iter()
    .map(|contract| ContractImport {
        contract: ContractId(contract.into()),
        optional: false,
    })
    .collect();
    let limits = &mut capsule.execution.resource_budget_ceiling;
    limits.cpu_fuel = 1_000_000_000;
    limits.memory_bytes = 64 * 1024 * 1024;
    limits.wall_time_limit_millis = Some(120_000);
    limits.state_read_bytes = 4 * 1024 * 1024;
    limits.state_write_bytes = 2 * 1024 * 1024;
    limits.effect_count = 1;
    deployment.resources.clone_from(limits);
    deployment.grants.clear();
    (capsule, deployment)
}

fn violation(result: ManifestResult<()>, code: &str) {
    assert!(result.unwrap_err().iter().any(|item| item.code == code));
}

#[test]
fn transaction_ceilings_require_explicit_phase4_validation_and_preserve_unsigned_width() {
    let (mut capsule, mut deployment) = transaction();
    Phase4TransactionManifestValidator
        .validate_deployment_against_capsule(&deployment, &capsule)
        .unwrap();
    violation(
        Phase1ManifestValidator.validate_capsule(&capsule),
        "invalid-stateless-budget",
    );
    violation(
        Phase1ManifestValidator.validate_deployment(&deployment),
        "invalid-stateless-budget",
    );
    capsule.execution.resource_budget_ceiling.cpu_fuel = u64::MAX;
    deployment.resources.cpu_fuel = u64::MAX;
    Phase4TransactionManifestValidator
        .validate_deployment_against_capsule(&deployment, &capsule)
        .unwrap();
}

#[test]
fn transaction_bounds_reject_immediate_operations_children_and_overflowing_ceilings() {
    let (capsule, deployment) = transaction();
    for mutation in 0..10 {
        let mut invalid = capsule.clone();
        let budget = &mut invalid.execution.resource_budget_ceiling;
        match mutation {
            0 => budget.child_calls = 1,
            1 => budget.outbound_requests = 1,
            2 => budget.blob_read_bytes = 1,
            3 => budget.blob_write_bytes = 1,
            4 => budget.state_read_bytes = 4 * 1024 * 1024 + 1,
            5 => budget.state_write_bytes = 8 * 1024 * 1024 + 1,
            6 => budget.effect_count = 129,
            7 => budget.cpu_fuel = 0,
            8 => budget.memory_bytes = 0,
            _ => budget.wall_time_limit_millis = Some(0),
        }
        let mut invalid_deployment = deployment.clone();
        invalid_deployment.resources.clone_from(budget);
        violation(
            Phase4TransactionManifestValidator.validate_capsule(&invalid),
            "invalid-transaction-budget",
        );
        violation(
            Phase4TransactionManifestValidator.validate_deployment(&invalid_deployment),
            "invalid-transaction-budget",
        );
    }
}

#[test]
fn transaction_validation_preserves_guest_scope_identity_and_deployment_fences() {
    let (capsule, deployment) = transaction();
    let validator = Phase4TransactionManifestValidator;
    let mut invalid = capsule.clone();
    invalid.execution.state_model = StateModel::TransactionalKeyed;
    violation(
        validator.validate_capsule(&invalid),
        "unsupported-state-model",
    );
    invalid = capsule.clone();
    invalid.runtime_requirements.renderer = Some(RendererRequirement::angular());
    violation(
        validator.validate_capsule(&invalid),
        "transaction-renderer-unsupported",
    );
    invalid = capsule.clone();
    invalid.component_digest = ReleaseDigest("sha256:broken".into());
    violation(validator.validate_capsule(&invalid), "invalid-digest");
    for (invalid, code) in invalid_deployments(&deployment) {
        violation(
            validator.validate_deployment_against_capsule(&invalid, &capsule),
            code,
        );
    }
}

fn invalid_deployments(original: &DeploymentManifest) -> Vec<(DeploymentManifest, &'static str)> {
    let mut invalid = Vec::new();
    let mut deployment = original.clone();
    deployment.resources.state_write_bytes += 1;
    invalid.push((deployment, "budget-exceeds-capsule"));
    deployment = original.clone();
    deployment.resources.wall_time_limit_millis = None;
    invalid.push((deployment, "budget-exceeds-capsule"));
    deployment = original.clone();
    deployment.metadata.tenant = Some(TenantId("foreign".into()));
    invalid.push((deployment, "tenant-scope-mismatch"));
    deployment = original.clone();
    deployment.release = ReleaseDigest(format!("sha256:{}", "f".repeat(64)));
    invalid.push((deployment, "release-mismatch"));
    deployment = original.clone();
    let codec = JsonManifestCodec::default();
    deployment.grants = codec
        .decode_deployment(include_bytes!(
            "../../../examples/echo-contract/deployment.json"
        ))
        .unwrap()
        .grants;
    deployment.grants[0].capability = CapabilityId("latent:unknown/api@0.1.0".into());
    invalid.push((deployment, "capability-not-imported"));
    invalid
}

#[test]
fn fresh_query_ceiling_allows_zero_mutation_and_intent_capacity() {
    let (mut capsule, mut deployment) = transaction();
    capsule.execution.resource_budget_ceiling.state_write_bytes = 0;
    capsule.execution.resource_budget_ceiling.effect_count = 0;
    deployment
        .resources
        .clone_from(&capsule.execution.resource_budget_ceiling);
    Phase4TransactionManifestValidator
        .validate_deployment_against_capsule(&deployment, &capsule)
        .unwrap();
}

#[test]
fn deployment_document_accepts_both_shapes_without_selecting_artifact_authority() {
    let codec = JsonManifestCodec::default();
    let mut ordinary = codec
        .decode_deployment(include_bytes!(
            "../../../examples/echo-contract/deployment.json"
        ))
        .unwrap();
    ordinary.resources.child_calls = 2;
    ordinary.resources.outbound_requests = 1;
    Phase1ManifestValidator
        .validate_deployment(&ordinary)
        .unwrap();
    validate_deployment_document(&ordinary).unwrap();
    let (capsule, mut deployment) = transaction();
    validate_deployment_document(&deployment).unwrap();
    violation(
        Phase1ManifestValidator.validate_deployment_against_capsule(&deployment, &capsule),
        "invalid-stateless-budget",
    );
    deployment.resources.child_calls = 1;
    assert!(validate_deployment_document(&deployment).is_err());
    deployment.resources.child_calls = 0;
    deployment.resources.state_write_bytes = u64::MAX;
    assert!(validate_deployment_document(&deployment).is_err());
    ordinary.metadata.tenant = None;
    violation(validate_deployment_document(&ordinary), "missing-tenant");
}
