use super::{config, credentials, fixtures, reference, shutdown};
use latent_artifacts::{package::package_digest, RawArtifactCache, RawArtifactCacheLimits};
use latent_oci::HttpOciRegistry;

pub(super) async fn roundtrip(origin: &str, fixtures: &[fixtures::Fixture]) {
    let fixture = fixtures
        .iter()
        .find(|fixture| fixture.kind == "browser-assets")
        .unwrap();
    let root = tempfile::tempdir().unwrap();
    let cache = RawArtifactCache::open(root.path(), RawArtifactCacheLimits::default()).unwrap();
    let registry =
        HttpOciRegistry::new_with_cache(config(origin, credentials()), cache.clone()).unwrap();
    let pinned = reference(origin, package_digest(&fixture.manifest).as_str());
    fixture.check(registry.pull_package(&pinned).await.unwrap().request());
    let cold = cache.snapshot().unwrap();
    fixture.check(registry.pull_package(&pinned).await.unwrap().request());
    let warm = cache.snapshot().unwrap();
    assert_eq!(warm.entries, cold.entries);
    assert_eq!(warm.resident_disk_bytes, cold.resident_disk_bytes);
    assert!(warm.hits > cold.hits);
    shutdown(&registry).await;
    drop(registry);
    drop(cache);
    let reopened = RawArtifactCache::open(root.path(), RawArtifactCacheLimits::default()).unwrap();
    let registry =
        HttpOciRegistry::new_with_cache(config(origin, credentials()), reopened).unwrap();
    fixture.check(registry.pull_package(&pinned).await.unwrap().request());
    shutdown(&registry).await;
}
