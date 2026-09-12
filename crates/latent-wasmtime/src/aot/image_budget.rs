//! Affine accounting for the complete page-rounded native ELF mapping.
//!
//! This excludes decoder/type/unwind heap, allocator arenas, lazy COW memfd data,
//! guest/pooling mappings and RSS. Counters follow actual native owner lifetime.

use crate::aot::error;
use latent_core::{PlatformError, PlatformErrorCode};
use std::sync::{Arc, Mutex, MutexGuard};

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct NativeImageLimits {
    pub maximum_images: usize,
    /// Upper bound applies after rounding to the actual host page size.
    pub maximum_image_bytes: usize,
    pub maximum_total_bytes: usize,
}
impl Default for NativeImageLimits {
    fn default() -> Self {
        Self {
            maximum_images: 64,
            maximum_image_bytes: 128 * 1024 * 1024,
            maximum_total_bytes: 256 * 1024 * 1024,
        }
    }
}
impl NativeImageLimits {
    pub fn validate(self) -> Result<Self, PlatformError> {
        if !(1..=4096).contains(&self.maximum_images)
            || !(1..=256 * 1024 * 1024).contains(&self.maximum_image_bytes)
            || !(1..=1024 * 1024 * 1024).contains(&self.maximum_total_bytes)
            || self.maximum_total_bytes < self.maximum_image_bytes
        {
            return Err(error(
                PlatformErrorCode::InvalidArgument,
                "invalid-native-image-limits",
            ));
        }
        Ok(self)
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct NativeImageSnapshot {
    pub limits: NativeImageLimits,
    pub images: usize,
    pub bytes: usize,
    pub loading_images: usize,
    pub loading_bytes: usize,
    pub loader_attempts: u64,
}

#[derive(Debug)]
pub(crate) struct NativeImageBudget {
    used: Mutex<NativeImageSnapshot>,
}
impl NativeImageBudget {
    pub(crate) fn new(limits: NativeImageLimits) -> Result<Arc<Self>, PlatformError> {
        Ok(Arc::new(Self {
            used: Mutex::new(NativeImageSnapshot {
                limits: limits.validate()?,
                images: 0,
                bytes: 0,
                loading_images: 0,
                loading_bytes: 0,
                loader_attempts: 0,
            }),
        }))
    }
    pub(crate) fn snapshot(&self) -> NativeImageSnapshot {
        *self.state()
    }
    fn state(&self) -> MutexGuard<'_, NativeImageSnapshot> {
        // No caller code, I/O or fallible work runs under this bookkeeping lock.
        self.used
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
    }
    pub(crate) fn reserve(
        self: &Arc<Self>,
        native_bytes: usize,
    ) -> Result<NativeImagePermit, PlatformError> {
        let bytes = mapping_bytes(native_bytes)?;
        self.reserve_rounded(bytes)
    }
    fn reserve_rounded(self: &Arc<Self>, bytes: usize) -> Result<NativeImagePermit, PlatformError> {
        let mut used = self.state();
        let total = used.bytes.checked_add(bytes).ok_or_else(exhausted)?;
        if used.images >= used.limits.maximum_images
            || bytes > used.limits.maximum_image_bytes
            || total > used.limits.maximum_total_bytes
        {
            return Err(exhausted());
        }
        used.images += 1;
        used.bytes = total;
        used.loading_images += 1;
        used.loading_bytes += bytes;
        Ok(NativeImagePermit {
            budget: Arc::clone(self),
            bytes,
            loading: true,
        })
    }
}

/// Declared after every native owner it covers. No Clone or public constructor.
#[derive(Debug)]
pub(crate) struct NativeImagePermit {
    budget: Arc<NativeImageBudget>,
    bytes: usize,
    loading: bool,
}
impl NativeImagePermit {
    pub(crate) fn record_attempt(&self) {
        let mut used = self.budget.state();
        used.loader_attempts = used.loader_attempts.saturating_add(1);
    }
    pub(crate) fn loaded(&mut self) {
        if self.loading {
            let mut used = self.budget.state();
            used.loading_images -= 1;
            used.loading_bytes -= self.bytes;
            self.loading = false;
        }
    }
}
impl Drop for NativeImagePermit {
    fn drop(&mut self) {
        let mut used = self.budget.state();
        used.images -= 1;
        used.bytes -= self.bytes;
        if self.loading {
            used.loading_images -= 1;
            used.loading_bytes -= self.bytes;
        }
    }
}

pub(crate) fn mapping_bytes(native_bytes: usize) -> Result<usize, PlatformError> {
    rounded(native_bytes, page_size()?)
}

fn rounded(bytes: usize, page: usize) -> Result<usize, PlatformError> {
    if bytes == 0 || !page.is_power_of_two() {
        return Err(exhausted());
    }
    bytes
        .checked_add(page - 1)
        .map(|value| value & !(page - 1))
        .ok_or_else(exhausted)
}
#[cfg_attr(
    all(target_os = "linux", target_arch = "x86_64"),
    expect(
        clippy::unnecessary_wraps,
        reason = "the shared API rejects unsupported platforms with an error"
    )
)]
fn page_size() -> Result<usize, PlatformError> {
    #[cfg(all(target_os = "linux", target_arch = "x86_64"))]
    {
        Ok(rustix::param::page_size())
    }
    #[cfg(not(all(target_os = "linux", target_arch = "x86_64")))]
    {
        Err(error(
            PlatformErrorCode::IncompatibleContract,
            "aot-sandbox-platform-unsupported",
        ))
    }
}
fn exhausted() -> PlatformError {
    error(
        PlatformErrorCode::ResourceExhausted,
        "native-image-resource-limit",
    )
}

#[cfg(test)]
mod tests;
