use super::*;

#[test]
fn committed_publication_requires_descriptor_and_exact_admitted_package() {
    let expected = format!("sha256:{}", "a".repeat(64));
    let mut value = proto::PublishReleaseResponse {
        operation: Some(proto::ReleaseOperationReceipt {
            disposition: proto::ReleaseOperationDisposition::Committed as i32,
            record: Some(proto::ReleaseLifecycleRecord {
                package_digest: Some(expected.clone()),
                ..proto::ReleaseLifecycleRecord::default()
            }),
            ..proto::ReleaseOperationReceipt::default()
        }),
        ..proto::PublishReleaseResponse::default()
    };
    assert!(publication_identity(&value, Some(&expected)).is_err());
    value.release = Some(proto::ReleaseDescriptor::default());
    publication_identity(&value, Some(&expected)).unwrap();
    value
        .operation
        .as_mut()
        .unwrap()
        .record
        .as_mut()
        .unwrap()
        .package_digest = Some(format!("sha256:{}", "b".repeat(64)));
    assert!(publication_identity(&value, Some(&expected)).is_err());
    // A rejected conflict may describe the existing historical package.
    value.operation.as_mut().unwrap().disposition =
        proto::ReleaseOperationDisposition::Rejected as i32;
    value.release = None;
    publication_identity(&value, Some(&expected)).unwrap();
}

#[test]
fn prepared_release_projection_is_bounded_lossless_and_never_execution_authority() {
    let value = proto::PrepareReleaseResponse {
        publication: Some(proto::PublicationRef {
            id: format!("publication:sha256:{}", "a".repeat(64)),
            tenant: "examples".into(),
        }),
        lifecycle_generation: u64::MAX,
        component_digest: format!("sha256:{}", "b".repeat(64)),
        prepared: true,
    };
    projection::checked(&value, 4096).unwrap();
    let output = value.clone().project();
    assert_eq!(output["lifecycleGeneration"], u64::MAX.to_string());
    assert_eq!(output["executionAuthorized"], false);
    assert!(output.get("handle").is_none());
    for index in 0..5 {
        let mut invalid = value.clone();
        match index {
            0 => invalid.publication = None,
            1 => invalid.lifecycle_generation = 0,
            2 => invalid.prepared = false,
            3 => invalid.component_digest = "not-a-digest".into(),
            _ => invalid.component_digest.reserve(4096),
        }
        assert!(projection::checked(&invalid, 4096).is_err());
    }
}
