use super::{AotReceiptCacheLimits, AotReceiptCacheSnapshot};
use crate::aot::{
    AotProcessLimits, AotResourceSnapshot, NativeImageLimits, NativeImageSnapshot,
    TrustedAotCompilerAuthority,
};
use latent_artifacts::{RawArtifactCacheLimits, RawArtifactCacheSnapshot};
use latent_core::PlatformError;
use std::path::PathBuf;

#[derive(Debug, Clone)]
pub struct NativeAotCacheConfig {
    pub blob_root: PathBuf,
    pub receipt_root: PathBuf,
    pub raw: RawArtifactCacheLimits,
    pub receipts: AotReceiptCacheLimits,
}

impl Default for NativeAotCacheConfig {
    fn default() -> Self {
        Self {
            blob_root: PathBuf::new(),
            receipt_root: PathBuf::new(),
            raw: RawArtifactCacheLimits {
                maximum_object_bytes: 128 * 1024 * 1024,
                maximum_staging_bytes: 256 * 1024 * 1024,
                maximum_read_bytes: 256 * 1024 * 1024,
                ..RawArtifactCacheLimits::default()
            },
            receipts: AotReceiptCacheLimits::default(),
        }
    }
}

/// Explicit operator approval and bounded storage. The key is never cloned.
pub struct NativeAotSettings {
    pub executable: PathBuf,
    pub approved_digest: [u8; 32],
    pub authority: TrustedAotCompilerAuthority,
    pub process: AotProcessLimits,
    pub cache: NativeAotCacheConfig,
    pub images: NativeImageLimits,
}

impl NativeAotSettings {
    pub fn validate(&self) -> Result<(), PlatformError> {
        self.process.validate()?;
        self.cache.raw.validate()?;
        self.cache.receipts.validate()?;
        self.images.validate()?;
        let native = self.process.compiler.maximum_output_bytes as u64;
        let mapping =
            crate::aot::image_budget::mapping_bytes(self.process.compiler.maximum_output_bytes)?;
        if native > 256 * 1024 * 1024
            || native > self.cache.raw.maximum_object_bytes
            || native > self.cache.raw.maximum_staging_bytes
            || native > self.cache.raw.maximum_read_bytes
            || native > self.cache.raw.maximum_disk_bytes
            || mapping > self.images.maximum_image_bytes
        {
            return Err(crate::aot::invalid());
        }
        Ok(())
    }
}

#[cfg(all(test, target_os = "linux", target_arch = "x86_64"))]
mod tests;

/// Independent charged domains, not process RSS. Subset fields are documented
/// by the corresponding owner; do not add pinned/loading bytes twice.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct NativeAotSnapshot {
    pub producer: AotResourceSnapshot,
    pub raw: RawArtifactCacheSnapshot,
    pub receipts: AotReceiptCacheSnapshot,
    pub images: NativeImageSnapshot,
    pub cache_hits: u64,
    pub cache_misses: u64,
    pub cache_rejections: u64,
    pub isolated_compilations: u64,
    pub persistence_failures: u64,
}
