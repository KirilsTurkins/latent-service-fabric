#[path = "inspection/nodes.rs"]
mod nodes;
#[path = "inspection/routes.rs"]
mod routes;

use latent_artifacts::ArtifactRepository;
use latent_wire::management::{proto, ManagementLimits};
use tonic::Code;

use super::support::{artifact, deployment, request, Harness};

async fn seed(harness: &Harness, tenant: &str, identity: &str, marker: &str) {
    let release = harness
        .artifacts
        .publish(artifact(tenant, "echo", marker))
        .await
        .unwrap();
    harness
        .deployments_client()
        .apply_deployment(request(
            identity,
            proto::ApplyDeploymentRequest {
                operation: None,
                deployment: Some(deployment(marker, tenant, "echo", &release.release_digest)),
                expected_generation: Some(0),
            },
        ))
        .await
        .unwrap();
}

#[tokio::test]
async fn cluster_only_node_operations_and_route_watch_are_unimplemented() {
    let harness = Harness::new(ManagementLimits::default()).await;
    let mut nodes = harness.nodes_client();
    assert_eq!(
        nodes
            .register_node(request(
                "operator",
                proto::RegisterNodeRequest { node: None }
            ))
            .await
            .unwrap_err()
            .code(),
        Code::Unimplemented
    );
    assert_eq!(
        nodes
            .report_inventory(request(
                "operator",
                proto::ReportInventoryRequest { inventory: None }
            ))
            .await
            .unwrap_err()
            .code(),
        Code::Unimplemented
    );
    assert_eq!(
        nodes
            .heartbeat(request("operator", proto::HeartbeatRequest::default()))
            .await
            .unwrap_err()
            .code(),
        Code::Unimplemented
    );
    assert_eq!(
        harness
            .routes_client()
            .watch_route_snapshots(request(
                "operator",
                proto::WatchRouteSnapshotsRequest {
                    after_generation: 0,
                    node_id: "local-test".to_owned(),
                }
            ))
            .await
            .unwrap_err()
            .code(),
        Code::Unimplemented
    );
    assert_eq!(
        harness
            .inventory
            .snapshots
            .load(std::sync::atomic::Ordering::Relaxed),
        0
    );
    drop(nodes);
    harness.shutdown().await;
}
