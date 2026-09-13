use super::*;

#[test]
fn managed_apply_binds_full_normalized_manifest_not_only_component_and_generation() {
    let manifest = latent_manifest::JsonManifestCodec::default()
        .decode_deployment(include_bytes!(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../../examples/echo-contract/deployment.json"
        )))
        .unwrap();
    let value =
        latent_wire::management::deployment_to_proto(&latent_control_store::VersionedDeployment {
            manifest,
            generation: 7,
        })
        .unwrap();
    let mut request = value.clone();
    request.generation = 0;
    let expected = manifest_digest(&request).unwrap();
    assert_eq!(manifest_digest(&value).unwrap(), expected);
    // Generation zero is valid for a request but remains invalid in responses.
    let maximum = latent_control_store::deployment_operations::MAX_REQUEST_BYTES;
    assert!(bounds::checked(&request, maximum).is_err());
    bounds::checked(&value, maximum).unwrap();
    let receipt = proto::DeploymentOperationReceipt {
        manifest_digest: expected.clone(),
        ..proto::DeploymentOperationReceipt::default()
    };
    check_manifest(&value, &receipt, &expected).unwrap();
    let mut changed = value.clone();
    changed.route_weight = if value.route_weight == 1000 {
        2000
    } else {
        1000
    };
    assert_eq!(changed.release_digest, value.release_digest);
    assert_eq!(changed.generation, value.generation);
    assert!(check_manifest(&changed, &receipt, &expected).is_err());
    let mut wrong_receipt = receipt;
    wrong_receipt.manifest_digest = format!("sha256:{}", "f".repeat(64));
    assert!(check_manifest(&value, &wrong_receipt, &expected).is_err());
}
