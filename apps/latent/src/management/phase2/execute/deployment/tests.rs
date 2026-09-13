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
            publication: None,
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

#[test]
fn explicit_apply_preserves_original_manifest_and_rejects_publication_substitution() {
    let mut manifest = latent_manifest::JsonManifestCodec::default()
        .decode_deployment(include_bytes!(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../../examples/echo-contract/deployment.json"
        )))
        .unwrap();
    let id = format!("publication:sha256:{}", "a".repeat(64))
        .parse()
        .unwrap();
    manifest.publication = Some(id);
    let response =
        latent_wire::management::deployment_to_proto(&latent_control_store::VersionedDeployment {
            publication: manifest
                .publication
                .as_ref()
                .map(|id| latent_artifacts::PublicationRef {
                    id: id.clone(),
                    scope: latent_artifacts::LifecycleScope::Tenant(
                        manifest.metadata.tenant.clone().expect("validated tenant"),
                    ),
                }),
            manifest,
            generation: 7,
        })
        .unwrap();
    let component = response.release_digest.clone();
    let selected = response.publication.clone().unwrap();
    let expected = manifest_digest(&response).unwrap();
    let mut input = response.clone();
    input.release_digest.clear();
    input.requested_publication = None;
    input.generation = 0;
    let mut request = proto::ApplyDeploymentRequest {
        deployment: Some(input),
        expected_component_digest: Some(component.clone()),
        ..Default::default()
    };
    let original = request.clone();
    assert_eq!(request_manifest(&mut request).unwrap(), expected);
    assert_eq!(request, original);
    let receipt = proto::DeploymentOperationReceipt {
        publication: Some(selected.clone()),
        manifest_digest: expected.clone(),
        ..Default::default()
    };
    let mut reply = proto::ApplyDeploymentResponse {
        deployment: Some(response.clone()),
        receipt: Some(receipt),
        ..Default::default()
    };
    check_publication(&reply, &component, Some(&selected)).unwrap();
    check_manifest(
        reply.deployment.as_ref().unwrap(),
        reply.receipt.as_ref().unwrap(),
        &expected,
    )
    .unwrap();
    for changed in [
        None,
        Some(proto::PublicationRef {
            id: format!("publication:sha256:{}", "b".repeat(64)),
            tenant: selected.tenant.clone(),
        }),
        Some(proto::PublicationRef {
            id: selected.id.clone(),
            tenant: "foreign".into(),
        }),
    ] {
        let mut substituted = reply.clone();
        substituted.deployment.as_mut().unwrap().publication = changed.clone();
        substituted
            .deployment
            .as_mut()
            .unwrap()
            .requested_publication = changed.clone();
        substituted.receipt.as_mut().unwrap().publication = changed;
        assert!(check_publication(&substituted, &component, Some(&selected)).is_err());
    }
    reply.receipt.as_mut().unwrap().publication = None;
    assert!(check_publication(&reply, &component, Some(&selected)).is_err());
    let mut both = original.clone();
    both.deployment.as_mut().unwrap().release_digest = component;
    assert!(request_manifest(&mut both).is_err());
    let mut missing = original;
    missing.expected_component_digest = None;
    assert!(request_manifest(&mut missing).is_err());
}
