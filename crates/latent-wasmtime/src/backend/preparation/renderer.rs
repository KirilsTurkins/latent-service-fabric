use latent_artifacts::CapsuleArtifact;
use latent_core::PlatformError;

impl super::super::PreparationContext {
    pub(in crate::backend) fn validate_renderer_component(
        &self,
        artifact: &CapsuleArtifact,
    ) -> Result<(), PlatformError> {
        if let Some(renderer) = &artifact.manifest.runtime_requirements.renderer {
            // Validate before either in-process compilation or isolated native
            // loading. A manifest label never substitutes for the actual public
            // async export and sealed context import surface.
            self.runtime_profile.check_capsule(&artifact.manifest)?;
            latent_packaging::validate_web_renderer_with_backend(
                &artifact.component_bytes,
                renderer.profile,
                latent_artifacts::web::WebBackendProfile::from_imports(&artifact.manifest.imports)?,
                latent_packaging::SemanticLimits {
                    max_component_bytes: self.config.maximum_component_bytes.min(32 * 1024 * 1024),
                    ..latent_packaging::SemanticLimits::default()
                },
            )?;
        }
        Ok(())
    }
}
