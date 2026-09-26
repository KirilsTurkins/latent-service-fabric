use super::fixture::*;
use latent_ingress::http;
use serde_json::json;
use tempfile::TempDir;
use tokio::io::AsyncWriteExt;

#[tokio::test]
#[ignore = "requires the public web component built by contract CI"]
async fn actual_http_component_authenticates_executes_cancels_and_recovers() {
    let bytes =
        std::fs::read(std::env::var_os("LSF_WEB_COMPONENT").expect("real public web fixture"))
            .unwrap();
    let root = TempDir::new().unwrap();
    let mut value = config(&root);
    value["credentials"].as_array_mut().unwrap().push(json!({"token":"reuse-token-0000000000000000000000000000", "subject":"carol", "tenant":"tests", "role":"invoke"}));
    let fixture = Fixture::start(root, value.clone(), Some(bytes)).await;
    let mut socket = fixture.connect().await;
    for (token, subject) in [
        (TOKEN, "alice"),
        ("reuse-token-0000000000000000000000000000", "carol"),
    ] {
        socket
            .write_all(request("POST", "/", token, 5, false).as_bytes())
            .await
            .unwrap();
        socket.write_all(b"hello").await.unwrap();
        let (status, headers, body) = response(&mut socket).await;
        assert_eq!(status, 200, "{headers}");
        assert!(headers.contains(&format!("x-subject: {subject}\r\n")));
        assert_eq!(body, b"hello");
    }
    socket
        .write_all(request("GET", "/", OTHER, 0, true).as_bytes())
        .await
        .unwrap();
    assert_eq!(response(&mut socket).await.0, 403);
    drop(socket);
    let maximum = call(&fixture, "/maximum").await;
    assert_eq!(maximum.0, 200);
    assert_eq!(maximum.2, vec![255; http::MAX_RESPONSE_BODY]);
    for path in ["/trap", "/invalid-response"] {
        assert_eq!(call(&fixture, path).await.0, 502);
    }
    // All cells occupied; the second request queues with its original owner.
    let mut first = fixture.connect().await;
    first
        .write_all(request("GET", "/spin", TOKEN, 0, true).as_bytes())
        .await
        .unwrap();
    wait(|| fixture.node.backend.resource_snapshot().active_invocations == 1).await;
    let mut second = fixture.connect().await;
    second
        .write_all(request("GET", "/", TOKEN, 0, true).as_bytes())
        .await
        .unwrap();
    wait(|| {
        fixture
            .node
            .scheduler
            .observations(latent_scheduler::CellClass::Standard)
            .queue_depth
            == 1
    })
    .await;
    assert_eq!(call(&fixture, "/").await.0, 503);
    drop(first);
    assert_eq!(response(&mut second).await.0, 200);
    drop(second);
    fixture.idle().await;
    assert_eq!(fixture.node.cleanup_snapshot().unwrap().handoffs, 1);
    assert_eq!(fixture.node.cleanup_snapshot().unwrap().completed, 1);
    assert_eq!(call(&fixture, "/").await.0, 200);
    fixture.idle().await;
    let root = fixture.shutdown().await;
    let reopened = Fixture::start(root, value, None).await;
    assert_eq!(call(&reopened, "/").await.0, 200);
    reopened.shutdown().await;
}
