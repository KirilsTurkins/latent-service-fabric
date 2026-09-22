use super::{artifact, list, proto, request, upload, Harness, ManagementLimits};
use prost::Message;
use tonic::Code;

async fn publish(
    harness: &Harness,
    identity: &str,
    tenant: &str,
    version: &str,
    operation: &str,
) -> proto::PublishReleaseResponse {
    let mut capsule = artifact(tenant, "coexist", "identical-executable-bytes");
    capsule.manifest.semantic_version = version.to_owned();
    let mut input = upload(&capsule);
    input.operation = Some(proto::ReleaseOperationPrecondition {
        operation_id: operation.to_owned(),
        expected_generation: Some(0),
    });
    harness
        .releases_client()
        .publish_release(request(identity, input))
        .await
        .unwrap()
        .into_inner()
}

#[tokio::test]
async fn explicit_publications_preserve_shared_components_and_operation_recovery() {
    let harness = Harness::new(ManagementLimits::default()).await;
    let original = publish(&harness, "alice", "acme", "1.0.0", "original").await;
    let corrected = publish(&harness, "alice", "acme", "1.0.1", "corrected").await;
    let foreign = publish(&harness, "bob", "other", "1.0.0", "original").await;
    let first = original.release.as_ref().unwrap();
    let second = corrected.release.as_ref().unwrap();
    assert_eq!(first.digest, second.digest);
    assert_eq!(first.digest, foreign.release.unwrap().digest);
    assert_ne!(first.publication, second.publication);
    assert!(first.package_digest.is_none()); // Trusted-local is never a package claim.
    let selected = first.publication.clone().unwrap();
    assert_eq!(selected.tenant, "acme");
    assert_eq!(selected.id.len(), 83);
    let original_receipt = original.operation.clone().unwrap();
    assert_eq!(original_receipt.publication.as_ref(), Some(&selected));
    assert_eq!(
        original_receipt
            .record
            .as_ref()
            .unwrap()
            .publication
            .as_ref(),
        Some(&selected)
    );

    let exact = proto::GetReleaseRequest {
        publication: Some(selected.clone()),
    };
    assert_eq!(
        harness
            .releases_client()
            .get_release(request("alice", exact.clone()))
            .await
            .unwrap()
            .into_inner()
            .release
            .as_ref(),
        Some(first)
    );
    let page = list(&harness, "alice", None, None).await.unwrap();
    assert_eq!(page.releases.len(), 2);
    assert!(page
        .releases
        .windows(2)
        .all(|pair| pair[0].publication.as_ref().unwrap().id
            < pair[1].publication.as_ref().unwrap().id));
    // Old wire field 1 can still be decoded as an unknown field, but it never
    // selects a publication, even when a component has only one association.
    let mut old_wire = vec![0x0a, u8::try_from(first.digest.len()).unwrap()];
    old_wire.extend_from_slice(first.digest.as_bytes());
    let obsolete = proto::GetReleaseRequest::decode(old_wire.as_slice()).unwrap();
    assert!(obsolete.publication.is_none());
    let failure = harness
        .releases_client()
        .get_release(request("alice", obsolete.clone()))
        .await
        .unwrap_err();
    assert_eq!(failure.code(), Code::InvalidArgument);

    let mutation = proto::ChangeReleaseLifecycleRequest {
        publication: Some(selected.clone()),
        action: proto::ReleaseLifecycleAction::Revoke as i32,
        operation: Some(proto::ReleaseOperationPrecondition {
            operation_id: "revoke-first".into(),
            expected_generation: Some(1),
        }),
        reason: proto::ReleaseLifecycleReason::SecurityIncident as i32,
    };
    let revoked = harness
        .releases_client()
        .change_release_lifecycle(request("alice", mutation.clone()))
        .await
        .unwrap()
        .into_inner();
    assert_eq!(
        revoked.operation.as_ref().unwrap().publication.as_ref(),
        Some(&selected)
    );
    let replay = harness
        .releases_client()
        .change_release_lifecycle(request("alice", mutation.clone()))
        .await
        .unwrap()
        .into_inner();
    assert_eq!(revoked.operation, replay.operation);
    let mut changed = mutation;
    changed.publication = second.publication.clone();
    assert_eq!(
        harness
            .releases_client()
            .change_release_lifecycle(request("alice", changed))
            .await
            .unwrap_err()
            .code(),
        Code::Aborted
    );
    assert_eq!(
        harness
            .releases_client()
            .get_release(request("alice", obsolete))
            .await
            .unwrap_err()
            .code(),
        Code::InvalidArgument
    );
    let status = harness
        .releases_client()
        .get_release_lifecycle(request(
            "alice",
            proto::GetReleaseLifecycleRequest {
                publication: second.publication.clone(),
            },
        ))
        .await
        .unwrap()
        .into_inner()
        .status
        .unwrap();
    assert_eq!(
        status.eligibility,
        proto::ReleaseLiveEligibility::Eligible as i32
    );
    assert_eq!(status.record.unwrap().generation, 1);
    let receipt = harness
        .releases_client()
        .get_release_operation(request(
            "alice",
            proto::GetReleaseOperationRequest {
                operation_id: "original".into(),
            },
        ))
        .await
        .unwrap()
        .into_inner()
        .receipt
        .unwrap();
    assert_eq!(receipt, original_receipt);
    harness.shutdown().await;
}

#[tokio::test]
async fn explicit_selectors_reject_invalid_presence_and_keep_foreign_existence_private() {
    let harness = Harness::new(ManagementLimits::default()).await;
    let publication = publish(&harness, "alice", "acme", "1.0.0", "publish").await;
    let release = publication.release.unwrap();
    let selected = release.publication.unwrap();
    for input in [
        proto::GetReleaseRequest { publication: None },
        proto::GetReleaseRequest {
            publication: Some(proto::PublicationRef::default()),
        },
        proto::GetReleaseRequest {
            publication: Some(proto::PublicationRef {
                id: selected.id.to_uppercase(),
                tenant: "acme".into(),
            }),
        },
        proto::GetReleaseRequest {
            publication: Some(proto::PublicationRef {
                id: selected.id.clone(),
                tenant: "other".into(),
            }),
        },
    ] {
        assert_eq!(
            harness
                .releases_client()
                .get_release(request("alice", input))
                .await
                .unwrap_err()
                .code(),
            Code::InvalidArgument
        );
    }
    for id in [
        selected.id,
        format!("publication:sha256:{}", "0".repeat(64)),
    ] {
        let response = harness
            .releases_client()
            .get_release(request(
                "bob",
                proto::GetReleaseRequest {
                    publication: Some(proto::PublicationRef {
                        id,
                        tenant: "other".into(),
                    }),
                },
            ))
            .await
            .unwrap_err();
        assert_eq!(response.code(), Code::NotFound);
        assert_eq!(response.message(), "publication not found");
    }
    harness.shutdown().await;
}
