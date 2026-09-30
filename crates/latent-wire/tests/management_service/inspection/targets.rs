//! Real managed RPC/catalog tests. Component execution is a separate qualifier.
use super::*;
use latent_routing::RouteResolver;
fn query() -> proto::InspectHttpTargetRequest {
    proto::InspectHttpTargetRequest {
        service: "echo".into(),
        contract: "acme:echo/api@1.0.0".into(),
        function: "echo".into(),
        ..proto::InspectHttpTargetRequest::default()
    }
}

#[tokio::test]
async fn targets_require_authenticated_management_scope_and_bounded_exact_selectors() {
    let harness = Harness::new(ManagementLimits::default()).await;
    let mut client = harness.nodes_client();
    assert_eq!(
        client
            .inspect_http_target(tonic::Request::new(query()))
            .await
            .unwrap_err()
            .code(),
        Code::Unauthenticated
    );
    let mut forged = request("caller", query());
    forged
        .metadata_mut()
        .insert("latent.node.operator", "true".parse().unwrap());
    assert_eq!(
        client.inspect_http_target(forged).await.unwrap_err().code(),
        Code::PermissionDenied
    );
    let mut invalid = query();
    invalid.publication = Some(proto::PublicationRef {
        tenant: "other".into(),
        id: format!("publication:sha256:{}", "a".repeat(64)),
    });
    assert_eq!(
        client
            .inspect_http_target(request("alice", invalid))
            .await
            .unwrap_err()
            .code(),
        Code::InvalidArgument
    );
    let mut invalid = query();
    invalid.function = "x".repeat(513);
    assert_eq!(
        client
            .inspect_http_target(request("alice", invalid))
            .await
            .unwrap_err()
            .code(),
        Code::ResourceExhausted
    );
    let mut invalid = query();
    invalid.maximum_wait_millis = 30_001;
    assert_eq!(
        client
            .inspect_http_target(request("alice", invalid))
            .await
            .unwrap_err()
            .code(),
        Code::InvalidArgument
    );
    drop(client);
    harness.shutdown().await;
}

#[tokio::test]
async fn target_rpc_returns_coherent_candidate_identity_without_invocation_or_receipts() {
    let harness = Harness::new(ManagementLimits::default()).await;
    seed(&harness, "acme", "alice", "blue").await;
    seed(&harness, "acme", "alice", "green").await;
    let mut client = harness.nodes_client();
    let before = harness.deployments.generation();
    let value = client
        .inspect_http_target(request("alice", query()))
        .await
        .unwrap()
        .into_inner();
    assert_eq!(value.schema_version, 1);
    assert_eq!(value.tenant, "acme");
    assert_eq!(value.candidates.len(), 2);
    assert_eq!(value.route_generation, before.0);
    assert_eq!(value.binding_generation, before.0);
    assert_eq!(value.state, proto::TargetObservationState::Coherent as i32);
    assert!(value.selected_revision_id.is_none() && !value.live_grants_checked);
    assert!(value
        .candidates
        .iter()
        .all(|candidate| candidate.export_compatible
            && !candidate.http_compatible
            && candidate.publication.is_some()
            && candidate.requested_publication == candidate.publication
            // The existing raw local fixture has no verified package association.
            && candidate.package_digest.is_none()
            && !candidate.eligible
            && candidate.reasons.contains(&(proto::TargetReason::UnmanagedPublication as i32))
            && candidate.http_bindings.is_empty()));
    let mut exact = query();
    exact.revision_id = Some(value.candidates[0].revision_id.clone());
    exact.publication = value.candidates[0].publication.clone();
    exact.include_preparation = true;
    let exact = client
        .inspect_http_target(request("alice", exact))
        .await
        .unwrap()
        .into_inner();
    assert_eq!(exact.candidates.len(), 1);
    let preparation = exact.candidates[0].preparation.as_ref().unwrap();
    assert_eq!(
        preparation.state,
        proto::TargetPreparationState::Unavailable as i32
    );
    assert!(
        preparation.diagnostic.is_none()
            && preparation.import_count.is_none()
            && preparation.exports.is_empty()
    );
    let foreign = client
        .inspect_http_target(request("bob", query()))
        .await
        .unwrap()
        .into_inner();
    assert_eq!(foreign.tenant, "other");
    assert!(foreign.candidates.is_empty());
    let mut selected = query();
    selected.routing_key = Some("supported-hypothetical-context".into());
    let selected = client
        .inspect_http_target(request("alice", selected))
        .await
        .unwrap()
        .into_inner();
    assert!(selected
        .selected_revision_id
        .as_ref()
        .is_some_and(|id| value
            .candidates
            .iter()
            .any(|candidate| &candidate.revision_id == id)));
    assert_eq!(selected.catalog_transaction, value.catalog_transaction);
    assert_eq!(harness.deployments.generation(), before);
    drop(client);
    harness.shutdown().await;
}
