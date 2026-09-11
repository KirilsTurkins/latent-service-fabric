use std::io::{self, Write};

use latent_artifacts::package::{
    validate_package_json, validate_package_path, LayerRole, PackageConfig, PackageLimits,
};
use latent_core::{ArtifactBlobDigest, PlatformError};
use serde::{Deserialize, Serialize};

pub const BUILD_INPUTS_PATH: &str = "package/build-inputs.json";

/// Observed input identity and the metadata-normalized output it produced.
/// An externally supplied receipt's input claims require separate provenance.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct BuildInputIdentity {
    pub path: String,
    pub role: LayerRole,
    pub input_digest: String,
    pub input_size: u64,
    pub output_digest: String,
    pub output_size: u64,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct BuildReceipt {
    pub format_version: u32,
    pub operation: String,
    pub packager: String,
    pub packager_version: String,
    pub inputs: Vec<BuildInputIdentity>,
}

impl BuildReceipt {
    pub(crate) fn new(inputs: Vec<BuildInputIdentity>) -> Self {
        Self {
            format_version: 1,
            operation: "package-supplied-artifacts".to_owned(),
            packager: "latent-packaging".to_owned(),
            packager_version: env!("CARGO_PKG_VERSION").to_owned(),
            inputs,
        }
    }

    pub(crate) fn validate_outputs(
        &self,
        config: &PackageConfig,
        limits: PackageLimits,
    ) -> Result<(), PlatformError> {
        self.validate(limits)?;
        let outputs: Vec<_> = config
            .layers
            .iter()
            .filter(|layer| layer.path != BUILD_INPUTS_PATH)
            .collect();
        if outputs.len() != self.inputs.len() {
            return Err(crate::invalid("build-inputs-output-mismatch"));
        }
        for (input, output) in self.inputs.iter().zip(outputs) {
            if input.path != output.path
                || input.role != output.role
                || input.output_digest != output.digest.as_str()
                || input.output_size != output.size
            {
                return Err(crate::invalid("build-inputs-output-mismatch"));
            }
        }
        Ok(())
    }

    fn validate(&self, limits: PackageLimits) -> Result<(), PlatformError> {
        limits.validate()?;
        if self.format_version != 1
            || self.operation != "package-supplied-artifacts"
            || self.packager != "latent-packaging"
            || self.packager_version.is_empty()
            || self.packager_version.len() > 128
            || !self
                .packager_version
                .bytes()
                .all(|byte| byte.is_ascii_alphanumeric() || b".-+".contains(&byte))
            || self.inputs.is_empty()
            || self.inputs.len() >= limits.max_layers
        {
            return Err(crate::invalid("invalid-build-inputs-receipt"));
        }
        let mut previous: Option<&str> = None;
        let mut input_total = 0_u64;
        let mut output_total = 0_u64;
        for input in &self.inputs {
            validate_package_path(&input.path, limits)?;
            if input.path == BUILD_INPUTS_PATH
                || previous.is_some_and(|path| path >= input.path.as_str())
            {
                return Err(crate::invalid("unordered-build-inputs"));
            }
            previous = Some(&input.path);
            for digest in [&input.input_digest, &input.output_digest] {
                digest
                    .parse::<ArtifactBlobDigest>()
                    .map_err(|_| crate::invalid("invalid-build-input-digest"))?;
            }
            for (size, total) in [
                (input.input_size, &mut input_total),
                (input.output_size, &mut output_total),
            ] {
                if size > limits.max_layer_bytes || (size == 0 && input.role != LayerRole::Asset) {
                    return Err(crate::invalid("invalid-build-input-size"));
                }
                *total = total
                    .checked_add(size)
                    .filter(|value| *value <= limits.max_total_layer_bytes)
                    .ok_or_else(|| crate::exceeded("build-inputs-total-limit"))?;
            }
        }
        Ok(())
    }

    pub(crate) fn encode(&self, limits: PackageLimits) -> Result<Vec<u8>, PlatformError> {
        self.validate(limits)?;
        encode_json(self, limits)
    }
}

pub(crate) fn decode(bytes: &[u8], limits: PackageLimits) -> Result<BuildReceipt, PlatformError> {
    validate_package_json(bytes, limits)?;
    let value: BuildReceipt =
        serde_json::from_slice(bytes).map_err(|_| crate::invalid("invalid-build-inputs-json"))?;
    value.validate(limits)?;
    Ok(value)
}

pub(crate) fn encode_json<T: Serialize>(
    value: &T,
    limits: PackageLimits,
) -> Result<Vec<u8>, PlatformError> {
    limits.validate()?;
    let mut writer = LimitedWriter {
        bytes: Vec::new(),
        maximum: limits.max_document_bytes,
    };
    serde_json::to_writer(&mut writer, value)
        .map_err(|_| crate::exceeded("package-document-limit"))?;
    validate_package_json(&writer.bytes, limits)?;
    Ok(writer.bytes)
}

struct LimitedWriter {
    bytes: Vec<u8>,
    maximum: usize,
}
impl Write for LimitedWriter {
    fn write(&mut self, bytes: &[u8]) -> io::Result<usize> {
        let next = self
            .bytes
            .len()
            .checked_add(bytes.len())
            .filter(|value| *value <= self.maximum)
            .ok_or_else(|| io::Error::other("package document limit"))?;
        if next > self.bytes.capacity() {
            let capacity = next
                .max(self.bytes.capacity().saturating_mul(2))
                .min(self.maximum);
            self.bytes
                .try_reserve_exact(capacity - self.bytes.len())
                .map_err(io::Error::other)?;
        }
        self.bytes.extend_from_slice(bytes);
        Ok(bytes.len())
    }
    fn flush(&mut self) -> io::Result<()> {
        Ok(())
    }
}
