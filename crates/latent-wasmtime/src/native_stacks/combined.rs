//! Only the authenticated fixed graph may combine child and engine-worker stacks.
use super::*;
use crate::component_threading::Authentication;
use latent_executor::PreparedComponent;

impl StackContext {
    pub(crate) fn with_combined_http(
        budget: ActivationBudget,
        runtime: ActivationRuntime,
        size: usize,
        maximum_native: usize,
        proof: &Authentication,
        descriptor: &PreparedComponent,
    ) -> Result<Arc<Self>, PlatformError> {
        // A configuration name or an inspector result is insufficient. The
        // immutable final-byte proof must match this exact prepared component.
        proof.check_before_instantiation(descriptor)?;
        if !matches!(proof, Authentication::RustCombinedHttpVerified(_)) {
            return Err(crate::containment::platform_error(
                PlatformErrorCode::CorruptArtifact,
                "combined-http-stack-proof-required",
                false,
            ));
        }
        // Both paths share the SAME runtime Native ceiling and activation
        // memory ledger. Child total-start and duplicate-task checks are not
        // replaced by worker capacity. Cached child permits stay charged until
        // the actual Store-drop fence, even if an HTTP worker consumes a permit.
        Self::create(
            budget,
            runtime,
            size,
            maximum_native.saturating_sub(1),
            Some(maximum_native),
        )
    }
}
