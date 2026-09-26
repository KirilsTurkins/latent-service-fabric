use super::{invalid, PlatformError};

/// Logical ownership limits, not a claim about process RSS. Policy documents
/// additionally retain the policy owner's existing bounded snapshot leases.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct CapabilityBrokerLimits {
    pub maximum_providers: usize,
    pub maximum_plans: usize,
    pub maximum_sessions: usize,
    pub maximum_handles: usize,
    pub maximum_handles_per_session: usize,
    pub maximum_calls: usize,
    pub maximum_calls_per_session: usize,
    pub maximum_results: usize,
    pub maximum_metadata_bytes: usize,
    pub maximum_buffer_bytes: usize,
    pub maximum_input_bytes: usize,
    pub maximum_output_bytes: usize,
    /// Cumulative per-call transfers; these do not reserve whole bodies in memory.
    pub maximum_stream_input_bytes: u64,
    pub maximum_stream_output_bytes: u64,
}
impl Default for CapabilityBrokerLimits {
    fn default() -> Self {
        Self {
            maximum_providers: 32,
            maximum_plans: 256,
            maximum_sessions: 128,
            maximum_handles: 2048,
            maximum_handles_per_session: 16,
            maximum_calls: 256,
            maximum_calls_per_session: 16,
            maximum_results: 256,
            maximum_metadata_bytes: 8 * 1024 * 1024,
            maximum_buffer_bytes: 32 * 1024 * 1024,
            maximum_input_bytes: 64 * 1024,
            maximum_output_bytes: 64 * 1024,
            maximum_stream_input_bytes: 16 * 1024 * 1024,
            maximum_stream_output_bytes: 16 * 1024 * 1024,
        }
    }
}
impl CapabilityBrokerLimits {
    pub fn validate(self) -> Result<(), PlatformError> {
        for (value, max) in [
            (self.maximum_providers, 256),
            (self.maximum_plans, 4096),
            (self.maximum_sessions, 4096),
            (self.maximum_handles, 65536),
            (self.maximum_handles_per_session, 128),
            (self.maximum_calls, 65536),
            (self.maximum_calls_per_session, 128),
            (self.maximum_results, 65536),
            (self.maximum_metadata_bytes, 256 * 1024 * 1024),
            (self.maximum_buffer_bytes, 256 * 1024 * 1024),
            (self.maximum_input_bytes, 1024 * 1024),
            (self.maximum_output_bytes, 1024 * 1024),
        ] {
            if value == 0 || value > max {
                return Err(invalid());
            }
        }
        if self.maximum_stream_input_bytes > 63 * 1024 * 1024
            || self.maximum_stream_output_bytes > 63 * 1024 * 1024
            || self.maximum_handles_per_session > self.maximum_handles
            || self.maximum_calls_per_session > self.maximum_calls
            || self.maximum_input_bytes + self.maximum_output_bytes > self.maximum_buffer_bytes
        {
            return Err(invalid());
        }
        Ok(())
    }
}
#[derive(Debug, Clone, Copy, Default, PartialEq, Eq)]
pub struct CapabilityBrokerSnapshot {
    pub providers: usize,
    pub plans: usize,
    pub sessions: usize,
    pub handles: usize,
    pub calls: usize,
    pub results: usize,
    pub metadata_bytes: usize,
    pub buffer_bytes: usize,
}
