use super::super::{invalid, Result};
use crate::OciDescriptor;
use latent_artifacts::package::PackageLimits;
use latent_core::ArtifactBlobDigest;
use reqwest::header::{HeaderMap, CONTENT_TYPE};

pub(crate) fn content_type(headers: &HeaderMap, expected: &str) -> Result<()> {
    let mut values = headers.get_all(CONTENT_TYPE).iter();
    let value = values
        .next()
        .ok_or_else(|| invalid("missing-oci-content-type"))?
        .to_str()
        .map_err(|_| invalid("invalid-oci-content-type"))?;
    if values.next().is_some()
        || !value
            .split(';')
            .next()
            .is_some_and(|value| value.trim().eq_ignore_ascii_case(expected))
    {
        return Err(invalid("unexpected-oci-content-type"));
    }
    Ok(())
}

pub(super) fn descriptor(value: &OciDescriptor, maximum: u64, limits: PackageLimits) -> Result<()> {
    if maximum == 0
        || maximum > limits.max_layer_bytes
        || value.size_bytes > maximum
        || value.digest.parse::<ArtifactBlobDigest>().is_err()
    {
        return Err(invalid("invalid-oci-blob-descriptor"));
    }
    super::super::referrers::media_type(&value.media_type, limits.max_string_bytes)?;
    if let Some(kind) = &value.artifact_type {
        super::super::referrers::media_type(kind, limits.max_string_bytes)?;
    }
    if value.annotations.len() > limits.max_annotations
        || value.annotations.iter().any(|(key, value)| {
            key.is_empty()
                || key.len() > limits.max_string_bytes
                || value.len() > limits.max_string_bytes
        })
    {
        return Err(invalid("invalid-oci-descriptor-annotations"));
    }
    Ok(())
}
