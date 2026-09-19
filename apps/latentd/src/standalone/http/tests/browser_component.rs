use super::fixture::*;
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
    for path in [
        "/browser-crlf",
        "/browser-header-bound",
        "/browser-csp",
        "/browser-cors",
        "/browser-compressed",
        "/browser-cookie",
        "/browser-redirect",
        "/browser-charset",
        "/browser-utf8",
    ] {
        let reply = call(&fixture, path).await;
        assert_eq!(reply.0, 502, "{path}");
        assert_eq!(reply.1.matches("HTTP/1.1").count(), 1);
        assert!(reply
            .1
            .contains(&format!("content-security-policy: {}\r\n", browser::CSP)));
        assert!(!reply.1.contains("x-injected:"));
        assert!(!reply.1.contains("attacker.invalid"));
        assert!(!reply.1.contains("access-control-allow-origin:"));
        assert!(!reply.1.contains("set-cookie:"));
        assert!(reply.1.contains("cache-control: no-store\r\n"));
        fixture.idle().await;
    }
    let safe = call(&fixture, "/browser-relative").await;
    assert_eq!(safe.0, 303);
    assert!(safe.1.contains("location: /next?from=fixture\r\n"));
    fixture.shutdown().await;
    let root = TempDir::new().unwrap();
    let mut value = config(&root);
    value["httpIngress"]["browserOrigins"] = json!([{"authority":AUTHORITY, "tenant":"tests"}]);
    value["httpIngress"]["transport"] = json!({"mode":"trusted-proxy", "peers":["127.0.0.1"]});
    let fixture = Fixture::start(root, value, Some(bytes)).await;
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
}
