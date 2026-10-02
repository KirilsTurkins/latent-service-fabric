use super::*;

fn query(id: &str, size: u32) -> proto::InspectActivationTreeRequest {
    proto::InspectActivationTreeRequest {
        activation_id: id.into(),
        page: Some(proto::PageRequest {
            page_size: size,
            page_token: None,
        }),
    }
}

#[tokio::test]
async fn tree_requires_trusted_tenant_authority_and_reports_missing_history_honestly() {
    let harness = Harness::new(ManagementLimits::default()).await;
    let mut client = harness.nodes_client();
    assert_eq!(
        client
            .inspect_activation_tree(tonic::Request::new(query("private-anchor", 0)))
            .await
            .unwrap_err()
            .code(),
        Code::Unauthenticated
    );
    let mut forged = request("caller", query("private-anchor", 0));
    forged
        .metadata_mut()
        .insert("latent.node.operator", "true".parse().unwrap());
    assert_eq!(
        client
            .inspect_activation_tree(forged)
            .await
            .unwrap_err()
            .code(),
        Code::PermissionDenied
    );
    let missing = client
        .inspect_activation_tree(request("alice", query("private-anchor", 0)))
        .await
        .unwrap()
        .into_inner();
    let foreign = client
        .inspect_activation_tree(request("bob", query("private-anchor", 0)))
        .await
        .unwrap()
        .into_inner();
    assert_eq!(missing, foreign);
    assert_eq!(missing.schema_version, 1);
    assert!(missing.retained_history_only && !missing.history_available && !missing.cursor_expired);
    assert!(missing.nodes.is_empty() && missing.page.unwrap().next_page_token.is_none());
    assert_eq!(
        client
            .inspect_activation_tree(request("alice", query("private-anchor", 129)))
            .await
            .unwrap_err()
            .code(),
        Code::InvalidArgument
    );
    assert_eq!(
        client
            .inspect_activation_tree(request("alice", query("bad id", 0)))
            .await
            .unwrap_err()
            .code(),
        Code::InvalidArgument
    );
    drop(client);
    harness.shutdown().await;
}
