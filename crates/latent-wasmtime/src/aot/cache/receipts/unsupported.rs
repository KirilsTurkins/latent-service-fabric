use super::{
    failure, AotReceiptCacheLimits, AotReceiptCacheSnapshot, ReceiptBytes, ReceiptReclamation,
    Result,
};
use latent_core::{ArtifactBlobDigest, PlatformError, PlatformErrorCode};
use std::{path::Path, sync::Arc};

pub(crate) struct ReceiptCache;

fn unsupported() -> PlatformError {
    failure(
        PlatformErrorCode::IncompatibleContract,
        "native-receipt-cache-platform-unsupported",
    )
}

impl ReceiptCache {
    pub(crate) fn open(_: &Path, _: AotReceiptCacheLimits) -> Result<Arc<Self>> {
        Err(unsupported())
    }
    pub(crate) fn limits(&self) -> AotReceiptCacheLimits {
        AotReceiptCacheLimits::default()
    }
    pub(crate) fn snapshot(&self) -> AotReceiptCacheSnapshot {
        AotReceiptCacheSnapshot::new(self.limits())
    }
    pub(crate) fn lookup(&self, _: &ArtifactBlobDigest) -> Result<Option<ReceiptBytes>> {
        Err(unsupported())
    }
    pub(crate) fn publish(&self, _: &ArtifactBlobDigest, _: &[u8]) -> Result<()> {
        Err(unsupported())
    }
    pub(crate) fn invalidate(&self, _: &ArtifactBlobDigest) -> Result<bool> {
        Err(unsupported())
    }
    pub(crate) fn reclaim(&self, _: usize) -> Result<ReceiptReclamation> {
        Err(unsupported())
    }
}
