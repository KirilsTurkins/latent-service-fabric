//! Raw cache hits preserve remote authorization, graph bounds and exact identity.
#![cfg(unix)]
#[path = "http_cache/storage.rs"]
mod storage;
#[path = "http_pull/support.rs"]
#[allow(
    dead_code,
    reason = "Shared fixture APIs differ between pull and cache integration targets."
)]
mod support;

use latent_artifacts::{RawArtifactCache, RawArtifactCacheLimits};
use latent_core::PlatformErrorCode;
use latent_oci::{HttpOciRegistry, RegistryLimits};
use std::sync::{
    atomic::{AtomicU16, Ordering},
    Arc,
};
use support::{Fixture, Server};

fn cache(root: &std::path::Path) -> Arc<RawArtifactCache> {
    RawArtifactCache::open(root, RawArtifactCacheLimits::default()).unwrap()
}

#[tokio::test]
async fn warm_package_keeps_online_manifest_and_authorizes_each_cached_blob() {
    let fixture = Fixture::load(false);
    let total = fixture.total();
    let blobs = fixture.blobs.len();
    let server = Server::start_methods(move |_, path| fixture.reply(path)).await;
    let root = tempfile::tempdir().unwrap();
    let registry = HttpOciRegistry::new_with_cache(
        server.config(RegistryLimits::default()),
        cache(root.path()),
    )
    .unwrap();
    let reference = server.reference("latest");
    let first = registry.pull_package(&reference).await.unwrap();
    let expected = first.request().manifest().as_bytes().to_vec();
    drop(first);
    let received = registry.pull_package(&reference).await.unwrap();
    assert_eq!(received.request().manifest().as_bytes(), expected);
    assert_eq!(registry.usage().retained_bytes, total);
    assert!(registry.cache_usage().unwrap().is_some());
    let methods = server.methods();
    assert_eq!(
        methods
            .iter()
            .filter(|(m, p)| m == "GET" && p.contains("/manifests/"))
            .count(),
        2
    );
    assert_eq!(
        methods
            .iter()
            .filter(|(m, p)| m == "GET" && p.contains("/blobs/"))
            .count(),
        blobs
    );
    assert_eq!(
        methods
            .iter()
            .filter(|(m, p)| m == "HEAD" && p.contains("/blobs/"))
            .count(),
        blobs
    );
    drop(received);
    assert_eq!(registry.usage().retained_bytes, 0);
}

#[tokio::test]
async fn cached_bytes_do_not_override_current_blob_or_manifest_authorization() {
    let fixture = Fixture::load(false);
    let denied = Arc::new(AtomicU16::new(0));
    let denied_route = denied.clone();
    let server = Server::start_methods(move |method, path| {
        let mut reply = fixture.reply(path);
        match denied_route.load(Ordering::Acquire) {
            403 if method == "HEAD" => reply.status = 403,
            401 if path.contains("/manifests/") => reply.status = 401,
            _ => (),
        }
        reply
    })
    .await;
    let root = tempfile::tempdir().unwrap();
    let registry = HttpOciRegistry::new_with_cache(
        server.config(RegistryLimits::default()),
        cache(root.path()),
    )
    .unwrap();
    let reference = server.reference("latest");
    drop(registry.pull_package(&reference).await.unwrap());
    denied.store(403, Ordering::Release);
    assert_eq!(
        registry.pull_package(&reference).await.unwrap_err().code,
        PlatformErrorCode::PermissionDenied
    );
    denied.store(401, Ordering::Release);
    assert_eq!(
        registry.pull_package(&reference).await.unwrap_err().code,
        PlatformErrorCode::Unauthenticated
    );
    assert_eq!(registry.usage().retained_bytes, 0);
    assert_eq!(registry.usage().in_flight, 0);
}

#[tokio::test]
async fn unsupported_head_falls_back_to_verified_get_without_offline_success() {
    let fixture = Fixture::load(false);
    let blob_count = fixture.blobs.len();
    let get_status = Arc::new(AtomicU16::new(200));
    let status = get_status.clone();
    let server = Server::start_methods(move |method, path| {
        let mut reply = fixture.reply(path);
        if method == "HEAD" {
            reply.status = 405;
        } else if path.contains("/blobs/") {
            reply.status = status.load(Ordering::Acquire);
        }
        reply
    })
    .await;
    let root = tempfile::tempdir().unwrap();
    let registry = HttpOciRegistry::new_with_cache(
        server.config(RegistryLimits::default()),
        cache(root.path()),
    )
    .unwrap();
    let reference = server.reference("latest");
    drop(registry.pull_package(&reference).await.unwrap());
    drop(registry.pull_package(&reference).await.unwrap());
    assert_eq!(
        server
            .methods()
            .iter()
            .filter(|(m, p)| m == "GET" && p.contains("/blobs/"))
            .count(),
        blob_count * 2
    );
    get_status.store(403, Ordering::Release);
    assert_eq!(
        registry.pull_package(&reference).await.unwrap_err().code,
        PlatformErrorCode::PermissionDenied
    );
}

#[tokio::test]
async fn warm_cache_does_not_bypass_complete_graph_memory_reservation() {
    let fixture = Fixture::load(false);
    let total = fixture.total();
    let server = Server::start(move |path| fixture.reply(path)).await;
    let root = tempfile::tempdir().unwrap();
    let cache = cache(root.path());
    let registry =
        HttpOciRegistry::new_with_cache(server.config(RegistryLimits::default()), cache.clone())
            .unwrap();
    drop(
        registry
            .pull_package(&server.reference("latest"))
            .await
            .unwrap(),
    );
    let before = server.requests().len();
    let limited = HttpOciRegistry::new_with_cache(
        server.config(RegistryLimits {
            package: latent_artifacts::package::PackageLimits {
                max_document_bytes: 1024,
                ..latent_artifacts::package::PackageLimits::default()
            },
            max_retained_bytes: u32::try_from(total - 1).unwrap(),
            ..RegistryLimits::default()
        }),
        cache,
    )
    .unwrap();
    assert_eq!(
        limited
            .pull_package(&server.reference("latest"))
            .await
            .unwrap_err()
            .code,
        PlatformErrorCode::ResourceExhausted
    );
    assert_eq!(
        &server.requests()[before..],
        ["/v2/tenant/site/manifests/latest"]
    );
    assert_eq!(limited.usage().retained_bytes, 0);
}

#[tokio::test]
async fn repeated_tag_pull_resolves_the_new_manifest_once() {
    let original = Fixture::load(false);
    let moved = Fixture::load(true);
    let mut manifests = 0;
    let server = Server::start_methods(move |_, path| {
        if path.contains("/manifests/") {
            manifests += 1;
        }
        if manifests == 1 {
            original.reply(path)
        } else {
            moved.reply(path)
        }
    })
    .await;
    let root = tempfile::tempdir().unwrap();
    let registry = HttpOciRegistry::new_with_cache(
        server.config(RegistryLimits::default()),
        cache(root.path()),
    )
    .unwrap();
    let reference = server.reference("latest");
    let first = registry.pull_package(&reference).await.unwrap();
    assert!(first.request().referrer().is_none());
    let digest = first.request().manifest().digest().clone();
    drop(first);
    let second = registry.pull_package(&reference).await.unwrap();
    assert!(second.request().referrer().is_some());
    assert_ne!(second.request().manifest().digest(), &digest);
    assert_eq!(
        server
            .methods()
            .iter()
            .filter(|(_, p)| p.contains("/manifests/"))
            .count(),
        2
    );
}

#[tokio::test]
async fn mismatched_head_length_or_digest_never_uses_cached_bytes() {
    let fixture = Fixture::load(false);
    let mode = Arc::new(AtomicU16::new(0));
    let setting = mode.clone();
    let server = Server::start_methods(move |method, path| {
        let mut reply = fixture.reply(path);
        if method == "HEAD" {
            if setting.load(Ordering::Acquire) == 1 {
                reply.body.push(0);
            }
            if setting.load(Ordering::Acquire) == 2 {
                reply = reply.header(
                    "Docker-Content-Digest",
                    &format!("sha256:{}", "0".repeat(64)),
                );
            }
        }
        reply
    })
    .await;
    let root = tempfile::tempdir().unwrap();
    let registry = HttpOciRegistry::new_with_cache(
        server.config(RegistryLimits::default()),
        cache(root.path()),
    )
    .unwrap();
    let reference = server.reference("latest");
    drop(registry.pull_package(&reference).await.unwrap());
    for invalid in [1, 2] {
        mode.store(invalid, Ordering::Release);
        assert_eq!(
            registry.pull_package(&reference).await.unwrap_err().code,
            PlatformErrorCode::CorruptArtifact
        );
        assert_eq!(registry.usage().retained_bytes, 0);
    }
}
