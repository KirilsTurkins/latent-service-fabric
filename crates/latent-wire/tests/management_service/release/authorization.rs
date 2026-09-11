use tonic::{Code, Request};

use super::{artifact, get, list, proto, publish, upload, Harness, ManagementLimits};

#[tokio::test]
async fn rejected_publications_leave_no_visible_release() {
    let harness = Harness::new(ManagementLimits::default()).await;
    let capsule = artifact("acme", "echo", "rejected-publication");
    let valid = upload(&capsule);
    assert_eq!(
        harness
            .releases_client()
            .publish_release(Request::new(valid.clone()))
            .await
            .unwrap_err()
            .code(),
        Code::Unauthenticated
    );
    for identity in ["caller", "bob"] {
        assert_eq!(
            publish(&harness, identity, valid.clone())
                .await
                .unwrap_err()
                .code(),
            Code::PermissionDenied
        );
    }
    let mut cases = Vec::new();
    let mut corrupt = valid.clone();
    corrupt.artifact.as_mut().unwrap().component_bytes.push(0);
    cases.push((corrupt, Code::DataLoss));
    let mut missing = valid.clone();
    missing
        .artifact
        .as_mut()
        .unwrap()
        .contract_metadata_json
        .clear();
    cases.push((missing, Code::InvalidArgument));
    let mut unknown_contract = valid.clone();
    unknown_contract
        .artifact
        .as_mut()
        .unwrap()
        .contract_metadata_json = br#"{"format_version":1,"contracts":[]}"#.to_vec();
    cases.push((unknown_contract, Code::InvalidArgument));
    let mut malformed = valid.clone();
    malformed.artifact.as_mut().unwrap().capsule_manifest_json = b"{".to_vec();
    cases.push((malformed, Code::InvalidArgument));
    for field in [
        "locator",
        "publisher",
        "admission",
        "timestamp",
        "tenant",
        "service",
    ] {
        let mut value = valid.clone();
        let mut claims = proto::ReleaseDescriptor::default();
        match field {
            "locator" => claims.artifact_reference = "../../outside".to_owned(),
            "publisher" => claims.publisher = "forged".to_owned(),
            "admission" => claims.admitted = true,
            "timestamp" => claims.created_at_unix_millis = 1,
            "tenant" => claims.tenant = Some("other".to_owned()),
            "service" => claims.service = "different".to_owned(),
            _ => unreachable!(),
        }
        value.release = Some(claims);
        cases.push((value, Code::InvalidArgument));
    }
    for (value, expected) in cases {
        assert_eq!(
            publish(&harness, "alice", value).await.unwrap_err().code(),
            expected
        );
    }
    assert!(get(&harness, "alice", &capsule.descriptor.release_digest.0)
        .await
        .is_none());
    assert!(list(&harness, "alice", None, None)
        .await
        .unwrap()
        .releases
        .is_empty());
    publish(&harness, "alice", valid).await.unwrap();
    // The global content identity cannot be overwritten with another tenant's metadata.
    let other = artifact("other", "echo", "rejected-publication");
    assert!(publish(&harness, "bob", upload(&other)).await.is_err());
    assert!(list(&harness, "bob", None, None)
        .await
        .unwrap()
        .releases
        .is_empty());
    assert_eq!(
        list(&harness, "alice", None, None)
            .await
            .unwrap()
            .releases
            .len(),
        1
    );
    harness.shutdown().await;
}

#[tokio::test]
async fn oversized_upload_is_rejected_before_publication() {
    let harness = Harness::new(ManagementLimits {
        max_component_bytes: 4,
        ..ManagementLimits::default()
    })
    .await;
    let capsule = artifact("acme", "echo", "five+");
    assert_eq!(
        publish(&harness, "alice", upload(&capsule))
            .await
            .unwrap_err()
            .code(),
        Code::ResourceExhausted
    );
    assert!(list(&harness, "alice", None, None)
        .await
        .unwrap()
        .releases
        .is_empty());
    harness.shutdown().await;
}
