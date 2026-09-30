use super::*;

fn list(id: &str, node: bool) -> proto::ListCapabilitiesRequest {
    proto::ListCapabilitiesRequest {
        deployment_id: id.into(),
        include_node_usage: node,
        ..Default::default()
    }
}

#[cfg(target_os = "linux")]
#[tokio::test]
#[expect(
    clippy::too_many_lines,
    reason = "authenticated transport and actual maintenance retirement barriers"
)]
async fn stream_diagnostics_are_operator_scoped_and_keep_actual_maintenance_visible() {
    use latent_capabilities::broker::{
        io::{IoLimits, IoRuntime},
        pools::{ProviderPoolLimits, ProviderPools},
        ActivationCapabilityRuntime,
    };
    use latent_streams::StreamLifecycle;
    use std::{
        sync::Arc,
        time::{Duration, Instant},
    };

    let harness = Harness::with_capabilities(ManagementLimits::default()).await;
    seed(&harness, "acme", "alice", "local").await;
    let broker = harness.capability_broker.as_ref().unwrap().clone();
    let io = Arc::new(IoRuntime::new(IoLimits::default()).unwrap());
    let pools = Arc::new(
        ProviderPools::new(
            broker.clone(),
            io,
            tokio::runtime::Handle::current(),
            ProviderPoolLimits::default(),
        )
        .unwrap(),
    );
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let configuration = serde_json::from_value(serde_json::json!({
        "formatVersion":1,"profile":"lsf-outbound-streams-v1",
        "destinations":[{"endpoint":{"host":"127.0.0.1","port":listener.local_addr().unwrap().port(),"transport":"tcp"},
            "addresses":{"networks":["127.0.0.1/32"],"specialAddresses":["127.0.0.1"]},
            "resolution":{"kind":"static","addresses":["127.0.0.1"]}}],
        "limits":{"maximumTransferBytes":65536,"idleTimeoutMillis":1000,"absoluteTimeoutMillis":5000}
    })).unwrap();
    let owner = Arc::new(
        StreamLifecycle::install_for_qualification(pools.clone(), "streams", 1, configuration)
            .unwrap(),
    );
    let weak = Arc::downgrade(&owner);
    let runtime = ActivationCapabilityRuntime::new(broker.clone(), harness.deployments.clone());
    runtime.install_outbound_streams(owner.clone()).unwrap();
    let maintenance = owner.maintenance().unwrap();
    let stop = maintenance.stop_handle();
    let driver = tokio::spawn(maintenance.run());
    let mut client =
        proto::capability_service_client::CapabilityServiceClient::new(harness.channel.clone());
    for identity in ["alice", "caller", "bob"] {
        assert_eq!(
            client
                .list_capabilities(request(identity, list("local", true)))
                .await
                .unwrap_err()
                .code(),
            Code::PermissionDenied
        );
    }
    let mut spoofed = request("caller", list("local", true));
    spoofed
        .metadata_mut()
        .insert("latent.node.operator", "true".parse().unwrap());
    assert_eq!(
        client.list_capabilities(spoofed).await.unwrap_err().code(),
        Code::PermissionDenied
    );
    let node = client
        .list_capabilities(request("operator", list("local", true)))
        .await
        .unwrap()
        .into_inner()
        .node_usage
        .unwrap();
    assert_eq!(node.counters["stream_configuration_epoch"], 1);
    assert_eq!(node.counters["stream_maintenance_owners"], 1);
    assert_eq!(node.counters["stream_owners"], 0);
    assert_eq!(node.counters["stream_stopped"], 0);
    assert_eq!(
        node.counters
            .keys()
            .filter(|key| key.starts_with("stream_"))
            .count(),
        10
    );
    assert!(!format!("{node:?}").contains("127.0.0.1"));
    assert!(
        tokio::time::timeout(Duration::from_millis(20), listener.accept())
            .await
            .is_err()
    );
    owner
        .drain(Instant::now() + Duration::from_secs(1))
        .await
        .unwrap();
    stop.stop();
    driver.await.unwrap().unwrap();
    let stopped = client
        .list_capabilities(request("operator", list("local", true)))
        .await
        .unwrap()
        .into_inner()
        .node_usage
        .unwrap();
    assert_eq!(stopped.counters["stream_stopped"], 1);
    assert_eq!(stopped.counters["stream_maintenance_owners"], 0);
    assert_eq!(stopped.counters["stream_connections"], 0);
    drop(stop);
    drop(runtime);
    drop(owner);
    assert!(weak.upgrade().is_none());
    let gone = client
        .list_capabilities(request("operator", list("local", true)))
        .await
        .unwrap()
        .into_inner()
        .node_usage
        .unwrap();
    assert!(gone
        .unavailable
        .contains(&"outbound-streams-no-retained-observation".into()));
    assert!(!gone.counters.contains_key("stream_connections"));
    drop(client);
    let snapshot = pools.snapshot().unwrap();
    assert_eq!(snapshot.connections, 0);
    assert_eq!(snapshot.running_requests, 0);
    assert!(pools
        .shutdown(Instant::now() + Duration::from_secs(1))
        .await
        .unwrap()
        .is_clean());
    harness.shutdown().await;
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
