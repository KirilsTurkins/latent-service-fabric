use latent_core::PlatformError;

/// Independent v1 format ceilings. Callers may lower these limits, never raise
/// them above the profile maxima. They do not describe process RSS or guest fuel.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct PackageLimits {
    pub max_document_bytes: usize,
    pub max_depth: usize,
    pub max_nodes: usize,
    pub max_string_bytes: usize,
    pub max_layers: usize,
    pub max_annotations: usize,
    pub max_layer_bytes: u64,
    pub max_total_layer_bytes: u64,
    pub max_path_bytes: usize,
}

impl Default for PackageLimits {
    fn default() -> Self {
        Self {
            max_document_bytes: 256 * 1024,
            max_depth: 16,
            max_nodes: 16_384,
            max_string_bytes: 4096,
            max_layers: 256,
            max_annotations: 32,
            max_layer_bytes: 64 * 1024 * 1024,
            max_total_layer_bytes: 256 * 1024 * 1024,
            max_path_bytes: 240,
        }
    }
}

impl PackageLimits {
    pub(super) fn validate(self) -> Result<(), PlatformError> {
        let maximum = Self::default();
        macro_rules! check {
            ($($field:ident),+ $(,)?) => {$ (
                if self.$field == 0 || self.$field > maximum.$field {
                    return Err(super::invalid("invalid-package-limits"));
                }
            )+};
        }
        check!(
            max_document_bytes,
            max_depth,
            max_nodes,
            max_string_bytes,
            max_layers,
            max_annotations,
            max_layer_bytes,
            max_total_layer_bytes,
            max_path_bytes
        );
        Ok(())
    }
}
