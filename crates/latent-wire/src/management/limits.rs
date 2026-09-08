use latent_core::{PlatformError, PlatformErrorCode};

use crate::invocation::InvocationLimits;

#[cfg(test)]
mod tests;

#[derive(Debug, Clone, PartialEq, Eq)]
#[allow(clippy::struct_field_names)]
pub struct ManagementLimits {
    pub auth: InvocationLimits,
    pub max_request_bytes: usize,
    pub max_response_bytes: usize,
    pub max_component_bytes: usize,
    pub max_manifest_bytes: usize,
    pub max_contract_metadata_bytes: usize,
    pub max_metadata_entries: usize,
    pub max_metadata_bytes: usize,
    pub max_string_bytes: usize,
    pub max_id_bytes: usize,
    pub default_page_size: u32,
    pub max_page_size: u32,
    pub max_page_token_bytes: usize,
    pub max_collection_entries: usize,
    pub max_route_services: usize,
    pub max_route_revisions: usize,
}

impl Default for ManagementLimits {
    fn default() -> Self {
        Self {
            auth: InvocationLimits::default(),
            max_request_bytes: 20 * 1024 * 1024,
            max_response_bytes: 4 * 1024 * 1024,
            max_component_bytes: 16 * 1024 * 1024,
            max_manifest_bytes: 1024 * 1024,
            max_contract_metadata_bytes: 1024 * 1024,
            max_metadata_entries: 64,
            max_metadata_bytes: 32 * 1024,
            max_string_bytes: 4096,
            max_id_bytes: 512,
            default_page_size: 50,
            max_page_size: 1000,
            max_page_token_bytes: 8192,
            max_collection_entries: 1024,
            max_route_services: 1024,
            max_route_revisions: 4096,
        }
    }
}

impl ManagementLimits {
    pub fn validate(&self) -> Result<(), PlatformError> {
        self.auth.validate()?;
        let envelope = self.max_request_bytes.min(self.max_response_bytes);
        let invalid = self.max_request_bytes == 0
            // The scoped route source reserves a fixed 512-byte projection header.
            || self.max_response_bytes < 512
            || isize::try_from(self.max_request_bytes).is_err()
            || isize::try_from(self.max_response_bytes).is_err()
            || self.default_page_size == 0
            || self.default_page_size > self.max_page_size
            || [
                self.max_component_bytes,
                self.max_manifest_bytes,
                self.max_contract_metadata_bytes,
            ]
            .into_iter()
            .any(|value| value == 0 || value > self.max_request_bytes)
            || [
                self.max_metadata_bytes,
                self.max_string_bytes,
                self.max_id_bytes,
                self.max_page_token_bytes,
            ]
            .into_iter()
            .any(|value| value == 0 || value > envelope)
            || [
                self.max_metadata_entries,
                self.max_collection_entries,
                self.max_route_services,
                self.max_route_revisions,
            ]
            .into_iter()
            .any(|value| value == 0 || value > self.max_response_bytes);
        if invalid {
            return Err(PlatformError {
                code: PlatformErrorCode::InvalidArgument,
                message: "invalid management limits".to_owned(),
                retryable: false,
                details: Vec::new(),
            });
        }
        Ok(())
    }
}
