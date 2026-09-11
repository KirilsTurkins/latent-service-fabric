use std::collections::BTreeMap;

use latent_artifacts::package::{LayerRole, PackageKind, PackageLimits};
use latent_core::PlatformError;
use serde::{Deserialize, Serialize};

use crate::SemanticLimits;

/// Supplied raw bytes. Archives and compression are never expanded implicitly.
#[derive(Debug, Clone)]
pub struct LayerInput {
    pub path: String,
    pub role: LayerRole,
    pub media_type: String,
    pub bytes: Vec<u8>,
}

/// A build packages supplied artifacts; it does not claim to have compiled them.
#[derive(Debug, Clone)]
pub struct PackageInput {
    pub kind: PackageKind,
    pub name: String,
    pub version: String,
    pub entrypoint: String,
    pub annotations: BTreeMap<String, String>,
    pub layers: Vec<LayerInput>,
}

/// One explicitly selected regular file below the caller-approved input root.
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct PackageFile {
    pub path: String,
    pub source: String,
    pub role: LayerRole,
    pub media_type: String,
}

/// Explicit input mapping: no globbing, recursive discovery, or archive extraction.
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct PackageSource {
    pub format_version: u32,
    pub kind: PackageKind,
    pub name: String,
    pub version: String,
    pub entrypoint: String,
    pub annotations: BTreeMap<String, String>,
    pub layers: Vec<PackageFile>,
}

pub(crate) fn check_header(
    name: &str,
    version: &str,
    entrypoint: &str,
    annotations: &BTreeMap<String, String>,
    count: usize,
    limits: PackagingLimits,
) -> Result<(), PlatformError> {
    limits.validate()?;
    if name.len() > 128
        || version.len() > 128
        || entrypoint.len() > limits.package.max_path_bytes
        || annotations.len() > limits.package.max_annotations
        || count == 0
        || count >= limits.package.max_layers
    {
        return Err(crate::exceeded("package-input-metadata-limit"));
    }
    for (key, value) in annotations {
        if key.len() > 128 || value.len() > limits.package.max_string_bytes {
            return Err(crate::exceeded("package-input-metadata-limit"));
        }
    }
    Ok(())
}

#[derive(Debug, Clone, Copy, Default)]
pub struct PackagingLimits {
    pub package: PackageLimits,
    pub semantics: SemanticLimits,
}

impl PackagingLimits {
    pub(crate) fn validate(self) -> Result<(), PlatformError> {
        self.package.validate()?;
        self.semantics.validate()
    }

    pub(crate) fn document_limit(self, role: LayerRole) -> u64 {
        match role {
            LayerRole::CapsuleManifest | LayerRole::Contracts | LayerRole::WitLock => {
                (self.package.max_document_bytes as u64).min(self.package.max_layer_bytes)
            }
            _ => self.package.max_layer_bytes,
        }
    }
}
