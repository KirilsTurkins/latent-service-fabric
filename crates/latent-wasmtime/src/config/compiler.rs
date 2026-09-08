use latent_core::PlatformError;

use super::{invalid_config, WasmtimeConfig};

impl WasmtimeConfig {
    #[must_use]
    pub fn effective_compiler_workers(&self) -> usize {
        self.compiler_workers
            .unwrap_or(self.maximum_concurrent_preparations.min(2))
    }

    pub(super) fn validate_compiler(&self) -> Result<(), PlatformError> {
        let workers = self.effective_compiler_workers();
        if workers == 0
            || workers > 8
            || workers > self.maximum_concurrent_preparations
            || self.maximum_concurrent_preparations > 1024
            || self.maximum_preparation_waiters == 0
            || self.maximum_preparation_waiters > 1024
            || self.maximum_waiters_per_preparation == 0
            || self.maximum_waiters_per_preparation > self.maximum_preparation_waiters
            || self.maximum_ready_preparations == 0
            || self.maximum_ready_preparations > 1024
            || self.maximum_preparation_document_bytes == 0
        {
            return Err(invalid_config());
        }
        Ok(())
    }
}
