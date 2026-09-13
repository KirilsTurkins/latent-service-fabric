use crate::tests::fixtures;
mod server;

use crate::{http::HttpOciRegistry, OciPushRequest, OciRegistry};
use latent_artifacts::package::{PackageKind, PackageLimits};
use latent_core::PlatformErrorCode;
use server::Server;
use std::time::Duration;
use tokio::time::Instant;

const LOCATION: &str = "/v2/tenant/site/blobs/uploads/session?_state=a%2fb%2B%3D&empty=";

async fn shutdown(registry: &HttpOciRegistry) {
    registry
        .shutdown(Instant::now() + Duration::from_secs(3))
        .await
        .unwrap();
    assert_eq!(registry.usage().in_flight, 0);
    assert_eq!(registry.usage().retained_bytes, 0);
}

fn request(server: &Server) -> OciPushRequest {
    let (manifest, config, layers) = fixtures::fixture(PackageKind::BrowserAssets);
    OciPushRequest::new(
        server.reference(),
        manifest,
        config,
        layers,
        PackageLimits::default(),
    )
    .unwrap()
}

#[tokio::test]
async fn cancellation_before_location_retains_operation_until_delete_finishes() {
    let mut server = Server::new().await;
    let registry = HttpOciRegistry::new(server.config(1)).unwrap();
    let operation = registry.transport.begin(17).unwrap();
    let worker = registry.uploads.clone();
    let start = tokio::spawn(async move { worker.start(operation).await });
    let post = server.next().await;
    assert_eq!(post.method, "POST");
    assert_eq!(post.headers["content-length"], "0");
    start.abort();
    assert!(matches!(start.await, Err(error) if error.is_cancelled()));
    assert_eq!(registry.usage().retained_bytes, 17);
    post.respond(202, &[("Location", LOCATION)]);
    let delete = server.next().await;
    assert_eq!(delete.method, "DELETE");
    assert_eq!(delete.target, LOCATION);
    assert!(registry.transport.begin(1).is_err());
    assert_eq!(registry.usage().retained_bytes, 17);
    delete.respond(204, &[]);
    shutdown(&registry).await;
}

#[tokio::test]
async fn every_session_reserves_cleanup_capacity_before_post() {
    let mut server = Server::new().await;
    let registry = HttpOciRegistry::new(server.config(2)).unwrap();
    let mut sessions = Vec::new();
    for index in 0..2 {
        let operation = registry.transport.begin(13).unwrap();
        let worker = registry.uploads.clone();
        let start = tokio::spawn(async move { worker.start(operation).await });
        let post = server.next().await;
        assert_eq!(post.method, "POST");
        let location = format!("/v2/tenant/site/blobs/uploads/session{index}");
        post.respond(202, &[("Location", &location)]);
        sessions.push(start.await.unwrap().unwrap());
    }
    assert!(registry.transport.begin(1).is_err());
    drop(sessions);
    for _ in 0..2 {
        let delete = server.next().await;
        assert_eq!(delete.method, "DELETE");
        assert!(registry.usage().in_flight > 0);
        delete.respond(204, &[]);
    }
    shutdown(&registry).await;
}

#[tokio::test]
async fn config_and_layers_precede_exact_manifest_with_head_deduplication() {
    let mut server = Server::new().await;
    let registry = HttpOciRegistry::new(server.config(1)).unwrap();
    let request = request(&server);
    let manifest = request.manifest().as_bytes().to_vec();
    let digest = request.manifest().digest().clone();
    let config = request.config_bytes().to_vec();
    let config_digest = request.layout().unwrap().manifest().config.digest.clone();
    let layer = request.layout().unwrap().manifest().layers[0].clone();
    let client = registry.clone();
    let push = tokio::spawn(async move { client.push(request).await });
    let head = server.next().await;
    assert_eq!(head.method, "HEAD");
    assert!(head.target.ends_with(config_digest.as_str()));
    head.respond(404, &[]);
    server.next().await.respond(202, &[("Location", LOCATION)]);
    let put = server.next().await;
    assert_eq!(put.method, "PUT");
    assert_eq!(
        put.target,
        format!("{LOCATION}&digest={}", config_digest.as_str())
    );
    assert_eq!(put.body, config);
    put.respond(201, &[("Docker-Content-Digest", config_digest.as_str())]);
    let head = server.next().await;
    assert_eq!(head.method, "HEAD");
    assert!(head.target.ends_with(layer.digest.as_str()));
    head.respond(
        200,
        &[
            ("Content-Length", &layer.size.to_string()),
            ("Docker-Content-Digest", layer.digest.as_str()),
        ],
    );
    let put = server.next().await;
    assert_eq!(put.method, "PUT");
    assert_eq!(put.target, "/v2/tenant/site/manifests/candidate");
    assert_eq!(put.body, manifest);
    put.respond(201, &[("Docker-Content-Digest", digest.as_str())]);
    assert_eq!(push.await.unwrap().unwrap(), digest);
    shutdown(&registry).await;
}

#[tokio::test]
async fn cancellation_during_put_cleans_session_and_keeps_full_byte_lease() {
    let mut server = Server::new().await;
    let registry = HttpOciRegistry::new(server.config(1)).unwrap();
    let request = request(&server);
    let client = registry.clone();
    let push = tokio::spawn(async move { client.push(request).await });
    server.next().await.respond(404, &[]);
    server.next().await.respond(202, &[("Location", LOCATION)]);
    let put = server.next().await;
    assert_eq!(put.method, "PUT");
    let retained = registry.usage().retained_bytes;
    assert!(retained > put.body.len());
    push.abort();
    assert!(push.await.unwrap_err().is_cancelled());
    drop(put); // Close the stalled response so the sequential test peer advances.
    let delete = server.next().await;
    assert_eq!(delete.method, "DELETE");
    assert_eq!(delete.target, LOCATION);
    assert_eq!(registry.usage().retained_bytes, retained);
    delete.respond(204, &[]);
    shutdown(&registry).await;
}

#[tokio::test]
async fn wrong_manifest_digest_is_not_reported_as_a_successful_push() {
    let mut server = Server::new().await;
    let registry = HttpOciRegistry::new(server.config(1)).unwrap();
    let request = request(&server);
    let sizes = [
        request.config_bytes().len(),
        request.layers().next().unwrap().1.len(),
    ];
    let client = registry.clone();
    let push = tokio::spawn(async move { client.push(request).await });
    for size in sizes {
        let head = server.next().await;
        assert_eq!(head.method, "HEAD");
        head.respond(200, &[("Content-Length", &size.to_string())]);
    }
    let manifest = server.next().await;
    assert_eq!(manifest.method, "PUT");
    manifest.respond(201, &[("Docker-Content-Digest", "sha256:wrong")]);
    assert_eq!(
        push.await.unwrap().unwrap_err().code,
        PlatformErrorCode::CorruptArtifact
    );
    shutdown(&registry).await;
}

#[tokio::test]
async fn cleanup_failure_is_visible_at_shutdown() {
    let mut server = Server::new().await;
    let registry = HttpOciRegistry::new(server.config(1)).unwrap();
    let operation = registry.transport.begin(9).unwrap();
    let worker = registry.uploads.clone();
    let start = tokio::spawn(async move { worker.start(operation).await });
    server.next().await.respond(202, &[("Location", LOCATION)]);
    drop(start.await.unwrap().unwrap());
    let delete = server.next().await;
    assert_eq!(delete.method, "DELETE");
    delete.respond(500, &[]);
    let error = registry
        .shutdown(Instant::now() + Duration::from_secs(3))
        .await
        .unwrap_err();
    assert_eq!(error.message, "oci-upload-cleanup-failed");
    assert_eq!(registry.usage().retained_bytes, 0);
}
