use super::*;
use latent_artifacts::{package::artifact_blob_digest, RawArtifactKey};

#[tokio::test]
async fn corrupt_blob_refetches_after_reclamation_and_valid_blobs_survive_reopen() {
    let fixture = Fixture::load(false);
    let config = fixture.config_path();
    let bytes = fixture.blobs[&config].clone();
    let server = Server::start_methods(move |_, path| fixture.reply(path)).await;
    let root = tempfile::tempdir().unwrap();
    let first_cache = cache(root.path());
    let registry = HttpOciRegistry::new_with_cache(
        server.config(RegistryLimits::default()),
        first_cache.clone(),
    )
    .unwrap();
    let reference = server.reference("latest");
    drop(registry.pull_package(&reference).await.unwrap());
    // Controlled fixture mutation of one documented, cache-owned raw file.
    let digest = config
        .rsplit('/')
        .next()
        .unwrap()
        .strip_prefix("sha256:")
        .unwrap();
    let data = root
        .path()
        .join("objects")
        .join(format!("b-{digest}"))
        .join("data");
    std::fs::write(&data, vec![b'x'; bytes.len()]).unwrap();
    drop(registry.pull_package(&reference).await.unwrap());
    assert_eq!(std::fs::read(&data).unwrap(), bytes);
    assert_eq!(
        server
            .methods()
            .iter()
            .filter(|(method, path)| method == "GET" && *path == config)
            .count(),
        2
    );
    assert_eq!(first_cache.snapshot().unwrap().corruptions, 1);
    registry
        .shutdown(tokio::time::Instant::now() + std::time::Duration::from_secs(1))
        .await
        .unwrap();
    drop(registry);
    drop(first_cache);
    let reopened = cache(root.path());
    let registry =
        HttpOciRegistry::new_with_cache(server.config(RegistryLimits::default()), reopened)
            .unwrap();
    let before = server.methods().len();
    drop(registry.pull_package(&reference).await.unwrap());
    assert!(server.methods()[before..]
        .iter()
        .all(|(method, path)| method == "HEAD" || path.contains("/manifests/")));
}

#[tokio::test]
async fn one_bounded_pressure_pass_can_replace_unpinned_entries() {
    let fixture = Fixture::load(false);
    let blobs = fixture.blobs.len();
    let server = Server::start(move |path| fixture.reply(path)).await;
    let root = tempfile::tempdir().unwrap();
    let cache = RawArtifactCache::open(
        root.path(),
        RawArtifactCacheLimits {
            maximum_entries: 1,
            ..RawArtifactCacheLimits::default()
        },
    )
    .unwrap();
    let registry =
        HttpOciRegistry::new_with_cache(server.config(RegistryLimits::default()), cache.clone())
            .unwrap();
    let package = registry
        .pull_package(&server.reference("latest"))
        .await
        .unwrap();
    let used = cache.snapshot().unwrap();
    assert_eq!(used.entries, 1);
    assert_eq!(used.evictions, u64::try_from(blobs - 1).unwrap());
    // Returned package owns its independent exact bytes after earlier blobs were evicted.
    assert!(package.request().capsule_layout().is_err());
    assert_eq!(registry.usage().retained_packages, 1);
}

#[tokio::test]
async fn impossible_object_limit_and_all_pinned_capacity_do_not_evict_or_download() {
    for impossible_object in [false, true] {
        let fixture = Fixture::load(false);
        let server = Server::start(move |path| fixture.reply(path)).await;
        let root = tempfile::tempdir().unwrap();
        let limits = RawArtifactCacheLimits {
            maximum_entries: 1,
            maximum_object_bytes: if impossible_object { 4 } else { 64 * 1024 },
            ..RawArtifactCacheLimits::default()
        };
        let cache = RawArtifactCache::open(root.path(), limits).unwrap();
        let pin = cache
            .reserve_write(RawArtifactKey::Blob(artifact_blob_digest(b"held")), 4)
            .unwrap()
            .publish(b"held")
            .unwrap();
        let retained_pin = if impossible_object {
            drop(pin);
            None
        } else {
            Some(pin)
        };
        let registry = HttpOciRegistry::new_with_cache(
            server.config(RegistryLimits::default()),
            cache.clone(),
        )
        .unwrap();
        assert_eq!(
            registry
                .pull_package(&server.reference("latest"))
                .await
                .unwrap_err()
                .code,
            PlatformErrorCode::ResourceExhausted
        );
        assert_eq!(server.requests(), ["/v2/tenant/site/manifests/latest"]);
        let state = cache.snapshot().unwrap();
        assert_eq!(
            (state.entries, state.resident_disk_bytes, state.evictions),
            (1, 4, 0)
        );
        drop(retained_pin);
    }
}

#[tokio::test]
async fn low_level_blob_pull_remains_authenticated_network_io() {
    use latent_oci::{OciDescriptor, OciRegistry};
    let fixture = Fixture::load(false);
    let path = fixture.config_path();
    let bytes = fixture.blobs[&path].clone();
    let server = Server::start(move |path| fixture.reply(path)).await;
    let root = tempfile::tempdir().unwrap();
    let cache = cache(root.path());
    let registry =
        HttpOciRegistry::new_with_cache(server.config(RegistryLimits::default()), cache).unwrap();
    let reference = server.reference("latest");
    drop(registry.pull_package(&reference).await.unwrap());
    let descriptor = OciDescriptor {
        media_type: "application/octet-stream".to_owned(),
        artifact_type: None,
        digest: path.rsplit('/').next().unwrap().to_owned(),
        size_bytes: bytes.len() as u64,
        annotations: latent_core::Metadata::default(),
    };
    let before = server.methods().len();
    assert_eq!(
        registry
            .pull_blob(&reference, &descriptor, descriptor.size_bytes)
            .await
            .unwrap(),
        bytes
    );
    assert_eq!(&server.methods()[before..], [("GET".to_owned(), path)]);
}
