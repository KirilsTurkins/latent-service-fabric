use super::{
    exhausted,
    limits::{add, name},
    SemanticLimits,
};
use latent_core::PlatformError;
use latent_manifest::CapsuleManifest;

/// The standalone validator accepts owned inputs too. Bound them before calling
/// legacy validators which can format violations for each supplied entry.
pub(super) fn manifest(
    value: &CapsuleManifest,
    limits: SemanticLimits,
) -> Result<(), PlatformError> {
    if value.exports.len() > limits.max_exports || value.imports.len() > limits.max_imports {
        return Err(exhausted("manifest-interface-limit"));
    }
    let mut bytes = 1024;
    for text in [
        &value.api_version,
        &value.metadata.name,
        &value.semantic_version,
        &value.component_digest.0,
        &value.world.0,
        &value.minimum_fabric_version,
    ] {
        name(text, limits)?;
        add(&mut bytes, text.len(), limits.max_summary_bytes)?;
    }
    for text in [
        value.metadata.tenant.as_ref().map(|v| v.0.as_str()),
        value.metadata.namespace.as_deref(),
    ]
    .into_iter()
    .flatten()
    {
        name(text, limits)?;
        add(&mut bytes, text.len(), limits.max_summary_bytes)?;
    }
    for values in [&value.metadata.labels, &value.metadata.annotations] {
        if values.len() > limits.max_type_members {
            return Err(exhausted("manifest-metadata-count-limit"));
        }
        for (key, value) in values {
            name(key, limits)?;
            if value.len() > 4096 {
                return Err(exhausted("manifest-metadata-string-limit"));
            }
            add(
                &mut bytes,
                key.len() + value.len() + 128,
                limits.max_summary_bytes,
            )?;
        }
    }
    for identity in value
        .imports
        .iter()
        .map(|v| &v.contract.0)
        .chain(value.exports.iter().map(|v| &v.contract.0))
    {
        name(identity, limits)?;
        add(&mut bytes, identity.len() + 128, limits.max_summary_bytes)?;
    }
    Ok(())
}
