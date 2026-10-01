mod fixtures;

use fixtures::component::Options;
use latent_artifacts::package::LayerRole;
use latent_core::PHASE4_HOST_ABI_V1;
use latent_manifest::{
    phase4_host_abi_digest, TransactionBinding, TransactionOperation, TransactionOperationMode,
};
use latent_packaging::{build_package, inspect_bundle, PackageInput, PackagingLimits};
use serde_json::json;

fn transaction() -> PackageInput {
    let mut input = fixtures::capsule(Options::default());
    fixtures::mutate_json(&mut input, "capsule.json", |manifest| {
        let limits = &mut manifest["execution"]["limits"];
        limits["stateReadBytes"] = json!(4 * 1024 * 1024);
        limits["stateWriteBytes"] = json!(2 * 1024 * 1024);
        limits["effectCount"] = json!(1);
        limits["wallTimeLimitMillis"] = json!(120_000);
    });
    let companion = TransactionBinding {
        api_version: "latent.dev/v1".into(),
        kind: "TransactionBinding".into(),
        capsule: "tests/packaging".into(),
        deployment: "packaging".into(),
        binding: "packaging-transaction".into(),
        profile: "lsf-transaction-v1".into(),
        host_abi_digest: phase4_host_abi_digest(),
        namespace: "packaging".into(),
        state_schema: format!("sha256:{}", "1".repeat(64)),
        operations: vec![TransactionOperation {
            operation: "inspect".into(),
            mode: TransactionOperationMode::FreshQuery,
            input_format: "test-input-v1".into(),
            result_format: "test-output-v1".into(),
        }],
    };
    input.layers.push(fixtures::layer(
        "transaction-binding.json",
        LayerRole::Asset,
        "application/vnd.latent.transaction-binding.v1+json",
        serde_json::to_vec(&companion).unwrap(),
    ));
    input
}

#[test]
fn exact_companion_selects_transaction_manifest_validation_before_inspection() {
    let bundle = build_package(transaction(), PackagingLimits::default()).unwrap();
    assert_eq!(bundle.surface().unwrap().host_profile(), PHASE4_HOST_ABI_V1);
    let inspected = inspect_bundle(fixtures::raw(&bundle), PackagingLimits::default()).unwrap();
    assert_eq!(inspected.layout().digest(), bundle.layout().digest());
    assert_eq!(
        inspected.surface().unwrap().host_profile(),
        PHASE4_HOST_ABI_V1
    );
}

#[test]
fn missing_or_forged_companion_never_adopts_transaction_budget_hints() {
    let original = transaction();
    let mut missing = original.clone();
    missing
        .layers
        .retain(|layer| layer.path != "transaction-binding.json");
    assert!(build_package(missing, PackagingLimits::default()).is_err());
    for mutation in 0..6 {
        let mut invalid = original.clone();
        match mutation {
            0 => invalid.layers.last_mut().unwrap().media_type = "application/json".into(),
            1 => invalid.layers.last_mut().unwrap().path = "other-binding.json".into(),
            _ => fixtures::mutate_json(&mut invalid, "transaction-binding.json", |companion| {
                match mutation {
                    2 => companion["capsule"] = json!("foreign/capsule"),
                    3 => companion["hostAbiDigest"] = json!(format!("sha256:{}", "0".repeat(64))),
                    4 => companion["profile"] = json!("lsf-transaction-v2"),
                    _ => companion["grant"] = json!(true),
                }
            }),
        }
        assert!(build_package(invalid, PackagingLimits::default()).is_err());
    }
}

#[test]
fn transaction_profile_keeps_wit_component_and_resource_checks_authoritative() {
    for mutation in 0..4 {
        let mut invalid = transaction();
        match mutation {
            0 => fixtures::mutate_json(&mut invalid, "capsule.json", |manifest| {
                manifest["execution"]["limits"]["outboundRequests"] = json!(1);
            }),
            1 => fixtures::mutate_json(&mut invalid, "capsule.json", |manifest| {
                manifest["execution"]["limits"]["stateWriteBytes"] = json!(8 * 1024 * 1024 + 1);
            }),
            2 => invalid.layers[0].bytes[0] = 1,
            _ => {
                invalid
                    .layers
                    .iter_mut()
                    .find(|layer| layer.path == "wit/service.wit")
                    .unwrap()
                    .bytes = b"package foreign:surface@1.0.0; world different {}".to_vec()
            }
        }
        assert!(build_package(invalid, PackagingLimits::default()).is_err());
    }
}
