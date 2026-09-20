use super::fixture::*;
use crate::{
    config::NodeConfig,
    standalone::{RuntimeThreads, StandaloneNode},
};
use serde_json::json;
use std::time::Duration;
use tempfile::TempDir;
use tokio::{
    io::{AsyncReadExt, AsyncWriteExt},
    net::TcpListener,
};

#[tokio::test]
async fn failed_http_bind_retires_started_rpc_and_catalog_owners() {
    let root = TempDir::new().unwrap();
    let occupied = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let rpc = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let rpc_address = rpc.local_addr().unwrap();
    drop(rpc);
    let mut value = config(&root);
    value["bind"] = json!(rpc_address.to_string());
    value["httpIngress"]["bind"] = json!(occupied.local_addr().unwrap().to_string());
    let settings = serde_json::from_value::<NodeConfig>(value.clone())
        .unwrap()
        .derive()
        .unwrap();
    let result = StandaloneNode::start(
        settings,
        tokio::runtime::Handle::current(),
        RuntimeThreads::default(),
    )
    .await;
    assert!(matches!(result, Err(e) if e.message == "http-ingress-owner-unavailable"));
    drop(occupied);
    // Reusing both exact ports and the same durable directories proves startup
    // did not leave a listener or a catalog lock owned by an orphaned task.
    let fixture = Fixture::start(root, value, None).await;
    assert_eq!(call(&fixture, "/").await.0, 404);
    fixture.shutdown().await;
}

#[tokio::test]
async fn tls_configuration_refuses_readable_or_symlinked_private_keys() {
    use std::os::unix::fs::{symlink, PermissionsExt};
    let root = TempDir::new().unwrap();
    let (certificate, key) = super::network::tls_files(&root);
    let mut value = config(&root);
    value["httpIngress"]["transport"] =
        json!({"mode":"tls", "certificateFile":certificate, "privateKeyFile":key});
    std::fs::set_permissions(&key, std::fs::Permissions::from_mode(0o644)).unwrap();
    assert!(serde_json::from_value::<NodeConfig>(value.clone())
        .unwrap()
        .derive()
        .is_err());
    std::fs::set_permissions(&key, std::fs::Permissions::from_mode(0o600)).unwrap();
    serde_json::from_value::<NodeConfig>(value.clone())
        .unwrap()
        .derive()
        .unwrap();
    let link = root.path().join("key-link.pem");
    symlink(&key, &link).unwrap();
    value["httpIngress"]["transport"]["privateKeyFile"] = json!(link);
    assert!(serde_json::from_value::<NodeConfig>(value)
        .unwrap()
        .derive()
        .is_err());
}

fn public_request(path: &str) -> String {
    format!("GET {path} HTTP/1.1\r\nHost: {AUTHORITY}\r\n\r\n")
}

// The lifecycle deadlines below begin with guest execution. Compilation is
// bounded setup, using the exact tenant-scoped publication selected by ingress.
async fn prepare_lifecycle_component(fixture: &Fixture, release: &latent_core::ReleaseDigest) {
    use latent_artifacts::ArtifactRepository;
    use latent_executor::ExecutionBackend;
    let mut key = fixture.node.backend.preparation_key(release).unwrap();
    key.publication = Some(
        fixture
            .artifacts
            .select_execution_publication(&latent_core::TenantId("tests".into()), release, None)
            .unwrap()
            .expect("published lifecycle component")
            .id,
    );
    let prepared = tokio::time::timeout(
        Duration::from_secs(5),
        fixture
            .node
            .backend
            .prepare_from_repository(fixture.artifacts.as_ref(), &key),
    )
    .await
    .expect("bounded lifecycle compilation setup")
    .expect("lifecycle component preparation");
    drop(prepared);
}

#[tokio::test]
#[ignore = "requires the public web component built by contract CI"]
async fn actual_http_component_public_origin_deadline_and_forced_shutdown_reclaim_owners() {
    let root = TempDir::new().unwrap();
    let mut value = config(&root);
    value["execution"]["maximumWallTimeMillis"] = json!(1500);
    value["shutdownGraceMillis"] = json!(20);
    value["httpIngress"]["limits"]["maximumRequestsPerConnection"] = json!(2);
    value["httpIngress"]["authentication"] = json!({"mode":"public-origins", "origins":[{"authority":AUTHORITY,"subject":"public-web","tenant":"tests"}]});
    let bytes = std::fs::read(std::env::var_os("LSF_WEB_COMPONENT").unwrap()).unwrap();
    let release = latent_artifacts::content_digest(&bytes);
    let fixture = Fixture::start(root, value, Some(bytes)).await;
    prepare_lifecycle_component(&fixture, &release).await;
    let mut socket = fixture.connect().await;
    for _ in 0..2 {
        socket
            .write_all(public_request("/").as_bytes())
            .await
            .unwrap();
        let reply = response(&mut socket).await;
        assert_eq!(reply.0, 200);
        assert!(reply.1.contains("x-subject: public-web\r\n"));
    }
    assert!(
        socket.read_u8().await.is_err(),
        "request cap closes keepalive"
    );
    fixture.idle().await;
    assert_eq!(
        call(&fixture, "/").await.0,
        401,
        "public adapter rejects identity switching"
    );
    let mut expiring = fixture.connect().await;
    expiring
        .write_all(public_request("/spin").as_bytes())
        .await
        .unwrap();
    wait(|| fixture.node.backend.resource_snapshot().active_invocations == 1).await;
    assert!(
        tokio::time::timeout(Duration::from_secs(3), expiring.read_u8())
            .await
            .unwrap()
            .is_err()
    );
    fixture.idle().await;
    let mut active = fixture.connect().await;
    active
        .write_all(public_request("/").as_bytes())
        .await
        .unwrap();
    assert_eq!(
        response(&mut active).await.0,
        200,
        "deadline leaves reusable capacity"
    );
    active
        .write_all(public_request("/spin").as_bytes())
        .await
        .unwrap();
    wait(|| fixture.node.backend.resource_snapshot().active_invocations == 1).await;
    let mut incomplete = fixture.connect().await;
    incomplete.write_all(b"G").await.unwrap();
    wait(|| fixture.node.http_snapshot().unwrap().connections == 2).await;
    // Awaited forced shutdown must join both the active guest/cleanup owner and
    // a pre-authentication connection; reporting a timeout alone is insufficient.
    tokio::time::timeout(Duration::from_secs(3), fixture.shutdown())
        .await
        .unwrap();
    assert!(active.read_u8().await.is_err());
    assert!(incomplete.read_u8().await.is_err());
}
