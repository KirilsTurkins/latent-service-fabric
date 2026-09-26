use super::AngularBuildRecipe;
use crate::{BuildMaterial, SignatureFailure, SignatureResult};
use latent_artifacts::web::{renderer_profile_digest, WebRendererProfile};

pub(super) fn validate(
    recipe: &AngularBuildRecipe,
    materials: &[BuildMaterial],
) -> SignatureResult<()> {
    for (text, maximum) in [
        (&recipe.compiler, 64),
        (&recipe.renderer_profile, 64),
        (&recipe.profile_digest, 71),
        (&recipe.renderer_digest, 71),
    ] {
        if text.capacity() > maximum {
            return Err(SignatureFailure::ResourceLimit.into());
        }
    }
    if recipe.compiler != "lsf-angular-component"
        || recipe.recipe_version != 1
        || recipe.renderer_profile != "angular-ssr-component-v1"
        || recipe.profile_digest
            != renderer_profile_digest(WebRendererProfile::AngularSsrComponentV1).as_str()
        || recipe.renderer_size == 0
        || recipe.renderer_size > 32 * 1024 * 1024
        || recipe.max_hydration_bytes != 32768
        || recipe.lifecycle_scripts
    {
        return Err(SignatureFailure::PredicateDisallowed.into());
    }
    crate::provenance::validate_digest(&recipe.renderer_digest)?;
    for required in [
        "node",
        "cargo",
        "rustc",
        "wasm-tools",
        "dependency-lock",
        "npm-lock",
        "npm-tree",
        "javascript-embedding",
        "async-adapter",
        "adapter-source",
        "public-wit",
        "private-wit",
        "renderer-component",
        "angular-server-bundle",
        "angular-client-bundle",
    ] {
        let material = materials
            .iter()
            .find(|item| item.name == required)
            .ok_or(SignatureFailure::MalformedProvenance)?;
        if required == "renderer-component"
            && (material.digest != recipe.renderer_digest || material.size != recipe.renderer_size)
        {
            return Err(SignatureFailure::IntegrityMismatch.into());
        }
    }
    Ok(())
}
