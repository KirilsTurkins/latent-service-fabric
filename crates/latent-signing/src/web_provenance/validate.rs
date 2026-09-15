use super::{WebBuildObservation, WEB_ASSEMBLY_BUILD_TYPE};
use crate::{provenance, ProvenanceLimits, SignatureFailure, SignatureResult};
use std::collections::BTreeSet;

pub(crate) fn validate_observation(
    value: &WebBuildObservation,
    limits: ProvenanceLimits,
) -> SignatureResult<()> {
    limits.validate()?;
    if value.materials.capacity() > limits.max_materials {
        return Err(SignatureFailure::ResourceLimit.into());
    }
    // Public unsigned inputs can have arbitrarily large spare allocations.
    // Reject these before a signer copies any observation into its statement.
    for (text, maximum) in [
        (&value.build_type, 128),
        (&value.source.repository, 512),
        (&value.source.revision, 64),
        (&value.source.snapshot_digest, 71),
        (&value.source.repository_trust, 32),
        (&value.source.capture, 32),
        (&value.outputs_digest, 71),
        (&value.reproducibility, 32),
        (&value.dependency_completeness, 32),
        (&value.parameters.assembler, 64),
        (&value.parameters.input_mode, 32),
    ] {
        if text.capacity() > maximum {
            return Err(SignatureFailure::ResourceLimit.into());
        }
    }
    if value.format_version != 1 || value.build_type != WEB_ASSEMBLY_BUILD_TYPE {
        return Err(SignatureFailure::UnsupportedProfile.into());
    }
    provenance::validate_repository(&value.source.repository)?;
    provenance::validate_revision(&value.source.revision)?;
    provenance::validate_digest(&value.source.snapshot_digest)?;
    provenance::validate_digest(&value.outputs_digest)?;
    if value.source.revision != value.source.snapshot_digest[7..]
        || value.source.repository_trust != "operator-asserted"
        || value.source.capture != "explicit-input-files"
        || value.outputs_count == 0
        || value.outputs_count > 256
        || value.outputs_bytes == 0
        || value.outputs_bytes > 256 * 1024 * 1024
        || value
            .finished_at
            .checked_sub(value.started_at)
            .is_none_or(|duration| duration > 3600)
        || !matches!(
            value.reproducibility.as_str(),
            "not-checked" | "two-build-byte-equality"
        )
        || value.hermetic
        || value.dependency_completeness != "declared-inputs-incomplete"
    {
        return Err(SignatureFailure::MalformedProvenance.into());
    }
    if value.parameters.assembler != "lsf-web-package-assembly"
        || value.parameters.recipe_version != 1
        || value.parameters.input_mode != "explicit-supplied-files"
    {
        return Err(SignatureFailure::PredicateDisallowed.into());
    }
    materials(value)?;
    Ok(())
}

fn materials(value: &WebBuildObservation) -> SignatureResult<()> {
    let mut names = BTreeSet::new();
    for material in &value.materials {
        if material.name.capacity() > 128 || material.digest.capacity() > 71 {
            return Err(SignatureFailure::ResourceLimit.into());
        }
        if !material
            .name
            .as_bytes()
            .first()
            .is_some_and(u8::is_ascii_alphanumeric)
            || !material
                .name
                .bytes()
                .all(|b| b.is_ascii_alphanumeric() || b"._-".contains(&b))
            || material.size == 0
            || material.size > 256 * 1024 * 1024
            || !names.insert(&material.name)
        {
            return Err(SignatureFailure::MalformedProvenance.into());
        }
        provenance::validate_digest(&material.digest)?;
        if material.name == "source-snapshot" && material.digest != value.source.snapshot_digest {
            return Err(SignatureFailure::IntegrityMismatch.into());
        }
    }
    for required in [
        "source-snapshot",
        "build-recipe",
        "toolchain-config",
        "package-assembler",
    ] {
        if !names.iter().any(|name| name.as_str() == required) {
            return Err(SignatureFailure::MalformedProvenance.into());
        }
    }
    Ok(())
}
