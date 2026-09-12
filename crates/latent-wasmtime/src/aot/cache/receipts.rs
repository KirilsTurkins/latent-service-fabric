//! Bounded untrusted receipt storage. A locator never authenticates native code.

mod model;
pub use model::{AotReceiptCacheLimits, AotReceiptCacheSnapshot};

#[cfg(all(target_os = "linux", target_arch = "x86_64"))]
mod io;
#[cfg(all(target_os = "linux", target_arch = "x86_64"))]
mod recovery;
#[cfg(all(target_os = "linux", target_arch = "x86_64"))]
mod store;
#[cfg(all(target_os = "linux", target_arch = "x86_64"))]
pub(crate) use store::ReceiptCache;
#[cfg(not(all(target_os = "linux", target_arch = "x86_64")))]
mod unsupported;
#[cfg(not(all(target_os = "linux", target_arch = "x86_64")))]
pub(crate) use unsupported::ReceiptCache;

#[cfg(all(test, target_os = "linux", target_arch = "x86_64"))]
mod tests;

use latent_core::{PlatformError, PlatformErrorCode};
use std::sync::{Arc, Mutex};

type Result<T> = std::result::Result<T, PlatformError>;
const BASE_METADATA: usize = 8192;
const ENTRY_METADATA: usize = 256;

/// An affine memory allowance, deliberately unrelated to root ownership/trust.
pub(crate) struct ReceiptBytes {
    bytes: Box<[u8]>,
    _allowance: ReadAllowance,
}

impl ReceiptBytes {
    pub(crate) fn as_bytes(&self) -> &[u8] {
        &self.bytes
    }
}

struct ReadAllowance {
    statistics: Arc<Mutex<AotReceiptCacheSnapshot>>,
    size: usize,
}

impl Drop for ReadAllowance {
    fn drop(&mut self) {
        let mut statistics = self
            .statistics
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        statistics.read_owners -= 1;
        statistics.retained_read_bytes -= self.size;
    }
}

#[derive(Debug, Clone, Copy, Default, PartialEq, Eq)]
pub(crate) struct ReceiptReclamation {
    pub removed_entries: usize,
    pub reclaimed_bytes: u64,
    pub staging_reclaimed: bool,
}

fn failure(code: PlatformErrorCode, reason: &'static str) -> PlatformError {
    PlatformError {
        code,
        message: reason.into(),
        retryable: matches!(
            code,
            PlatformErrorCode::Unavailable | PlatformErrorCode::ResourceExhausted
        ),
        details: Vec::new(),
    }
}

fn invalid() -> PlatformError {
    failure(
        PlatformErrorCode::InvalidArgument,
        "native-receipt-cache-invalid-input",
    )
}

fn capacity() -> PlatformError {
    failure(
        PlatformErrorCode::ResourceExhausted,
        "native-receipt-cache-capacity",
    )
}

fn corrupt() -> PlatformError {
    failure(
        PlatformErrorCode::CorruptArtifact,
        "native-receipt-cache-corrupt",
    )
}

fn uncertain() -> PlatformError {
    failure(
        PlatformErrorCode::Unavailable,
        "native-receipt-cache-durability-uncertain",
    )
}

fn pressure() -> PlatformError {
    failure(
        PlatformErrorCode::ResourceExhausted,
        "native-receipt-cache-reclaimable-pressure",
    )
}
