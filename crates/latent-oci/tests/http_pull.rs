#[path = "http_pull/referrers.rs"]
mod referrers;
#[path = "http_pull/support.rs"]
#[allow(
    dead_code,
    reason = "Shared fixture APIs differ between pull and cache integration targets."
)]
mod support;

use latent_artifacts::package::{decode_manifest, encode_manifest, package_digest, PackageLimits};
use latent_core::PlatformErrorCode;
use latent_oci::RegistryLimits;
use std::time::Duration;
use support::{Fixture, Server};

#[tokio::test]
async fn package_pins_tag_once_and_retains_exact_bytes_and_slot_until_drop() {
    let fixture = Fixture::load(false);
    let expected = package_digest(&fixture.manifest);
    let bytes = fixture.total();
    let server = Server::start(move |path| fixture.reply(path)).await;
    let registry = server.registry(RegistryLimits {
        max_retained_packages: 1,
        ..RegistryLimits::default()
    });
    let reference = server.reference("latest");
    let package = registry.pull_package(&reference).await.unwrap();
    assert_eq!(package.request().manifest().digest(), &expected);
    assert_eq!(package.request().reference().reference, expected.as_str());
    assert_eq!(registry.usage().retained_bytes, bytes);
    assert_eq!(registry.usage().retained_packages, 1);
    assert_eq!(registry.usage().in_flight, 0);
    assert_eq!(
        registry.pull_package(&reference).await.unwrap_err().code,
        PlatformErrorCode::ResourceExhausted
    );
    let requests = server.requests();
    assert_eq!(
        requests
            .iter()
            .filter(|path| path.contains("/manifests/"))
            .count(),
        1
    );
    assert!(requests
        .iter()
        .skip(1)
        .all(|path| path.starts_with("/v2/tenant/site/blobs/sha256:")));
    drop(package);
    assert_eq!(registry.usage().retained_bytes, 0);
    assert_eq!(registry.usage().retained_packages, 0);
    drop(registry.pull_package(&reference).await.unwrap());
}

#[tokio::test]
async fn evidence_uses_the_same_checked_retention_owner_without_capsule_authority() {
    let fixture = Fixture::load(true);
    let total = fixture.total();
    let server = Server::start(move |path| fixture.reply(path)).await;
    let registry = server.registry(RegistryLimits::default());
    let package = registry
        .pull_package(&server.reference("evidence"))
        .await
        .unwrap();
    assert!(package.request().referrer().is_some());
    assert!(package.request().capsule_layout().is_err());
    assert_eq!(registry.usage().retained_bytes, total);
    drop(package);
    assert_eq!(registry.usage().retained_bytes, 0);
}

#[tokio::test]
async fn aggregate_graph_reservation_fails_before_any_blob_request() {
    let fixture = Fixture::load(false);
    let maximum = u32::try_from(fixture.total() - 1).unwrap();
    let server = Server::start(move |path| fixture.reply(path)).await;
    let registry = server.registry(RegistryLimits {
        max_retained_bytes: maximum,
        package: PackageLimits {
            max_document_bytes: 1024,
            ..PackageLimits::default()
        },
        ..RegistryLimits::default()
    });
    assert_eq!(
        registry
            .pull_package(&server.reference("latest"))
            .await
            .unwrap_err()
            .code,
        PlatformErrorCode::ResourceExhausted
    );
    assert_eq!(server.requests(), ["/v2/tenant/site/manifests/latest"]);
    assert_eq!(registry.usage().retained_bytes, 0);
    assert_eq!(registry.usage().retained_packages, 0);
}

#[tokio::test]
async fn config_association_is_checked_before_layer_downloads() {
    let mut fixture = Fixture::load(false);
    let mut manifest = decode_manifest(&fixture.manifest, PackageLimits::default()).unwrap();
    manifest.layers[0].size += 1;
    fixture.manifest = encode_manifest(&manifest, PackageLimits::default()).unwrap();
    let config_path = fixture.config_path();
    let server = Server::start(move |path| fixture.reply(path)).await;
    let registry = server.registry(RegistryLimits::default());
    assert!(registry
        .pull_package(&server.reference("latest"))
        .await
        .is_err());
    assert_eq!(
        server.requests(),
        ["/v2/tenant/site/manifests/latest".to_owned(), config_path]
    );
    assert_eq!(registry.usage().retained_bytes, 0);
    assert_eq!(registry.usage().retained_packages, 0);
}

#[tokio::test]
async fn cancelled_download_reclaims_partial_package_and_operation_ownership() {
    let fixture = Fixture::load(false);
    let config_path = fixture.config_path();
    let server = Server::start(move |path| {
        let mut reply = fixture.reply(path);
        if path == config_path {
            reply.delay = Duration::from_secs(10);
        }
        reply
    })
    .await;
    let registry = server.registry(RegistryLimits::default());
    let worker = registry.clone();
    let reference = server.reference("latest");
    let task = tokio::spawn(async move { worker.pull_package(&reference).await });
    server.wait_requests(2).await;
    assert_eq!(registry.usage().retained_packages, 1);
    task.abort();
    assert!(task.await.unwrap_err().is_cancelled());
    assert_eq!(registry.usage().retained_packages, 0);
    assert_eq!(registry.usage().retained_bytes, 0);
    assert_eq!(registry.usage().in_flight, 0);
}
