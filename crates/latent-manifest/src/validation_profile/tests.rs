use super::*;
use crate::{ContractImport, JsonManifestCodec, ManifestCodec};
use latent_core::{ContractId, PHASE3_HOST_ABI_CURRENT};

fn profile() -> ManifestValidationProfile {
    ManifestValidationProfile::phase4(
        BudgetProfile::Phase4,
        PHASE4_HOST_ABI_V1,
        &phase4_host_abi_digest(),
    )
    .unwrap()
}
fn capsule() -> CapsuleManifest {
    let mut value = JsonManifestCodec::default()
        .decode_capsule(include_bytes!(
            "../../../../examples/echo-contract/capsule.json"
        ))
        .unwrap();
    value.imports = [
        "latent:state/key-value@0.2.0",
        "latent:intents/staging@0.1.0",
    ]
    .into_iter()
    .map(|name| ContractImport {
        contract: ContractId(name.into()),
        optional: false,
    })
    .collect();
    value.execution.threading = ThreadingModel::SingleThreaded;
    value.execution.snapshot_eligible = false;
    value.execution.fusion_eligible = false;
    let budget = &mut value.execution.resource_budget_ceiling;
    budget.state_read_bytes = 4 * 1024 * 1024;
    budget.state_write_bytes = 2 * 1024 * 1024;
    budget.effect_count = 32;
    budget.memory_bytes = 32 * 1024 * 1024;
    budget.wall_time_limit_millis = Some(30_000);
    value
}
fn deployment(value: &CapsuleManifest) -> DeploymentManifest {
    let mut deployment = JsonManifestCodec::default()
        .decode_deployment(include_bytes!(
            "../../../../examples/echo-contract/deployment.json"
        ))
        .unwrap();
    deployment.resources = value.execution.resource_budget_ceiling.clone();
    deployment.grants.clear();
    deployment
}

#[test]
fn selection_requires_exact_accounting_preparation_abi_and_digest() {
    assert!(!ManifestValidationProfile::default().transactional());
    assert!(profile().transactional());
    for accounting in [BudgetProfile::Phase1, BudgetProfile::Phase3] {
        assert!(ManifestValidationProfile::phase4(
            accounting,
            PHASE4_HOST_ABI_V1,
            &phase4_host_abi_digest()
        )
        .is_err());
    }
    assert!(ManifestValidationProfile::phase4(
        BudgetProfile::Phase4,
        PHASE3_HOST_ABI_CURRENT,
        &phase4_host_abi_digest()
    )
    .is_err());
    assert!(ManifestValidationProfile::phase4(
        BudgetProfile::Phase4,
        PHASE4_HOST_ABI_V1,
        "sha256:wrong"
    )
    .is_err());
}

#[test]
fn original_stateless_validation_rejects_state_requests_while_selected_profile_accepts() {
    let capsule = capsule();
    let deployment = deployment(&capsule);
    assert!(Phase1ManifestValidator.validate_capsule(&capsule).is_err());
    assert!(ManifestValidationProfile::default()
        .validate_capsule(&capsule)
        .is_err());
    assert!(ManifestValidationProfile::default()
        .validate_deployment(&deployment)
        .is_err());
    profile().validate_capsule(&capsule).unwrap();
    profile()
        .validate_deployment_against_capsule(&deployment, &capsule)
        .unwrap();
}

#[test]
fn selected_profile_retains_tenant_service_release_and_budget_ceiling_checks() {
    let capsule = capsule();
    let deployment = deployment(&capsule);
    let mut wrong = deployment.clone();
    wrong.service.0 = "other/service".into();
    assert!(profile()
        .validate_deployment_against_capsule(&wrong, &capsule)
        .is_err());
    wrong = deployment.clone();
    wrong.metadata.tenant = Some(latent_core::TenantId("other".into()));
    assert!(profile()
        .validate_deployment_against_capsule(&wrong, &capsule)
        .is_err());
    wrong = deployment.clone();
    wrong.release.0 = format!("sha256:{}", "2".repeat(64));
    assert!(profile()
        .validate_deployment_against_capsule(&wrong, &capsule)
        .is_err());
    wrong = deployment;
    wrong.resources.state_write_bytes += 1;
    assert!(profile()
        .validate_deployment_against_capsule(&wrong, &capsule)
        .is_err());
}

#[test]
fn supported_http_is_descriptive_but_raw_network_wrong_versions_and_optional_state_reject() {
    let mut value = capsule();
    value.imports.push(ContractImport {
        contract: ContractId("latent:http/client@0.2.0".into()),
        optional: false,
    });
    profile().validate_capsule(&value).unwrap();
    for name in [
        "wasi:sockets/tcp@0.2.0",
        "latent:http/client@0.3.0",
        "latent:state/key-value@0.1.0",
        "latent:service/invoke@0.1.0",
    ] {
        let mut wrong = value.clone();
        wrong.imports.push(ContractImport {
            contract: ContractId(name.into()),
            optional: false,
        });
        assert!(profile().validate_capsule(&wrong).is_err(), "{name}");
    }
    value.imports[0].optional = true;
    assert!(profile().validate_capsule(&value).is_err());
    value.imports.clear();
    assert!(profile().validate_capsule(&value).is_err());
}

#[test]
fn transaction_execution_remains_finite_unsnapshotted_and_without_immediate_effect_budget() {
    let original = capsule();
    let mut wrong = original.clone();
    wrong.execution.threading = ThreadingModel::Reentrant;
    assert!(profile().validate_capsule(&wrong).is_err());
    wrong = original.clone();
    wrong.execution.snapshot_eligible = true;
    assert!(profile().validate_capsule(&wrong).is_err());
    wrong = original.clone();
    wrong.execution.fusion_eligible = true;
    assert!(profile().validate_capsule(&wrong).is_err());
    wrong = original.clone();
    wrong
        .execution
        .resource_budget_ceiling
        .wall_time_limit_millis = None;
    assert!(profile().validate_capsule(&wrong).is_err());
    wrong = original.clone();
    wrong.execution.resource_budget_ceiling.outbound_requests = 1;
    assert!(profile().validate_capsule(&wrong).is_err());
    wrong = original;
    wrong.execution.resource_budget_ceiling.child_calls = 1;
    assert!(profile().validate_capsule(&wrong).is_err());
}

#[test]
fn configured_node_preserves_supported_stateless_capsules_and_their_existing_validation() {
    let value = JsonManifestCodec::default()
        .decode_capsule(include_bytes!(
            "../../../../examples/echo-contract/capsule.json"
        ))
        .unwrap();
    assert_eq!(
        profile().validate_capsule(&value),
        Phase1ManifestValidator.validate_capsule(&value)
    );
    let mut wrong = value;
    wrong.metadata.name.clear();
    assert_eq!(
        profile().validate_capsule(&wrong),
        Phase1ManifestValidator.validate_capsule(&wrong)
    );
}
