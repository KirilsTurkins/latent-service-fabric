use super::{artifact, proto, request, upload, Harness, ManagementLimits};
use tonic::{Code, Request};

#[tokio::test]
async fn authenticated_release_lifecycle_has_cas_receipts_and_tenant_private_queries() {
    let harness = Harness::new(ManagementLimits::default()).await;
    let capsule = artifact("acme", "lifecycle", "small-wire-lifecycle");
    let mut input = upload(&capsule);
    input.operation = Some(proto::ReleaseOperationPrecondition {
        operation_id: "create-one".to_owned(),
        expected_generation: Some(0),
    });
    let published = harness
        .releases_client()
        .publish_release(request("alice", input))
        .await
        .unwrap()
        .into_inner();
    let initial = published.operation.unwrap();
    assert_eq!(initial.actor.unwrap().subject, "alice");
    let release = published.release.unwrap();
    let status_request = || proto::GetReleaseLifecycleRequest {
        digest: release.digest.clone(),
    };
    assert_eq!(
        harness
            .releases_client()
            .get_release_lifecycle(Request::new(status_request()))
            .await
            .unwrap_err()
            .code(),
        Code::Unauthenticated
    );
    assert!(harness
        .releases_client()
        .get_release_lifecycle(request("bob", status_request()))
        .await
        .unwrap()
        .into_inner()
        .status
        .is_none());
    let initial = harness
        .releases_client()
        .get_release_lifecycle(request("alice", status_request()))
        .await
        .unwrap()
        .into_inner()
        .status
        .unwrap();
    assert_eq!(
        initial.eligibility,
        proto::ReleaseLiveEligibility::Eligible as i32
    );
    let generation = initial.record.unwrap().generation;
    let revoke = proto::ChangeReleaseLifecycleRequest {
        digest: release.digest.clone(),
        action: proto::ReleaseLifecycleAction::Revoke as i32,
        operation: Some(proto::ReleaseOperationPrecondition {
            operation_id: "revoke-one".to_owned(),
            expected_generation: Some(generation),
        }),
        reason: proto::ReleaseLifecycleReason::SecurityIncident as i32,
    };
    assert_eq!(
        harness
            .releases_client()
            .change_release_lifecycle(request("caller", revoke.clone()))
            .await
            .unwrap_err()
            .code(),
        Code::PermissionDenied
    );
    let receipt = harness
        .releases_client()
        .change_release_lifecycle(request("alice", revoke.clone()))
        .await
        .unwrap()
        .into_inner()
        .operation
        .unwrap();
    assert_eq!(
        receipt.record.as_ref().unwrap().state,
        proto::ReleaseLifecycleState::Revoked as i32
    );
    assert!(receipt.record.as_ref().unwrap().generation > generation);
    assert_eq!(
        harness
            .releases_client()
            .change_release_lifecycle(request("alice", revoke.clone()))
            .await
            .unwrap()
            .into_inner()
            .operation
            .as_ref(),
        Some(&receipt)
    );
    let mut stale = revoke;
    stale.operation.as_mut().unwrap().operation_id = "stale-other".to_owned();
    assert_eq!(
        harness
            .releases_client()
            .change_release_lifecycle(request("alice", stale))
            .await
            .unwrap_err()
            .code(),
        Code::Aborted
    );
    let query = || proto::GetReleaseOperationRequest {
        operation_id: "revoke-one".to_owned(),
    };
    assert_eq!(
        harness
            .releases_client()
            .get_release_operation(request("alice", query()))
            .await
            .unwrap()
            .into_inner()
            .receipt
            .as_ref(),
        Some(&receipt)
    );
    let foreign = harness
        .releases_client()
        .get_release_operation(request("bob", query()))
        .await
        .unwrap()
        .into_inner();
    assert_eq!(
        foreign.lookup,
        proto::ReleaseOperationLookupDisposition::Unknown as i32
    );
    assert!(foreign.receipt.is_none());
    let current = harness
        .releases_client()
        .get_release_lifecycle(request("alice", status_request()))
        .await
        .unwrap()
        .into_inner()
        .status
        .unwrap();
    assert_eq!(
        current.eligibility,
        proto::ReleaseLiveEligibility::Denied as i32
    );
    assert!(harness
        .releases_client()
        .publish_release(request("alice", upload(&capsule)))
        .await
        .is_err());
    // Historical admission remains available after execution eligibility changed.
    let historical = harness
        .releases_client()
        .get_release(request(
            "alice",
            proto::GetReleaseRequest {
                digest: release.digest,
            },
        ))
        .await
        .unwrap()
        .into_inner()
        .release
        .unwrap();
    assert!(historical.admitted);
    harness.shutdown().await;
}

#[tokio::test]
async fn renewal_rejects_missing_preconditions_and_ambiguous_evidence_before_owner_work() {
    let harness = Harness::new(ManagementLimits::default()).await;
    let capsule = artifact("acme", "renew", "small-renewal-input");
    let digest = capsule.descriptor.release_digest.0;
    let mut value = proto::RenewReleaseEvidenceRequest {
        digest: digest.clone(),
        package_digest: digest,
        operation: None,
        evidence: None,
    };
    assert_eq!(
        harness
            .releases_client()
            .renew_release_evidence(request("alice", value.clone()))
            .await
            .unwrap_err()
            .code(),
        Code::InvalidArgument
    );
    value.operation = Some(proto::ReleaseOperationPrecondition {
        operation_id: "renew-one".to_owned(),
        expected_generation: Some(1),
    });
    value.evidence = Some(proto::ReleaseEvidenceUpload {
        signatures: Vec::new(),
        provenance: Vec::new(),
        sboms: Vec::new(),
    });
    assert_eq!(
        harness
            .releases_client()
            .renew_release_evidence(request("alice", value))
            .await
            .unwrap_err()
            .code(),
        Code::InvalidArgument
    );
    let queried = harness
        .releases_client()
        .get_release_operation(request(
            "alice",
            proto::GetReleaseOperationRequest {
                operation_id: "renew-one".to_owned(),
            },
        ))
        .await
        .unwrap()
        .into_inner();
    assert_eq!(
        queried.lookup,
        proto::ReleaseOperationLookupDisposition::Unknown as i32
    );
    harness.shutdown().await;
}
