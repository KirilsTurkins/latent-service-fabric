use super::incompatible;
use crate::rollouts::Result;
use latent_artifacts::web::CheckedWebLayout;

pub(super) fn compare(previous: &CheckedWebLayout, next: &CheckedWebLayout) -> Result<()> {
    let previous_manifest = previous.manifest();
    let next_manifest = next.manifest();
    let previous_renderer = previous_manifest
        .renderer
        .as_ref()
        .ok_or_else(incompatible)?;
    let next_renderer = next_manifest.renderer.as_ref().ok_or_else(incompatible)?;
    if previous.name() != next.name()
        || previous_manifest.format_version != next_manifest.format_version
        || previous_manifest.profile != next_manifest.profile
        || previous_renderer.profile != next_renderer.profile
        || previous_renderer.profile_digest != next_renderer.profile_digest
        || previous_renderer.backend_profile != next_renderer.backend_profile
        || previous_manifest.routes.iter().any(|route| {
            !next_manifest
                .routes
                .iter()
                .any(|candidate| candidate == route)
        })
    {
        return Err(incompatible());
    }
    Ok(())
}
