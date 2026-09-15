use super::fixture::*;
use latent_artifacts::{
    LifecycleScope, PublicationRef, PublicationSelector, ReleaseLifecycleAction,
    ReleaseLifecycleReason,
};
use latent_control_store::http_routes::{TriggerOperationContext, TriggerOperationRequest};
use latent_control_store::DeploymentStore;
use latent_core::{ActivationId, DeploymentId, TenantId, TriggerId};
use latent_ingress::http;
use latent_routing::RouteResolver;
use serde_json::json;
use std::time::Duration;
use tempfile::TempDir;
use tokio::{
    io::{AsyncReadExt, AsyncWriteExt},
    net::TcpSocket,
};

#[tokio::test]
#[ignore = "requires the public web component built by contract CI"]
async fn actual_http_component_tls_body_and_slow_output_keep_owners_until_retirement() {
    let root = TempDir::new().unwrap();
    let mut value = config(&root);
    // Maximum TLS bodies need room for socket-window/record backpressure on a
    // constrained CI host; progress still cannot renew either absolute limit.
    value["httpIngress"]["limits"]["bodyTimeoutMillis"] = json!(1500);
    value["httpIngress"]["limits"]["writeTimeoutMillis"] = json!(1500);
    let (certificate, key) = super::network::tls_files(&root);
    value["httpIngress"]["transport"] =
        json!({"mode":"tls", "certificateFile":certificate, "privateKeyFile":key});
    let bytes = std::fs::read(std::env::var_os("LSF_WEB_COMPONENT").unwrap()).unwrap();
    let fixture = Fixture::start(root, value, Some(bytes)).await;
    let connector = super::network::connector(&certificate);
    let connect = || async {
        connector
            .connect("localhost".try_into().unwrap(), fixture.connect().await)
            .await
            .unwrap()
    };
    let mut valid = connect().await;
    valid
        .write_all(request("POST", "/", TOKEN, http::MAX_REQUEST_BODY, false).as_bytes())
        .await
        .unwrap();
    valid
        .write_all(&vec![b'z'; http::MAX_REQUEST_BODY])
        .await
        .unwrap();
    valid.flush().await.unwrap();
    let reply = response(&mut valid).await;
    assert_eq!(reply.0, 200);
    assert_eq!(reply.2, vec![b'z'; http::MAX_REQUEST_BODY]);
    // A complete, authenticated keepalive connection also has finite inactivity.
    fixture.idle().await;
    assert!(valid.read_u8().await.is_err());
    let mut slow_body = connect().await;
    slow_body
        .write_all(request("POST", "/", TOKEN, 5, false).as_bytes())
        .await
        .unwrap();
    wait(|| fixture.node.http_snapshot().unwrap().exchanges == 1).await;
    assert_eq!(fixture.node.manager.journal().snapshot().active, 0);
    for _ in 0..3 {
        tokio::time::sleep(Duration::from_millis(45)).await;
        slow_body.write_all(b"z").await.unwrap();
    }
    fixture.idle().await;
    assert!(slow_body.read_u8().await.is_err());
    // Tiny receiver window forces actual TLS/socket backpressure. Reading no
    // response must retain an exchange after the guest itself has completed.
    let tcp = TcpSocket::new_v4().unwrap();
    tcp.set_recv_buffer_size(1024).unwrap();
    let tcp = tcp
        .connect(fixture.node.http_endpoint().unwrap())
        .await
        .unwrap();
    let mut slow = connector
        .connect("localhost".try_into().unwrap(), tcp)
        .await
        .unwrap();
    slow.write_all(request("GET", "/maximum", TOKEN, 0, true).as_bytes())
        .await
        .unwrap();
    wait(|| fixture.node.http_snapshot().unwrap().exchanges == 1).await;
    wait(|| fixture.node.manager.journal().snapshot().active == 0).await;
    assert_eq!(fixture.node.http_snapshot().unwrap().exchanges, 1);
    assert_eq!(fixture.node.http_snapshot().unwrap().connections, 1);
    fixture.idle().await;
    drop(slow);
    let mut recovered = connect().await;
    recovered
        .write_all(request("GET", "/", TOKEN, 0, true).as_bytes())
        .await
        .unwrap();
    assert_eq!(response(&mut recovered).await.0, 200);
    drop((valid, slow_body, recovered));
    fixture.shutdown().await;
}

#[tokio::test]
#[ignore = "requires the public web component built by contract CI"]
#[expect(
    clippy::too_many_lines,
    reason = "ordered cutover and revocation operations keep captured pins and observed execution in one regression"
)]
async fn actual_http_component_pinned_cutover_and_revocation_use_current_authority() {
    let root = TempDir::new().unwrap();
    let value = config(&root);
    let bytes = std::fs::read(std::env::var_os("LSF_WEB_COMPONENT").unwrap()).unwrap();
    let fixture = Fixture::start(root, value, Some(bytes)).await;
    assert_eq!(call(&fixture, "/").await.0, 200);
    fixture.idle().await;
    let tenant = TenantId("tests".into());
    let captured = fixture
        .deployments
        .select_http(
            &http::CanonicalTarget::parse(http::Scheme::Http, AUTHORITY, "/").unwrap(),
            http::Method::Post,
        )
        .unwrap();
    let expected = captured.revision().clone();
    drop(captured);
    let mut pending = fixture.connect().await;
    pending
        .write_all(request("POST", "/", TOKEN, 1, true).as_bytes())
        .await
        .unwrap();
    wait(|| fixture.node.http_snapshot().unwrap().exchanges == 1).await;
    let current = fixture
        .deployments
        .get_versioned(&tenant, &DeploymentId("web".into()))
        .await
        .unwrap()
        .unwrap();
    let mut changed = current.manifest;
    changed
        .metadata
        .annotations
        .insert("cutover".into(), "new-revision".into());
    fixture
        .deployments
        .apply_versioned(&tenant, changed, Some(current.generation))
        .await
        .unwrap();
    pending.write_all(b"x").await.unwrap();
    let (status, headers, body) = response(&mut pending).await;
    assert_eq!(status, 200);
    assert_eq!(body, b"x");
    let id = headers
        .lines()
        .find_map(|h| h.strip_prefix("x-activation: "))
        .unwrap();
    let retained = fixture
        .node
        .manager
        .status(&tenant, &ActivationId(id.into()))
        .unwrap()
        .unwrap();
    assert_eq!(retained.metadata["revision"], expected.revision.0);
    assert_eq!(retained.metadata["release"], expected.release.0);
    assert_eq!(
        retained.metadata["route-generation"],
        expected.route_generation.0.to_string()
    );
    drop(pending);
    fixture.idle().await;
    // Exact stale triggers must reject instead of routing to the new revision.
    assert_ne!(call(&fixture, "/").await.0, 200);
    // Repin POST to the new revision, accept its head, then revoke its package
    // before body completion. This isolates current admission from stale routing.
    let next = fixture.deployments.resolve(&expected.target, None).unwrap();
    let version = fixture
        .deployments
        .get_versioned(&tenant, &DeploymentId("web".into()))
        .await
        .unwrap()
        .unwrap()
        .generation;
    let trigger = fixture
        .deployments
        .get_trigger(&tenant, &TriggerId("web-post".into()))
        .unwrap();
    let mut definition = trigger.value().trigger.as_ref().unwrap().manifest.clone();
    definition.target.revision = Some(next.revision.0);
    definition.target.deployment_generation = Some(version);
    let prepared = fixture
        .deployments
        .prepare_trigger_operation(TriggerOperationRequest::Apply {
            context: TriggerOperationContext {
                tenant: tenant.clone(),
                actor: actor(),
                operation_id: "repin-post".into(),
                expected_state_version: trigger.value().state_version,
            },
            manifest: definition,
            expected_generation: trigger.value().trigger.as_ref().unwrap().generation,
        })
        .unwrap();
    drop(trigger);
    fixture
        .deployments
        .commit_trigger_operation(prepared)
        .unwrap()
        .value()
        .durability
        .as_ref()
        .unwrap();
    let mut revoked = fixture.connect().await;
    revoked
        .write_all(request("POST", "/", TOKEN, 1, true).as_bytes())
        .await
        .unwrap();
    wait(|| fixture.node.http_snapshot().unwrap().exchanges == 1).await;
    let stores_before_revocation = fixture.node.backend.resource_snapshot().stores_created;
    let selector = PublicationSelector::Publication(PublicationRef {
        id: expected.publication.unwrap(),
        scope: LifecycleScope::Tenant(tenant.clone()),
    });
    fixture
        .artifacts
        .change_publication_lifecycle(
            context("revoke", 1),
            &selector,
            ReleaseLifecycleAction::Revoke,
            ReleaseLifecycleReason::OperatorRevocation,
            &mut |_| Ok(()),
        )
        .unwrap();
    revoked.write_all(b"x").await.unwrap();
    // Local admission deliberately reports an unavailable revision, without
    // disclosing its publication's revocation state to the HTTP caller.
    assert_eq!(response(&mut revoked).await.0, 503);
    drop(revoked);
    assert!(
        fixture
            .deployments
            .get_trigger(&tenant, &TriggerId("web-get".into()))
            .unwrap()
            .value()
            .confirmed
    );
    fixture.idle().await;
    assert_eq!(
        fixture.node.backend.resource_snapshot().stores_created,
        stores_before_revocation,
        "revocation must reject before a fresh guest store exists"
    );
    fixture.shutdown().await;
}
