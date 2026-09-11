use std::path::PathBuf;
use std::sync::atomic::{AtomicU64, AtomicUsize, Ordering};

use latent_artifacts::{
    ArtifactDescriptor, ArtifactPage, ArtifactPreparationSource, ArtifactQuery, ArtifactRepository,
    CapsuleArtifact, DirectoryArtifactRepository, DirectoryArtifactRepositoryConfig,
};
use latent_core::{BoxFuture, PlatformError, ReleaseDigest};
use latent_wasmtime::WasmtimeBackend;

pub(super) struct Directory(PathBuf);

impl Directory {
    pub(super) fn new() -> Self {
        static NEXT: AtomicU64 = AtomicU64::new(0);
        let suffix = NEXT.fetch_add(1, Ordering::Relaxed);
        let path = std::env::temp_dir().join(format!(
            "latent-warm-preparation-{}-{suffix}-{}",
            std::process::id(),
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap()
                .as_nanos()
        ));
        std::fs::create_dir(&path).unwrap();
        Self(path)
    }

    pub(super) fn open(&self) -> DirectoryArtifactRepository {
        DirectoryArtifactRepository::open(&self.0, DirectoryArtifactRepositoryConfig::default())
            .unwrap()
    }

    pub(super) fn corrupt_component(&self, release: &ReleaseDigest) {
        let component = self
            .0
            .join("releases")
            .join(release.0.strip_prefix("sha256:").unwrap())
            .join("component.wasm");
        let mut bytes = std::fs::read(&component).unwrap();
        bytes[0] ^= 1;
        std::fs::write(component, bytes).unwrap();
    }
}

impl Drop for Directory {
    fn drop(&mut self) {
        let _ = std::fs::remove_dir_all(&self.0);
    }
}

/// A selected sealed source must own reads even when this adapter offers others.
pub(super) struct Repository<'a> {
    pub(super) source: Option<&'a DirectoryArtifactRepository>,
    pub(super) fallback: Option<CapsuleArtifact>,
    pub(super) fetches: AtomicUsize,
}

impl ArtifactRepository for Repository<'_> {
    fn preparation_source(&self) -> Option<ArtifactPreparationSource<'_>> {
        self.source.and_then(ArtifactRepository::preparation_source)
    }

    fn resolve<'a>(
        &'a self,
        _query: &'a ArtifactQuery,
    ) -> BoxFuture<'a, Result<Option<ArtifactDescriptor>, PlatformError>> {
        panic!("preparation must not resolve an already pinned release")
    }

    fn fetch<'a>(
        &'a self,
        _digest: &'a ReleaseDigest,
    ) -> BoxFuture<'a, Result<CapsuleArtifact, PlatformError>> {
        self.fetches.fetch_add(1, Ordering::Relaxed);
        Box::pin(async move {
            match &self.fallback {
                Some(artifact) => Ok(artifact.clone()),
                None => std::future::pending().await,
            }
        })
    }

    fn publish<'a>(
        &'a self,
        _artifact: CapsuleArtifact,
    ) -> BoxFuture<'a, Result<ArtifactDescriptor, PlatformError>> {
        panic!("preparation must not publish")
    }

    fn list<'a>(
        &'a self,
        _after: Option<&'a ReleaseDigest>,
        _limit: usize,
    ) -> BoxFuture<'a, Result<ArtifactPage, PlatformError>> {
        panic!("preparation must not enumerate artifacts")
    }
}

pub(super) fn no_reservations(backend: &WasmtimeBackend) {
    assert_eq!(backend.active_instance_reservations(), 0);
    assert_eq!(backend.resource_snapshot().live_stores, 0);
    let cache = backend.cache_snapshot();
    assert_eq!(cache.preparing, 0);
    assert_eq!(cache.preparing_source_bytes, 0);
    assert_eq!(cache.preparing_metadata_bytes, 0);
}
