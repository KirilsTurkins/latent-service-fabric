use super::{fixture, integration::Harness};
use crate::standalone::http::tests::fixture as node_fixture;
use serde_json::json;
use std::{
    path::PathBuf,
    process::{Command, Stdio},
    time::Duration,
};
use tokio::{
    io::{AsyncReadExt, AsyncWriteExt},
    net::TcpStream,
};

async fn get(harness: &Harness, path: &str, extra: &str) -> (u16, String, Vec<u8>) {
    let mut socket = TcpStream::connect(harness.owner.local_addr())
        .await
        .unwrap();
    socket
        .write_all(
            format!(
                "GET {path} HTTP/1.1\r\nHost: web.example.test\r\nConnection: close\r\n{extra}\r\n"
            )
            .as_bytes(),
        )
        .await
        .unwrap();
    node_fixture::response(&mut socket).await
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn browser_boundary_reclaims_two_incomplete_peers_and_continues_eligible_asset_admission() {
    let harness = Harness::configured(|value| {
        value["httpIngress"]["authentication"] = json!({"mode":"public-origins", "origins":[
            {"authority":"web.example.test", "subject":"public", "tenant":"tests"}]});
        value["httpIngress"]["limits"]["maximumConnections"] = json!(2);
        value["httpIngress"]["limits"]["headerTimeoutMillis"] = json!(1000);
        value["httpIngress"]["limits"]["idleTimeoutMillis"] = json!(1000);
    })
    .await;
    let page = harness.publish("browser-residency", b"eligible");
    let mut first = TcpStream::connect(harness.owner.local_addr())
        .await
        .unwrap();
    first.write_all(b"GET / HTTP/1.1\r\nHost: ").await.unwrap();
    node_fixture::wait(|| harness.owner.handle().snapshot().connections == 1).await;
    let (status, headers, body) = get(&harness, &page, "Sec-Fetch-Site: same-origin\r\n").await;
    assert_eq!((status, body), (200, b"eligible".to_vec()));
    assert!(headers.contains("content-security-policy:"));
    node_fixture::wait(|| harness.owner.handle().snapshot().connections == 1).await;
    let mut second = TcpStream::connect(harness.owner.local_addr())
        .await
        .unwrap();
    node_fixture::wait(|| harness.owner.handle().snapshot().connections == 2).await;
    let mut excess = TcpStream::connect(harness.owner.local_addr())
        .await
        .unwrap();
    assert!(
        tokio::time::timeout(Duration::from_millis(500), excess.read_u8())
            .await
            .unwrap()
            .is_err()
    );
    assert_eq!(harness.owner.handle().snapshot().connections, 2);
    node_fixture::trickle_until_closed(first, Duration::from_secs(2)).await;
    assert!(
        tokio::time::timeout(Duration::from_secs(2), second.read_u8())
            .await
            .unwrap()
            .is_err()
    );
    node_fixture::wait(|| harness.owner.handle().snapshot().connections == 0).await;
    assert_eq!(get(&harness, &page, "").await.0, 200);
    assert_eq!(
        get(&harness, &page, "Origin: http://sibling.example.test\r\n")
            .await
            .0,
        403
    );
    assert_eq!(
        harness.node.node.backend.resource_snapshot().stores_created,
        0
    );
    harness.finish().await;
}

fn environment(name: &str) -> PathBuf {
    PathBuf::from(std::env::var_os(name).expect("browser boundary fixture prerequisite"))
}
fn read(path: PathBuf, maximum: u64) -> Vec<u8> {
    assert!(std::fs::metadata(&path).unwrap().len() <= maximum);
    std::fs::read(path).unwrap()
}
fn publish(harness: &Harness, name: &str, files: &[(&str, &str, &[u8])], path: &str) -> String {
    let receipt = harness
        .repository
        .publish_web_package(
            fixture::context(name, 0),
            fixture::browser_upload(files),
            &mut |_| Ok(()),
        )
        .unwrap();
    harness
        .repository
        .select_web_publication(&receipt.receipt.publication)
        .unwrap()
        .asset_url(path)
        .unwrap()
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
#[ignore = "requires the controlled Angular browser build, Node and Chromium"]
async fn actual_browser_boundary_hydrates_navigates_and_blocks_injection_on_live_ingress() {
    let build = environment("LSF_BROWSER_BUILD");
    let node = environment("LSF_BROWSER_NODE");
    let chrome = environment("LSF_BROWSER_CHROME");
    let toolchain = environment("LSF_BROWSER_TOOLCHAIN");
    let selected = std::net::TcpListener::bind("127.0.0.1:0").unwrap();
    let address = selected.local_addr().unwrap();
    let authority = format!("localhost:{}", address.port());
    drop(selected);
    let harness = Harness::configured(|value| {
        value["httpIngress"]["bind"] = json!(address.to_string());
        value["httpIngress"]["authentication"] = json!({"mode":"public-origins", "origins":[
            {"authority":authority, "subject":"browser-fixture", "tenant":"tests"}]});
        value["httpIngress"]["limits"]["maximumConnections"] = json!(8);
        value["httpIngress"]["limits"]["maximumBufferBytes"] = json!(16 * 1024 * 1024);
        value["httpIngress"]["limits"]["headerTimeoutMillis"] = json!(2000);
        value["httpIngress"]["limits"]["idleTimeoutMillis"] = json!(2000);
        value["httpIngress"]["limits"]["writeTimeoutMillis"] = json!(5000);
    })
    .await;
    let client = read(build.join("client.js"), 8 * 1024 * 1024);
    let script = publish(
        &harness,
        "browser-client",
        &[
            ("/app.js", "text/javascript", &client),
            ("/index.html", "text/html", b"client publication"),
            ("/text.txt", "text/plain", b"globalThis.mimeExecuted=true;"),
        ],
        "/app.js",
    );
    let wrong_mime = script.strip_suffix("app.js").unwrap().to_owned() + "text.txt";
    let home = String::from_utf8(read(build.join("home.html"), 128 * 1024))
        .unwrap()
        .replace("__LSF_CLIENT_ASSET__", &script);
    let next = String::from_utf8(read(build.join("next.html"), 128 * 1024))
        .unwrap()
        .replace("__LSF_CLIENT_ASSET__", &script);
    let page = publish(
        &harness,
        "browser-pages",
        &[
            ("/index.html", "text/html", home.as_bytes()),
            ("/next.html", "text/html", next.as_bytes()),
        ],
        "/index.html",
    );
    let result_path = build.join("browser-receipt.json");
    let output = result_path.clone();
    let runner =
        PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../tools/browser-boundary/browser.mjs");
    let status = tokio::task::spawn_blocking(move || {
        Command::new("timeout")
            .args(["--kill-after=5s", "90s"])
            .arg(node)
            .arg(runner)
            .arg(toolchain)
            .arg(chrome)
            .arg(format!("http://{authority}"))
            .arg(page)
            .arg(wrong_mime)
            .arg(output)
            .env_clear()
            .env("PATH", "/usr/bin:/bin")
            .env("HOME", "/tmp")
            .stdin(Stdio::null())
            .status()
            .unwrap()
    })
    .await
    .unwrap();
    assert!(status.success(), "real browser boundary probe failed");
    let receipt: serde_json::Value = serde_json::from_slice(&read(result_path, 4096)).unwrap();
    assert_eq!(receipt["originalDomReused"], true);
    assert_eq!(receipt["navigationHydrated"], true);
    assert_eq!(receipt["componentRenderClaimed"], false);
    assert_eq!(
        harness.node.node.backend.resource_snapshot().stores_created,
        0
    );
    harness.finish().await;
}
