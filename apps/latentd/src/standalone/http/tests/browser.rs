use super::fixture::*;
use latent_ingress::http::{browser, Scheme};
use serde_json::json;
use tempfile::TempDir;
use tokio::io::AsyncWriteExt;

async fn check(fixture: &Fixture, raw: String, expected: u16) {
    let mut socket = fixture.connect().await;
    socket.write_all(raw.as_bytes()).await.unwrap();
    let (status, headers, body) = response(&mut socket).await;
    assert_eq!(status, expected);
    let lower = headers.to_ascii_lowercase();
    for header in browser::security_headers(Scheme::Http) {
        assert!(lower.contains(&format!(
            "{}: {}\r\n",
            header.name,
            std::str::from_utf8(header.value)
                .unwrap()
                .to_ascii_lowercase()
        )));
    }
    assert!(!lower.contains("access-control-allow"));
    assert!(!headers.contains(TOKEN));
    assert!(body.is_empty());
    drop(socket);
    fixture.idle().await;
    assert_eq!(fixture.node.manager.journal().snapshot().terminal, 0);
}
fn extra(method: &str, path: &str, token: &str, headers: &str) -> String {
    request(method, path, token, 0, true).replace("\r\n\r\n", &format!("\r\n{headers}\r\n"))
}

#[tokio::test]
async fn browser_boundary_rejects_cross_origin_csrf_spoofing_and_tenant_aliases_before_routing() {
    let root = TempDir::new().unwrap();
    let mut value = config(&root);
    value["httpIngress"]["browserOrigins"] = json!([{"authority":AUTHORITY,"tenant":"tests"}]);
    let fixture = Fixture::start(root, value, None).await;
    for headers in [
        "Origin: null\r\n",
        "Origin: http://sibling.example.test\r\n",
        "Origin: http://web.example.test\r\nSec-Fetch-Site: same-site\r\n",
        "Sec-Fetch-Site: cross-site\r\n",
        "Sec-Fetch-Mode: navigate\r\n",
    ] {
        check(&fixture, extra("POST", "/", TOKEN, headers), 403).await;
    }
    check(
        &fixture,
        extra(
            "GET",
            "/",
            TOKEN,
            "Origin: http://web.example.test\r\nOrigin: http://web.example.test\r\n",
        ),
        400,
    )
    .await;
    check(
        &fixture,
        extra("GET", "/", OTHER, "Sec-Fetch-Site: same-origin\r\n"),
        403,
    )
    .await;
    check(
        &fixture,
        extra("GET", "/_lsf/assets/missing/index.html", OTHER, ""),
        403,
    )
    .await;
    check(
        &fixture,
        extra(
            "OPTIONS",
            "/",
            TOKEN,
            "Origin: http://web.example.test\r\nAccess-Control-Request-Method: POST\r\n",
        ),
        403,
    )
    .await;
    check(
        &fixture,
        extra(
            "POST",
            "/",
            TOKEN,
            "Origin: http://web.example.test\r\nSec-Fetch-Site: same-origin\r\n",
        ),
        404,
    )
    .await;
    check(
        &fixture,
        extra(
            "GET",
            "/",
            TOKEN,
            "Sec-Fetch-Site: none\r\nSec-Fetch-Mode: navigate\r\n",
        ),
        404,
    )
    .await;
    fixture.shutdown().await;
}

#[tokio::test]
async fn browser_boundary_framing_traversal_cookie_and_compression_abuse_is_bounded() {
    let root = TempDir::new().unwrap();
    let value = config(&root);
    let fixture = Fixture::start(root, value, None).await;
    for path in [
        "/../private",
        "/%2e%2e/private",
        "/%2fprivate",
        "/%5cprivate",
        "/%252fprivate",
        "/a//b",
    ] {
        check(&fixture, request("GET", path, TOKEN, 0, true), 400).await;
    }
    for (headers, status) in [
        ("Transfer-Encoding: chunked\r\n".to_owned(), 400),
        ("Content-Length: 0\r\n".to_owned(), 400),
        ("X-Test: good\r\nHost: attacker.invalid\r\n".to_owned(), 400),
        ("Content-Encoding: gzip\r\n".to_owned(), 415),
        ("Content-Encoding: br\r\n".to_owned(), 415),
        ("Cookie: session=one; session=two\r\n".to_owned(), 400),
        (
            format!(
                "Cookie: a={}\r\nCookie: b={}\r\nCookie: c={}\r\nCookie: d={}\r\n",
                "x".repeat(1024),
                "x".repeat(1024),
                "x".repeat(1024),
                "x".repeat(1024)
            ),
            431,
        ),
        (format!("X-Header: {}\r\n", "x".repeat(16384)), 431),
        ("Origin: http://web.example.test\r\n".to_owned(), 403),
    ] {
        check(&fixture, extra("POST", "/", TOKEN, &headers), status).await;
    }
    check(&fixture, request("GET", "/", TOKEN, 0, true), 404).await;
    fixture.shutdown().await;
}

#[tokio::test]
async fn browser_boundary_proxy_scheme_and_origin_are_fixed_not_forwarded() {
    let root = TempDir::new().unwrap();
    let mut value = config(&root);
    value["httpIngress"]["transport"] = json!({"mode":"trusted-proxy", "peers":["127.0.0.1"]});
    value["httpIngress"]["browserOrigins"] = json!([{"authority":AUTHORITY,"tenant":"tests"}]);
    let fixture = Fixture::start(root, value, None).await;
    let mut socket = fixture.connect().await;
    socket.write_all(extra("GET", "/", TOKEN, "Origin: https://web.example.test\r\nForwarded: host=attacker.invalid;proto=http\r\nX-Forwarded-User: administrator\r\n").as_bytes()).await.unwrap();
    let (status, headers, _) = response(&mut socket).await;
    assert_eq!(status, 404);
    assert!(headers.contains("strict-transport-security: max-age=31536000"));
    assert!(!headers.contains("attacker.invalid"));
    drop(socket);
    fixture.idle().await;
    fixture.shutdown().await;
}
