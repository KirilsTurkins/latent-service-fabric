use super::*;

fn list(id: &str, node: bool) -> proto::ListCapabilitiesRequest {
    proto::ListCapabilitiesRequest {
        deployment_id: id.into(),
        include_node_usage: node,
        ..Default::default()
    }
}
#[tokio::test]
async fn capability_inspection_is_tenant_scoped_operator_gated_and_lease_bounded() {
    let harness = Harness::with_capabilities(ManagementLimits::default()).await;
    seed(&harness, "acme", "alice", "local").await;
    seed(&harness, "other", "bob", "foreign").await;
    let mut client =
        proto::capability_service_client::CapabilityServiceClient::new(harness.channel.clone());
    let page = client
        .list_capabilities(request("alice", list("local", false)))
        .await
        .unwrap()
        .into_inner();
    assert_eq!(page.revision.unwrap().deployment_id, "local");
    assert_eq!(page.state, "binding-plan-unavailable");
    assert!(page.capabilities.is_empty() && page.node_usage.is_none());
    assert_eq!(page.tenant_usage.unwrap().scope, "tenant");
    for (identity, body) in [
        ("alice", list("foreign", false)),
        ("caller", list("local", false)),
        ("alice", list("local", true)),
    ] {
        assert_eq!(
            client
                .list_capabilities(request(identity, body))
                .await
                .unwrap_err()
                .code(),
            Code::PermissionDenied
        );
    }
    let page = client
        .list_capabilities(request("operator", list("local", true)))
        .await
        .unwrap()
        .into_inner();
    let node = page.node_usage.unwrap();
    assert_eq!(node.scope, "node");
    assert!(node
        .unavailable
        .contains(&"provider-pools-no-retained-owner".into()));
    let control = harness.policy_control.as_ref().unwrap();
    let lease = control.store().reserve_inspection().unwrap();
    assert_eq!(
        client
            .list_capabilities(request("alice", list("local", false)))
            .await
            .unwrap_err()
            .code(),
        Code::ResourceExhausted
    );
    drop(lease);
    client
        .list_capabilities(request("alice", list("local", false)))
        .await
        .unwrap();
    let explanation = proto::ExplainCapabilityGrantRequest {
        deployment_id: "local".into(),
        capability_id: "latent:secrets/reader@0.1.0".into(),
        operation: "read".into(),
        resource_document: r#"{"kind":"secrets","reference":"sensitive-reference"}"#.into(),
        hypothetical_subject: Some(proto::CapabilityInspectionSubject {
            kind: "service".into(),
            subject: "echo".into(),
            service: Some("echo".into()),
        }),
        ..Default::default()
    };
    let result = client
        .explain_capability_grant(request("alice", explanation.clone()))
        .await
        .unwrap()
        .into_inner();
    assert!(!result.allowed);
    assert_eq!(result.obligations["descriptive-only"], "true");
    assert!(!format!("{result:?}").contains("sensitive-reference"));
    assert_eq!(
        client
            .explain_capability_grant(request("bob", explanation.clone()))
            .await
            .unwrap_err()
            .code(),
        Code::PermissionDenied
    );
    let spoofed = proto::ExplainCapabilityGrantRequest {
        principal: "operator".into(),
        ..explanation
    };
    assert_eq!(
        client
            .explain_capability_grant(request("alice", spoofed))
            .await
            .unwrap_err()
            .code(),
        Code::InvalidArgument
    );
    harness.shutdown().await;
}
