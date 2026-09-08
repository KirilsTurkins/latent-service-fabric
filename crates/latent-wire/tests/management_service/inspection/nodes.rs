use std::sync::atomic::Ordering;

use latent_wire::management::node_inventory_from_proto;
use tonic::Request;

use super::*;

fn get(id: &str) -> proto::GetNodeRequest {
    proto::GetNodeRequest {
        node_id: id.to_owned(),
    }
}

#[tokio::test]
async fn inventory_requires_trusted_operator_before_snapshot_and_round_trips() {
    let harness = Harness::new(ManagementLimits::default()).await;
    let mut client = harness.nodes_client();
    assert_eq!(
        client
            .get_node(Request::new(get("local-test")))
            .await
            .unwrap_err()
            .code(),
        Code::Unauthenticated
    );
    let mut spoofed = request("alice", get("local-test"));
    spoofed
        .metadata_mut()
        .insert("latent.node.operator", "true".parse().unwrap());
    assert_eq!(
        client.get_node(spoofed).await.unwrap_err().code(),
        Code::PermissionDenied
    );
    assert_eq!(
        client
            .get_node(request("caller", get("local-test")))
            .await
            .unwrap_err()
            .code(),
        Code::PermissionDenied
    );
    assert_eq!(harness.inventory.snapshots.load(Ordering::Relaxed), 0);
    let expected = harness.inventory.value.read().unwrap().clone();
    let actual = client
        .get_node(request("operator", get("local-test")))
        .await
        .unwrap()
        .into_inner()
        .inventory
        .unwrap();
    assert_eq!(node_inventory_from_proto(actual).unwrap(), expected);
    assert_eq!(harness.inventory.snapshots.load(Ordering::Relaxed), 1);
    assert!(client
        .get_node(request("operator", get("other-node")))
        .await
        .unwrap()
        .into_inner()
        .inventory
        .is_none());
    drop(client);
    harness.shutdown().await;
}

#[tokio::test]
async fn local_node_list_has_exact_filters_and_no_continuation() {
    let harness = Harness::new(ManagementLimits::default()).await;
    {
        let mut value = harness.inventory.value.write().unwrap();
        value.node.region = Some("east".to_owned());
        value.node.zone = Some("east-1".to_owned());
    }
    let mut client = harness.nodes_client();
    let matching = proto::ListNodesRequest {
        trust_class: Some("local".to_owned()),
        region: Some("east".to_owned()),
        zone: Some("east-1".to_owned()),
        page: Some(proto::PageRequest {
            page_size: 0,
            page_token: None,
        }),
    };
    let response = client
        .list_nodes(request("operator", matching.clone()))
        .await
        .unwrap()
        .into_inner();
    assert_eq!(response.nodes.len(), 1);
    assert_eq!(response.nodes[0].node.as_ref().unwrap().id, "local-test");
    assert!(response.page.unwrap().next_page_token.is_none());
    for index in 0..3 {
        let mut query = matching.clone();
        match index {
            0 => query.trust_class = Some("remote".to_owned()),
            1 => query.region = Some("west".to_owned()),
            _ => query.zone = Some("east-2".to_owned()),
        }
        assert!(client
            .list_nodes(request("operator", query))
            .await
            .unwrap()
            .into_inner()
            .nodes
            .is_empty());
    }
    let observations = harness.inventory.snapshots.load(Ordering::Relaxed);
    for (page_size, page_token, code) in [
        (1, Some("unused".to_owned()), Code::InvalidArgument),
        (1001, None, Code::ResourceExhausted),
    ] {
        let mut query = matching.clone();
        query.page = Some(proto::PageRequest {
            page_size,
            page_token,
        });
        assert_eq!(
            client
                .list_nodes(request("operator", query))
                .await
                .unwrap_err()
                .code(),
            code
        );
    }
    assert_eq!(
        harness.inventory.snapshots.load(Ordering::Relaxed),
        observations
    );
    drop(client);
    harness.shutdown().await;
}

#[tokio::test]
async fn oversized_requests_skip_source_and_oversized_inventory_fails_boundedly() {
    let harness = Harness::new(ManagementLimits::default()).await;
    let mut client = harness.nodes_client();
    assert_eq!(
        client
            .get_node(request("operator", get(&"x".repeat(513))))
            .await
            .unwrap_err()
            .code(),
        Code::ResourceExhausted
    );
    assert_eq!(harness.inventory.snapshots.load(Ordering::Relaxed), 0);
    harness.inventory.value.write().unwrap().node.identity = "x".repeat(4097);
    assert_eq!(
        client
            .get_node(request("operator", get("local-test")))
            .await
            .unwrap_err()
            .code(),
        Code::ResourceExhausted
    );
    harness.inventory.value.write().unwrap().node.identity = "recovered".to_owned();
    assert!(client
        .get_node(request("operator", get("local-test")))
        .await
        .unwrap()
        .into_inner()
        .inventory
        .is_some());
    drop(client);
    harness.shutdown().await;
}
