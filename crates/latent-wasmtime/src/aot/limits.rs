use latent_core::{PlatformError, PlatformErrorCode};

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct AotCompilerLimits {
    pub maximum_output_bytes: usize,
    pub maximum_profile_entries: usize,
    pub maximum_profile_bytes: usize,
    pub maximum_identity_bytes: usize,
}
impl Default for AotCompilerLimits {
    fn default() -> Self {
        Self {
            maximum_output_bytes: 128 * 1024 * 1024,
            maximum_profile_entries: 256,
            maximum_profile_bytes: 256 * 1024,
            maximum_identity_bytes: 1024,
        }
    }
}
impl AotCompilerLimits {
    pub fn validate(self) -> Result<Self, PlatformError> {
        if self.maximum_output_bytes == 0
            || self.maximum_output_bytes > 512 * 1024 * 1024
            || self.maximum_profile_entries == 0
            || self.maximum_profile_entries > 512
            || self.maximum_profile_bytes == 0
            || self.maximum_profile_bytes > 512 * 1024
            || self.maximum_identity_bytes == 0
            || self.maximum_identity_bytes > 4096
        {
            return Err(super::error(
                PlatformErrorCode::InvalidArgument,
                "invalid-aot-compiler-limits",
            ));
        }
        Ok(self)
    }
    pub(super) fn identity(self, value: &str) -> Result<(), PlatformError> {
        if value.is_empty()
            || value.len() > self.maximum_identity_bytes
            || value.chars().any(char::is_control)
        {
            return Err(super::invalid());
        }
        Ok(())
    }
}
