use super::super::{capacity, error, identifier};
use super::{model::Image, Compiled, PolicyStoreLimits};
use latent_core::{ArtifactBlobDigest, PlatformError, PlatformErrorCode};
use serde::Serialize;
use std::io::Write;

pub(super) fn corrupt() -> PlatformError {
    error(
        PlatformErrorCode::CorruptArtifact,
        "capability-policy-history-corrupt",
    )
}
pub(super) fn digest(bytes: &[u8]) -> String {
    latent_artifacts::package::artifact_blob_digest(bytes).to_string()
}
pub(super) fn is_digest(value: &str) -> bool {
    value.len() == 71 && value.parse::<ArtifactBlobDigest>().is_ok()
}
pub(super) fn encode(value: &impl Serialize, maximum: usize) -> Result<Vec<u8>, PlatformError> {
    let mut writer = Bounded {
        bytes: Vec::new(),
        maximum,
    };
    serde_json::to_writer(&mut writer, value).map_err(|_| capacity())?;
    Ok(writer.bytes)
}
struct Bounded {
    bytes: Vec<u8>,
    maximum: usize,
}
impl Write for Bounded {
    fn write(&mut self, bytes: &[u8]) -> std::io::Result<usize> {
        if bytes.len() > self.maximum - self.bytes.len() {
            return Err(std::io::Error::other("policy serialization capacity"));
        }
        self.bytes.extend_from_slice(bytes);
        Ok(bytes.len())
    }
    fn flush(&mut self) -> std::io::Result<()> {
        Ok(())
    }
}

pub(super) fn decode(bytes: &[u8], limits: PolicyStoreLimits) -> Result<Image, PlatformError> {
    if bytes.len() > limits.maximum_catalog_bytes {
        return Err(corrupt());
    }
    // Every node is a closed struct, bounded string or sequence. Serde rejects
    // duplicate fields; nested policy JSON is independently preflighted before
    // any compiled snapshot is installed. The entire input also has a hard cap.
    let image: Image = serde_json::from_slice(bytes).map_err(|_| corrupt())?;
    validate(&image, limits)?;
    if encode(&image, limits.maximum_catalog_bytes)? != bytes {
        return Err(corrupt());
    }
    Ok(image)
}
fn validate(image: &Image, limits: PolicyStoreLimits) -> Result<(), PlatformError> {
    if image.format_version != 1
        || image.generation == 0
        || image.records.len() > limits.maximum_records
        || image.outcomes.len() > limits.maximum_outcomes
    {
        return Err(corrupt());
    }
    let mut keys = std::collections::BTreeSet::new();
    for row in &image.records {
        if !identifier(&row.tenant)
            || !identifier(&row.id)
            || row.revision <= 1
            || row.revision > image.generation
            || !is_digest(&row.digest)
            || !keys.insert((&row.tenant, row.kind, &row.id))
        {
            return Err(corrupt());
        }
        if let Some(document) = &row.document {
            let parsed = Compiled::parse(row.kind, &row.tenant, document.as_bytes())
                .map_err(|_| corrupt())?;
            if parsed.canonical() != document.as_bytes() || parsed.digest() != row.digest {
                return Err(corrupt());
            }
        }
    }
    let mut operations = std::collections::BTreeSet::new();
    let mut previous = 1;
    for outcome in &image.outcomes {
        let r = &outcome.receipt;
        if !identifier(&r.operation_id)
            || !is_digest(&outcome.fingerprint)
            || !is_digest(&r.digest)
            || r.revision <= previous
            || r.revision > image.generation
            || !operations.insert((&r.tenant, &r.operation_id))
        {
            return Err(corrupt());
        }
        let row = image
            .records
            .iter()
            .find(|v| v.matches(&r.tenant, r.kind, &r.id))
            .ok_or_else(corrupt)?;
        if row.revision < r.revision
            || (row.revision == r.revision
                && (row.digest != r.digest || row.document.is_none() != r.revoked))
        {
            return Err(corrupt());
        }
        previous = r.revision;
    }
    if image.generation > 1
        && (image
            .outcomes
            .last()
            .is_none_or(|o| o.receipt.revision != image.generation)
            || image
                .records
                .iter()
                .all(|row| row.revision != image.generation))
    {
        return Err(corrupt());
    }
    Ok(())
}
