use latent_core::PlatformError;

/// Hard semantic-work ceilings. Defaults are maxima; callers may only lower them.
/// Counts bound parser inputs and examined structures, not exact process RSS.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct SemanticLimits {
    pub max_component_bytes: usize,
    pub max_component_depth: usize,
    pub max_sections: usize,
    pub max_core_functions: usize,
    pub max_core_locals: usize,
    pub max_operators: usize,
    pub max_component_items: usize,
    pub max_type_nodes: usize,
    pub max_type_depth: usize,
    pub max_type_members: usize,
    pub max_name_bytes: usize,
    pub max_wit_packages: usize,
    pub max_wit_source_bytes: usize,
    pub max_total_wit_bytes: usize,
    pub max_wit_tokens: usize,
    pub max_imports: usize,
    pub max_exports: usize,
    pub max_functions: usize,
    pub max_parameters: usize,
    pub max_summary_bytes: usize,
}

impl Default for SemanticLimits {
    fn default() -> Self {
        Self {
            max_component_bytes: 64 * 1024 * 1024,
            max_component_depth: 16,
            max_sections: 8192,
            max_core_functions: 65_536,
            max_core_locals: 1_048_576,
            max_operators: 2_000_000,
            max_component_items: 16_384,
            max_type_nodes: 65_536,
            max_type_depth: 64,
            max_type_members: 1024,
            max_name_bytes: 512,
            max_wit_packages: 256,
            max_wit_source_bytes: 256 * 1024,
            max_total_wit_bytes: 4 * 1024 * 1024,
            max_wit_tokens: 262_144,
            max_imports: 64,
            max_exports: 256,
            max_functions: 4096,
            max_parameters: 256,
            max_summary_bytes: 1024 * 1024,
        }
    }
}

impl SemanticLimits {
    pub(crate) fn validate(self) -> Result<(), PlatformError> {
        let maximum = Self::default();
        macro_rules! check {
            ($($field:ident),+ $(,)?) => {$(
                if self.$field == 0 || self.$field > maximum.$field {
                    return Err(super::invalid("invalid-semantic-limits"));
                }
            )+};
        }
        check!(
            max_component_bytes,
            max_component_depth,
            max_sections,
            max_core_functions,
            max_core_locals,
            max_operators,
            max_component_items,
            max_type_nodes,
            max_type_depth,
            max_type_members,
            max_name_bytes,
            max_wit_packages,
            max_wit_source_bytes,
            max_total_wit_bytes,
            max_wit_tokens,
            max_imports,
            max_exports,
            max_functions,
            max_parameters,
            max_summary_bytes
        );
        Ok(())
    }
}

pub(super) fn add(total: &mut usize, amount: usize, maximum: usize) -> Result<(), PlatformError> {
    *total = total
        .checked_add(amount)
        .filter(|total| *total <= maximum)
        .ok_or_else(|| super::exhausted("semantic-work-limit"))?;
    Ok(())
}

pub(super) fn name(name: &str, limits: SemanticLimits) -> Result<(), PlatformError> {
    if name.is_empty() || name.len() > limits.max_name_bytes {
        return Err(super::exhausted("semantic-name-limit"));
    }
    Ok(())
}
