use super::{
    artifact_blob_digest, corrupt, exceeded, invalid, package_digest, parse, validate,
    PackageConfig, PackageLayer, PackageLimits, PackageManifest, ReferrerManifest,
    LAYER_PATH_ANNOTATION, LAYER_ROLE_ANNOTATION,
};
use latent_core::{PackageDigest, PlatformError, ReleaseDigest};
use serde::{de::DeserializeOwned, Serialize};
use std::io::{self, Write};

/// A format-checked manifest/config association. Layer bytes, publisher trust,
/// typed WIT semantics and tenant admission are deliberately not established.
#[derive(Debug)]
pub struct PackageLayout {
    digest: PackageDigest,
    manifest: PackageManifest,
    config: PackageConfig,
}
impl PackageLayout {
    #[must_use]
    pub fn digest(&self) -> &PackageDigest {
        &self.digest
    }
    #[must_use]
    pub fn manifest(&self) -> &PackageManifest {
        &self.manifest
    }
    #[must_use]
    pub fn config(&self) -> &PackageConfig {
        &self.config
    }
    /// Only a capsule can yield the existing component-byte release identity.
    /// This is an identity conversion, not proof of verified bytes or admission.
    #[must_use]
    pub fn component_release(&self) -> Option<ReleaseDigest> {
        self.config
            .component_digest
            .as_ref()
            .map(|digest| ReleaseDigest(digest.as_str().to_owned()))
    }
}

/// Accept valid noncanonical JSON while binding identity to its original bytes.
pub fn inspect_package(
    manifest_bytes: &[u8],
    config_bytes: &[u8],
    limits: PackageLimits,
) -> Result<PackageLayout, PlatformError> {
    let manifest = decode_manifest(manifest_bytes, limits)?;
    let config = decode_config(config_bytes, limits)?;
    if manifest.config.digest != artifact_blob_digest(config_bytes)
        || manifest.config.size != config_bytes.len() as u64
    {
        return Err(corrupt("package-config-content-mismatch"));
    }
    if manifest.artifact_type != config.kind.artifact_type()
        || manifest.layers.len() != config.layers.len()
    {
        return Err(invalid("package-config-kind-mismatch"));
    }
    for (descriptor, layer) in manifest.layers.iter().zip(&config.layers) {
        let annotations = descriptor.annotations.as_ref().expect("checked descriptor");
        if descriptor.digest != layer.digest
            || descriptor.media_type != layer.media_type
            || descriptor.size != layer.size
            || annotations[LAYER_PATH_ANNOTATION] != layer.path
            || annotations[LAYER_ROLE_ANNOTATION] != layer.role.as_str()
        {
            return Err(invalid("package-config-layer-mismatch"));
        }
    }
    Ok(PackageLayout {
        digest: package_digest(manifest_bytes),
        manifest,
        config,
    })
}

/// Verify raw layer integrity only; do not execute or deserialize its contents.
pub fn verify_layer_bytes(
    layer: &PackageLayer,
    bytes: &[u8],
    limits: PackageLimits,
) -> Result<(), PlatformError> {
    limits.validate()?;
    validate::layer_fields(
        layer.role,
        &layer.path,
        &layer.media_type,
        layer.size,
        limits,
    )?;
    if bytes.len() as u64 != layer.size || artifact_blob_digest(bytes) != layer.digest {
        return Err(corrupt("package-layer-content-mismatch"));
    }
    Ok(())
}

macro_rules! codec {
    ($decode:ident, $encode:ident, $model:ty, $check:ident) => {
        pub fn $decode(bytes: &[u8], limits: PackageLimits) -> Result<$model, PlatformError> {
            let model: $model = decode(bytes, limits)?;
            validate::$check(&model, limits)?;
            Ok(model)
        }
        /// Deterministic LSF JSON profile: declared struct order, sorted annotation
        /// keys, integer sizes, compact UTF-8 and no trailing newline; not RFC 8785.
        pub fn $encode(model: &$model, limits: PackageLimits) -> Result<Vec<u8>, PlatformError> {
            validate::$check(model, limits)?;
            encode_bounded(model, limits)
        }
    };
}
codec!(decode_config, encode_config, PackageConfig, config);
codec!(decode_manifest, encode_manifest, PackageManifest, manifest);
codec!(decode_referrer, encode_referrer, ReferrerManifest, referrer);

fn decode<T: DeserializeOwned>(bytes: &[u8], limits: PackageLimits) -> Result<T, PlatformError> {
    serde_json::from_value(parse::parse(bytes, limits)?)
        .map_err(|_| invalid("invalid-package-shape"))
}
pub(super) fn encode_bounded<T: Serialize>(
    model: &T,
    limits: PackageLimits,
) -> Result<Vec<u8>, PlatformError> {
    limits.validate()?;
    let mut writer = LimitedWriter {
        bytes: Vec::new(),
        maximum: limits.max_document_bytes,
    };
    serde_json::to_writer(&mut writer, model).map_err(|_| exceeded("package-document-limit"))?;
    // The configured parse structure limits apply equally to public owned inputs.
    drop(parse::parse(&writer.bytes, limits)?);
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
            .filter(|n| *n <= self.maximum)
            .ok_or_else(|| io::Error::other("package document bound"))?;
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
