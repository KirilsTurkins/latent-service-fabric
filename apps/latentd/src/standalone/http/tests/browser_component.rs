use super::fixture::*;
use latent_core::{
    diagnostic::{ActivationDiagnostic, DiagnosticReason, DiagnosticStage},
    ActivationTerminalState, ServiceId, TenantId,
};
use latent_ingress::http::browser;
use serde_json::json;
use tempfile::TempDir;
use tokio::io::AsyncWriteExt;

#[tokio::test]
#[ignore = "requires the public web component built by contract CI"]
async fn actual_http_component_browser_policy_rejects_unsafe_output_without_reflecting_identity() {
    let root = TempDir::new().unwrap();
    let mut value = config(&root);
    value["httpIngress"]["browserOrigins"] = json!([{"authority":AUTHORITY, "tenant":"tests"}]);
    let bytes = std::fs::read(std::env::var_os("LSF_WEB_COMPONENT").unwrap()).unwrap();
    let fixture = Fixture::start(root, value, Some(bytes.clone())).await;
    assert_rejected_outputs(&fixture).await;
    let safe = call(&fixture, "/browser-relative").await;
    assert_eq!(safe.0, 303);
    assert!(safe.1.contains("location: /next?from=fixture\r\n"));
    fixture.idle().await;
    assert_output_observation(&fixture, false);
    fixture.shutdown().await;
    let root = TempDir::new().unwrap();
    let mut value = config(&root);
    value["httpIngress"]["browserOrigins"] = json!([{"authority":AUTHORITY, "tenant":"tests"}]);
    value["httpIngress"]["transport"] = json!({"mode":"trusted-proxy", "peers":["127.0.0.1"]});
    let fixture = Fixture::start(root, value, Some(bytes.clone())).await;
    let mut socket = fixture.connect().await;
    let input = request("GET", "/", TOKEN, 0, true).replace(
        "\r\n\r\n",
        &format!(
            "\r\nOrigin: https://{AUTHORITY}\r\nSec-Fetch-Site: same-origin\r\nForwarded: host=attacker.invalid;proto=http\r\nX-Forwarded-User: administrator\r\nX-Auth-Request-User: administrator\r\nX-Authenticated-User: administrator\r\nRemote-User: administrator\r\nX-Real-IP: 203.0.113.4\r\nX-Original-URL: /administrator\r\n\r\n"
        ),
    );
    socket.write_all(input.as_bytes()).await.unwrap();
    let reply = response(&mut socket).await;
    assert_eq!(reply.0, 200);
    assert!(reply.1.contains("x-subject: alice\r\n"));
    for forbidden in ["administrator", "attacker.invalid", "203.0.113.4", TOKEN] {
        assert!(!reply.1.contains(forbidden));
        assert!(!String::from_utf8_lossy(&reply.2).contains(forbidden));
    }
    fixture.idle().await;
    fixture.shutdown().await;

    // Even forged document metadata on an explicitly public mount cannot turn
    // an application/API target into a static document or reserve a guest cell.
    let root = TempDir::new().unwrap();
    let mut value = config(&root);
    value["httpIngress"]["authentication"] = json!({"mode":"public-origins", "origins":[
        {"authority":AUTHORITY,"tenant":"tests","subject":"public"}]});
    value["httpIngress"]["publicDocumentNavigation"] = json!([
        {"authority":AUTHORITY,"tenant":"tests","mount":"/"}]);
    let fixture = Fixture::start(root, value, Some(bytes)).await;
    let mut socket = fixture.connect().await;
    socket.write_all(format!("GET /api/data HTTP/1.1\r\nHost: {AUTHORITY}\r\nConnection: close\r\nSec-Fetch-Site: cross-site\r\nSec-Fetch-Mode: navigate\r\nSec-Fetch-Dest: document\r\n\r\n").as_bytes()).await.unwrap();
    assert_eq!(response(&mut socket).await.0, 403);
    fixture.idle().await;
    assert_eq!(fixture.node.manager.journal().snapshot().begun, 0);
    assert_eq!(fixture.node.backend.resource_snapshot().stores_created, 0);
    fixture.shutdown().await;
}

async fn assert_rejected_outputs(fixture: &Fixture) {
    for path in [
        "/browser-crlf",
        "/browser-header-bound",
        "/browser-csp",
        "/browser-referrer",
        "/browser-security-case",
        "/browser-header-case",
        "/browser-location-duplicate",
        "/browser-encoding-duplicate",
        "/browser-cors",
        "/browser-compressed",
        "/browser-cookie",
        "/browser-redirect",
        "/browser-charset",
        "/browser-utf8",
    ] {
        let before = fixture.node.manager.journal().snapshot().begun;
        let reply = call(fixture, path).await;
        assert_eq!(reply.0, 502, "{path}");
        assert!(reply.2.is_empty());
        assert_eq!(reply.1.matches("HTTP/1.1").count(), 1);
        assert!(reply
            .1
            .contains(&format!("content-security-policy: {}\r\n", browser::CSP)));
        assert!(!reply.1.contains("x-injected:"));
        assert!(!reply.1.contains("attacker.invalid"));
        assert!(!reply.1.contains("access-control-allow-origin:"));
        assert!(!reply.1.contains("set-cookie:"));
        assert!(reply.1.contains("cache-control: no-store\r\n"));
        for private in [
            "HttpResponseRejected",
            "OutputValidation",
            "synthetic-private-token",
            TOKEN,
        ] {
            assert!(!reply.1.contains(private));
        }
        fixture.idle().await;
        assert_eq!(fixture.node.manager.journal().snapshot().begun, before + 1);
        assert_output_observation(fixture, true);
    }
}

fn assert_output_observation(fixture: &Fixture, rejected: bool) {
    let journal = fixture.node.manager.journal();
    let tenant = TenantId("tests".into());
    let service = ServiceId("web".into());
    let page = journal
        .inspect_roots(&tenant, &service, None, 32, None)
        .unwrap();
    assert!(page.next_page_token.is_none());
    let node = page.nodes.last().unwrap();
    assert_eq!(
        node.terminal_state,
        Some(ActivationTerminalState::Completed)
    );
    assert!(
        !node.diagnostic_is_terminal,
        "output acceptance is distinct from execution success"
    );
    assert_eq!(
        node.diagnostic,
        rejected.then(|| ActivationDiagnostic::new(
            DiagnosticStage::OutputValidation,
            DiagnosticReason::HttpResponseRejected
        ))
    );
    assert_eq!(
        journal
            .inspect_tree(&tenant, &node.activation_id, 32, None)
            .unwrap()
            .nodes[0],
        *node
    );
    assert!(journal
        .inspect_roots(&TenantId("other".into()), &service, None, 32, None)
        .unwrap()
        .nodes
        .is_empty());
}
