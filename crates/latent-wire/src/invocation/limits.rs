use super::boundary_error;
use latent_core::{PlatformError, PlatformErrorCode};

/// Hard ceilings applied before expensive lifecycle work begins.
#[allow(clippy::struct_field_names)]
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct InvocationLimits {
    pub max_message_bytes: usize,
    pub max_payload_bytes: usize,
    pub max_metadata_entries: usize,
    pub max_metadata_bytes: usize,
    pub max_string_bytes: usize,
    pub max_id_bytes: usize,
    pub max_cancel_reason_bytes: usize,
    pub max_timeout_millis: u64,
    pub max_cpu_fuel: u64,
    pub max_memory_bytes: u64,
    pub max_child_calls: u32,
    pub max_outbound_requests: u32,
    pub max_state_read_bytes: u64,
    pub max_state_write_bytes: u64,
    pub max_blob_read_bytes: u64,
    pub max_blob_write_bytes: u64,
    pub max_log_bytes: u64,
    pub max_effect_count: u32,
    pub max_platform_error_details: usize,
    pub max_platform_error_fields: usize,
    pub max_platform_error_message_bytes: usize,
}
impl Default for InvocationLimits {
    fn default() -> Self {
        Self {
            max_message_bytes: 4 * 1024 * 1024,
            max_payload_bytes: 1024 * 1024,
            max_metadata_entries: 64,
            max_metadata_bytes: 32 * 1024,
            max_string_bytes: 4 * 1024,
            max_id_bytes: 512,
            max_cancel_reason_bytes: 1024,
            max_timeout_millis: 5 * 60 * 1000,
            max_cpu_fuel: 10_000_000_000,
            max_memory_bytes: 1024 * 1024 * 1024,
            max_child_calls: 0,
            max_outbound_requests: 0,
            max_state_read_bytes: 0,
            max_state_write_bytes: 0,
            max_blob_read_bytes: 0,
            max_blob_write_bytes: 0,
            max_log_bytes: 64 * 1024 * 1024,
            max_effect_count: 0,
            max_platform_error_details: 16,
            max_platform_error_fields: 32,
            max_platform_error_message_bytes: 2 * 1024,
        }
    }
}

impl InvocationLimits {
    pub fn validate(&self) -> Result<(), PlatformError> {
        if self.max_message_bytes == 0
            || isize::try_from(self.max_message_bytes).is_err()
            || self.max_payload_bytes == 0
            || self.max_payload_bytes > self.max_message_bytes
            || self.max_metadata_entries == 0
            || self.max_metadata_bytes == 0
            || self.max_string_bytes == 0
            || self.max_id_bytes == 0
            || self.max_cancel_reason_bytes == 0
            || self.max_timeout_millis == 0
            || self.max_cpu_fuel == 0
            || self.max_memory_bytes == 0
            || self.max_platform_error_details == 0
            || self.max_platform_error_fields == 0
            || self.max_platform_error_message_bytes == 0
            || [
                self.max_metadata_bytes,
                self.max_string_bytes,
                self.max_id_bytes,
                self.max_cancel_reason_bytes,
                self.max_platform_error_message_bytes,
            ]
            .into_iter()
            .any(|limit| limit > self.max_message_bytes)
            || self
                .max_metadata_entries
                .checked_mul(4096)
                .is_none_or(|bytes| bytes > self.max_message_bytes)
            || self
                .max_platform_error_details
                .checked_mul(self.max_platform_error_fields)
                .and_then(|entries| entries.checked_mul(4096))
                .is_none_or(|bytes| bytes > self.max_message_bytes)
            || self.max_timeout_millis > 24 * 60 * 60 * 1000
            || self.max_child_calls != 0
            || self.max_outbound_requests != 0
            || self.max_state_read_bytes != 0
            || self.max_state_write_bytes != 0
            || self.max_blob_read_bytes != 0
            || self.max_blob_write_bytes != 0
            || self.max_effect_count != 0
        {
            return Err(boundary_error(
                PlatformErrorCode::InvalidArgument,
                "invalid invocation limits",
            ));
        }
        Ok(())
    }
}
