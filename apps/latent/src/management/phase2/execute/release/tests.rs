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
