use super::{pipeline_error, PipelineCommand};
use latent_core::{PlatformError, PlatformErrorCode};
use std::time::Duration;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct TelemetryPipelineConfig {
    pub queue_capacity: usize,
    /// Owned string capacities plus conservative record/map bookkeeping.
    /// Channel slots and one exporting record are bounded separately.
    pub maximum_record_bytes: usize,
    pub maximum_attributes: usize,
    pub maximum_attribute_name_bytes: usize,
    pub maximum_attribute_value_bytes: usize,
    pub fail_on_drop: bool,
    /// Bounds a cooperatively polled export; blocking implementations are unsupported.
    pub export_timeout: Duration,
    pub flush_timeout: Duration,
    pub shutdown_timeout: Duration,
}
impl Default for TelemetryPipelineConfig {
    fn default() -> Self {
        Self {
            queue_capacity: 1_024,
            maximum_record_bytes: 64 * 1_024,
            maximum_attributes: 32,
            maximum_attribute_name_bytes: 64,
            maximum_attribute_value_bytes: 256,
            fail_on_drop: false,
            export_timeout: Duration::from_secs(1),
            flush_timeout: Duration::from_secs(5),
            shutdown_timeout: Duration::from_secs(5),
        }
    }
}
impl TelemetryPipelineConfig {
    pub fn validate(&self) -> Result<(), PlatformError> {
        let allocation = self.queue_capacity.checked_add(1).and_then(|count| {
            self.maximum_record_bytes
                .checked_add(size_of::<PipelineCommand>())
                .and_then(|bytes| count.checked_mul(bytes))
        });
        if self.queue_capacity == 0
            || self.queue_capacity > tokio::sync::Semaphore::MAX_PERMITS
            || allocation.is_none_or(|bytes| bytes > isize::MAX as usize)
            || self.maximum_record_bytes == 0
            || self.maximum_attributes == 0
            || self.maximum_attribute_name_bytes == 0
            || self.maximum_attribute_value_bytes == 0
            || [
                self.export_timeout,
                self.flush_timeout,
                self.shutdown_timeout,
            ]
            .iter()
            .any(|duration| duration.is_zero() || *duration > Duration::from_mins(1))
        {
            return Err(pipeline_error(
                PlatformErrorCode::InvalidArgument,
                "invalid telemetry pipeline bounds",
            ));
        }
        Ok(())
    }
}
