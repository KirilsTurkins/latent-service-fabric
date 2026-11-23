//! Check signed state declarations before a shared rollout can publish routes.
use crate::rollouts::{error, Result};
use latent_artifacts::package::LayerRole;
use latent_core::{DeploymentId, PlatformError, PlatformErrorCode};
use latent_manifest::{JsonManifestCodec, ManifestCodec, TransactionBinding};
use latent_packaging::PackageBundle;

pub(super) fn require_compatible(
    served: &PackageBundle,
    served_deployment: &DeploymentId,
    target: &PackageBundle,
    target_deployment: &DeploymentId,
) -> Result<()> {
    match (
        binding(served, served_deployment)?,
        binding(target, target_deployment)?,
    ) {
        (None, None) => Ok(()),
        (Some(served), Some(target))
            if served.namespace == target.namespace
                && served.state_schema == target.state_schema
                && served
                    .operations
                    .iter()
                    .all(|operation| target.operations.contains(operation)) =>
        {
            Ok(())
        }
        _ => Err(incompatible()),
    }
}

pub(in crate::deployments) fn binding(
    package: &PackageBundle,
    deployment: &DeploymentId,
) -> Result<Option<TransactionBinding>> {
    let layers = &package.layout().config().layers;
    let Some(layer) = layers
        .iter()
        .find(|layer| layer.path == TransactionBinding::ASSET_PATH)
    else {
        if package.surface().is_some_and(|surface| {
            surface
                .imports()
                .iter()
                .any(|name| transaction_import(name))
        }) {
            return Err(incompatible());
        }
        return Ok(None);
    };
    if layer.role != LayerRole::Asset
        || layer.media_type != TransactionBinding::MEDIA_TYPE
        || layer.size > TransactionBinding::MAXIMUM_BYTES as u64
    {
        return Err(incompatible());
    }
    let declaration =
        TransactionBinding::decode(package.blob(&layer.path).ok_or_else(incompatible)?)
            .map_err(|_| incompatible())?;
    let manifest = layers
        .iter()
        .find(|layer| layer.role == LayerRole::CapsuleManifest)
        .and_then(|layer| package.blob(&layer.path))
        .ok_or_else(incompatible)?;
    let capsule = JsonManifestCodec::default()
        .decode_capsule(manifest)
        .map_err(|_| incompatible())?;
    if declaration.capsule != capsule.metadata.name || declaration.deployment != deployment.0 {
        return Err(incompatible());
    }
    Ok(Some(declaration))
}

pub(in crate::deployments) fn transaction_import(name: &str) -> bool {
    matches!(
        name,
        "latent:state/key-value@0.2.0" | "latent:intents/staging@0.1.0"
    )
}

fn incompatible() -> PlatformError {
    error(
        PlatformErrorCode::IncompatibleContract,
        "rollout-state-schema-incompatible",
    )
}
