//! Small ownership, persistence and capacity checks; no cache load campaign.

use super::*;
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::Arc;

#[cfg(unix)]
mod catalog;
#[cfg(unix)]
mod cutpoints;
#[cfg(unix)]
mod hardening;
mod limits;
#[cfg(unix)]
mod ownership;
#[cfg(unix)]
mod persistence;
#[cfg(unix)]
mod reclamation;

static NEXT_ROOT: AtomicU64 = AtomicU64::new(0);

struct Root(PathBuf);
impl Root {
    fn new() -> Self {
        let path = std::env::temp_dir().join(format!(
            "lsf-raw-cache-test-{}-{:020}",
            std::process::id(),
            NEXT_ROOT.fetch_add(1, Ordering::Relaxed)
        ));
        std::fs::create_dir(&path).expect("new owned test directory");
        Self(path)
    }
    fn path(&self) -> PathBuf {
        self.0.join("cache")
    }
    fn base(&self) -> &Path {
        &self.0
    }
}
impl Drop for Root {
    fn drop(&mut self) {
        assert!(self.0.starts_with(std::env::temp_dir()));
        std::fs::remove_dir_all(&self.0).expect("remove only owned test directory");
    }
}

fn blob(bytes: &[u8]) -> RawArtifactKey {
    RawArtifactKey::Blob(crate::content_digest(bytes).0.parse().unwrap())
}

fn manifest(bytes: &[u8]) -> RawArtifactKey {
    RawArtifactKey::Manifest(crate::content_digest(bytes).0.parse().unwrap())
}

fn put(cache: &Arc<RawArtifactCache>, bytes: &[u8]) -> RawArtifactPin {
    cache
        .reserve_write(blob(bytes), bytes.len() as u64)
        .unwrap()
        .publish(bytes)
        .unwrap()
}

fn failure<T>(result: std::result::Result<T, PlatformError>) -> PlatformError {
    result.err().expect("operation must reject")
}
