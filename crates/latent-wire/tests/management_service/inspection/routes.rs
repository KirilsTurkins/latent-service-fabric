use super::*;

async fn current(harness: &Harness, identity: &str) -> proto::RouteSnapshot {
    harness
        .routes_client()
        .get_route_snapshot(request(
            identity,
            proto::GetRouteSnapshotRequest { generation: None },
        ))
        .await
        .unwrap()
        .into_inner()
        .snapshot
        .unwrap()
}

#[tokio::test]
async fn route_projection_is_complete_tenant_scoped_and_digest_bound() {
    let harness = Harness::new(ManagementLimits::default()).await;
    seed(&harness, "acme", "alice", "local-release").await;
    seed(&harness, "other", "bob", "foreign-release").await;
    let local = current(&harness, "alice").await;
    let foreign = current(&harness, "bob").await;
    assert_eq!(local.tenant.as_deref(), Some("acme"));
    assert_eq!(foreign.tenant.as_deref(), Some("other"));
    assert_eq!(local.services.len(), 2);
    assert_eq!(foreign.services.len(), 2);
    assert!(local
        .services
        .iter()
        .all(|route| route.tenant == "acme" && route.service == "echo"));
    assert!(foreign
        .services
        .iter()
        .all(|route| route.tenant == "other" && route.service == "echo"));
    assert!(local.bindings.is_empty() && local.policy_digests.is_empty());
    assert_eq!(local.generation, foreign.generation);
    assert_eq!(
        local.generated_at_unix_millis,
        foreign.generated_at_unix_millis
    );
    assert_ne!(local.snapshot_digest, foreign.snapshot_digest);
    assert_eq!(local.snapshot_digest.len(), 71);
    assert_eq!(current(&harness, "alice").await, local);
    assert_eq!(current(&harness, "operator").await, local);
    let mut client = harness.routes_client();
    let mut spoofed = request(
        "alice",
        proto::GetRouteSnapshotRequest {
            generation: Some(local.generation),
        },
    );
    spoofed
        .metadata_mut()
        .insert("tenant", "other".parse().unwrap());
    assert_eq!(
        client
            .get_route_snapshot(spoofed)
            .await
            .unwrap()
            .into_inner()
            .snapshot
            .unwrap(),
        local
    );
    assert_eq!(
        client
            .get_route_snapshot(request(
                "alice",
                proto::GetRouteSnapshotRequest {
                    generation: Some(local.generation - 1),
                }
            ))
            .await
            .unwrap_err()
            .code(),
        Code::NotFound
    );
    assert_eq!(
        client
            .get_route_snapshot(request(
                "caller",
                proto::GetRouteSnapshotRequest { generation: None }
            ))
            .await
            .unwrap_err()
            .code(),
        Code::PermissionDenied
    );
    drop(client);
    harness.shutdown().await;
}

#[tokio::test]
async fn route_read_exceeding_scope_limit_fails_without_a_partial_snapshot() {
    let harness = Harness::new(ManagementLimits {
        max_route_services: 1,
        ..ManagementLimits::default()
    })
    .await;
    seed(&harness, "acme", "alice", "two-route-rows").await;
    assert_eq!(
        harness
            .routes_client()
            .get_route_snapshot(request(
                "alice",
                proto::GetRouteSnapshotRequest { generation: None }
            ))
            .await
            .unwrap_err()
            .code(),
        Code::ResourceExhausted
    );
    let foreign = current(&harness, "bob").await;
    assert_eq!(foreign.tenant.as_deref(), Some("other"));
    assert!(foreign.services.is_empty());
    harness.shutdown().await;
}
