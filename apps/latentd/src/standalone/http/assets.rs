//! Immutable browser assets are a sibling of activation dispatch, not a renderer.
//! One node-owned cache and nonblocking work gate serve all admitted publications.
mod cache;
mod request;
mod source;
mod wire;

use cache::{Buffer, Cache, MAX_BYTES};
use latent_artifacts::{web::WebSelection, DirectoryArtifactRepository};
use latent_core::{PlatformError, PlatformErrorCode, TenantId};
use request::Request;
use serde::Serialize;
use std::sync::{
    atomic::{AtomicBool, AtomicU64, Ordering},
    Arc,
};
use tokio::sync::{OwnedSemaphorePermit, Semaphore};

const MAX_READS: usize = 4;
pub(super) use wire::exchange;

#[derive(Clone, Copy, Debug, Default, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct AssetSnapshot {
    pub maximum_reads: usize,
    /// Includes blocking reads and outputs awaiting write/cleanup, not only I/O.
    pub active_reads: usize,
    pub maximum_buffer_bytes: usize,
    /// Includes cached, in-flight and evicted-but-pinned bytes plus entry charges.
    pub retained_buffer_bytes: usize,
    pub cache_entries: usize,
    pub cache_hits: u64,
    pub cache_misses: u64,
    pub corruptions: u64,
    pub capacity_rejections: u64,
}
impl AssetSnapshot {
    pub(super) fn clean(self) -> bool {
        self.active_reads == 0 && self.retained_buffer_bytes == 0 && self.cache_entries == 0
    }
}

pub(super) struct Store {
    repository: Arc<DirectoryArtifactRepository>,
    source: source::Source,
    cache: Cache,
    work: Arc<Semaphore>,
    stopped: AtomicBool,
    rejected: AtomicU64,
}
impl Store {
    pub(super) fn new(repository: Arc<DirectoryArtifactRepository>) -> Result<Arc<Self>, u16> {
        Ok(Arc::new(Self {
            source: source::Source::new(&repository)?,
            repository,
            cache: Cache::new(MAX_BYTES),
            work: Arc::new(Semaphore::new(MAX_READS)),
            stopped: AtomicBool::new(false),
            rejected: AtomicU64::new(0),
        }))
    }
    pub(super) fn snapshot(&self) -> AssetSnapshot {
        AssetSnapshot {
            maximum_reads: MAX_READS,
            active_reads: MAX_READS - self.work.available_permits(),
            maximum_buffer_bytes: MAX_BYTES,
            retained_buffer_bytes: self.cache.retained_bytes(),
            cache_entries: self.cache.entries_count.load(Ordering::Acquire),
            cache_hits: self.cache.hits.load(Ordering::Relaxed),
            cache_misses: self.cache.misses.load(Ordering::Relaxed),
            corruptions: self.cache.corruptions.load(Ordering::Relaxed),
            capacity_rejections: self.rejected.load(Ordering::Relaxed),
        }
    }
    pub(super) fn stop(&self) {
        self.stopped.store(true, Ordering::Release);
    }
    pub(super) async fn shutdown(&self, deadline: tokio::time::Instant) -> bool {
        self.stop();
        // Running spawn_blocking calls cannot be canceled. Wait for actual work
        // AND response owners before clearing cache, never release their slots early.
        let Ok(Ok(_all)) = tokio::time::timeout_at(
            deadline,
            Arc::clone(&self.work).acquire_many_owned(MAX_READS as u32),
        )
        .await
        else {
            return false;
        };
        self.cache.clear();
        self.cache.retained_bytes() == 0
    }
    fn begin(
        self: &Arc<Self>,
        request: Request,
    ) -> Result<tokio::task::JoinHandle<Result<Prepared, u16>>, u16> {
        if self.stopped.load(Ordering::Acquire) {
            return Err(503);
        }
        let permit = Arc::clone(&self.work).try_acquire_owned().map_err(|_| {
            self.rejected.fetch_add(1, Ordering::Relaxed);
            503u16
        })?;
        let store = Arc::clone(self);
        // There is no wait queue or per-publication worker. The permit is moved
        // into the closure before spawn and then into its response on success.
        Ok(tokio::task::spawn_blocking(move || {
            let result = store.prepare(request, permit);
            if matches!(result, Err(503)) {
                store.rejected.fetch_add(1, Ordering::Relaxed);
            }
            result
        }))
    }
    fn prepare(&self, request: Request, permit: OwnedSemaphorePermit) -> Result<Prepared, u16> {
        if self.stopped.load(Ordering::Acquire) {
            return Err(503);
        }
        let selection = self
            .repository
            .select_web_publication(&request.reference)
            .map_err(status)?;
        // Never use a supplied digest as a grant or look up an arbitrary layer.
        let asset = selection.layout().asset(&request.path).ok_or(404u16)?;
        let buffer = self
            .cache
            .read(asset, |digest, bytes| self.source.read(digest, bytes))?;
        let etag = identity(&asset.digest, asset.size, &asset.media_type);
        let code = request.status(&etag)?;
        let media = asset.media_type.clone();
        Ok(Prepared {
            buffer,
            selection,
            request,
            etag,
            media,
            code,
            _permit: permit,
        })
    }
}

struct Prepared {
    buffer: Arc<Buffer>,
    selection: WebSelection,
    request: Request,
    etag: String,
    media: String,
    code: u16,
    // Last field: release all output and selection ownership before this slot.
    _permit: OwnedSemaphorePermit,
}
impl Prepared {
    fn accept(&self, tenant: &TenantId) -> Result<(), u16> {
        // Required even for cache hits, HEAD and 304. Generation/policy changes
        // invalidate this acceptance instead of silently switching publications.
        self.selection
            .with_current(tenant, &mut |current| current.check())
            .map_err(status)
    }
}
fn identity(digest: &str, size: u64, media: &str) -> String {
    use sha2::{Digest, Sha256};
    let mut hash = Sha256::new();
    hash.update(b"lsf-http-asset-identity-v1\0");
    hash.update(digest.as_bytes());
    hash.update(size.to_le_bytes());
    hash.update(media.as_bytes());
    format!("\"identity-sha256-{:x}\"", hash.finalize())
}
fn status(error: PlatformError) -> u16 {
    match error.code {
        PlatformErrorCode::Unauthenticated => 401,
        PlatformErrorCode::PermissionDenied => 403,
        PlatformErrorCode::NotFound => 404,
        PlatformErrorCode::InvalidArgument => 400,
        PlatformErrorCode::CorruptArtifact | PlatformErrorCode::IncompatibleContract => 502,
        _ => 503,
    }
}

impl super::HttpOwner {
    pub(crate) fn install_assets(
        &self,
        repository: Arc<DirectoryArtifactRepository>,
    ) -> Result<(), PlatformError> {
        let handle = self.handle();
        if *handle.0.signal.borrow() != super::state::Signal::Starting {
            return Err(super::failure());
        }
        let store = Store::new(repository).map_err(|_| super::failure())?;
        handle.0.assets.set(store).map_err(|_| super::failure())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn representation_identity_includes_media_size_and_encoding_domain() {
        assert_ne!(
            identity("sha256:abc", 1, "text/plain"),
            identity("sha256:abc", 1, "text/html")
        );
        assert_ne!(
            identity("sha256:abc", 1, "text/plain"),
            identity("sha256:abc", 2, "text/plain")
        );
        assert!(identity("sha256:abc", 1, "text/plain").starts_with("\"identity-sha256-"));
    }
}
