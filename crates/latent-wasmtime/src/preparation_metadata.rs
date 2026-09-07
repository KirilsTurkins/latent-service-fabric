//! Bounded, deterministic identity for the metadata retained by preparation.

use std::fmt::{self, Write};

use latent_artifacts::{CapsuleArtifact, ValueType};
use latent_core::{Metadata, PlatformError, PlatformErrorCode};
use sha2::{Digest, Sha256};

use crate::containment::platform_error;

pub(crate) struct MetadataIdentity {
    pub digest: String,
    pub bytes: usize,
}

/// The identity is internal to this engine version, never a release digest or
/// persisted format. Derived Debug on these owned domain records has fixed field
/// order; metadata maps are ordered. Streaming avoids another metadata buffer.
pub(crate) fn identity(
    artifact: &CapsuleArtifact,
    maximum_bytes: usize,
    maximum_depth: usize,
) -> Result<MetadataIdentity, PlatformError> {
    let mut bounds = Bounds {
        remaining: maximum_bytes,
        maximum_depth,
    };
    bounds.map(&artifact.descriptor.annotations)?;
    bounds.string(&artifact.descriptor.reference.0)?;
    bounds.string(&artifact.descriptor.release_digest.0)?;
    bounds.string(&artifact.descriptor.media_type)?;
    if let Some(publisher) = &artifact.descriptor.publisher {
        bounds.string(&publisher.0)?;
    }
    for layer in &artifact.descriptor.layers {
        bounds.charge(128)?;
        bounds.string(&layer.media_type)?;
        bounds.string(&layer.digest)?;
        bounds.map(&layer.annotations)?;
    }
    // The manifest has fixed type depth, but its strings and collections are
    // untrusted even when prepare is called without a directory repository.
    let manifest = &artifact.manifest;
    bounds.string(&manifest.api_version)?;
    bounds.string(&manifest.metadata.name)?;
    bounds.optional(
        manifest
            .metadata
            .tenant
            .as_ref()
            .map(|tenant| tenant.0.as_str()),
    )?;
    bounds.optional(manifest.metadata.namespace.as_deref())?;
    bounds.map(&manifest.metadata.labels)?;
    bounds.map(&manifest.metadata.annotations)?;
    bounds.string(&manifest.semantic_version)?;
    bounds.string(&manifest.component_digest.0)?;
    bounds.string(&manifest.world.0)?;
    bounds.string(&manifest.minimum_fabric_version)?;
    for export in &manifest.exports {
        bounds.charge(64)?;
        bounds.string(&export.contract.0)?;
    }
    for import in &manifest.imports {
        bounds.charge(64)?;
        bounds.string(&import.contract.0)?;
    }
    for contract in &artifact.contracts {
        bounds.charge(128)?;
        for text in [
            &contract.id.0,
            &contract.package_name,
            &contract.semantic_version,
            &contract.digest,
        ] {
            bounds.string(text)?;
        }
        for dependency in &contract.dependencies {
            bounds.string(&dependency.0)?;
        }
        for interface in &contract.interfaces {
            bounds.charge(128)?;
            bounds.string(&interface.id.0)?;
            bounds.string(&interface.digest)?;
            bounds.optional(interface.documentation.as_deref())?;
            for function in &interface.functions {
                bounds.charge(128)?;
                bounds.string(&function.id.0)?;
                bounds.string(&function.name)?;
                bounds.optional(function.documentation.as_deref())?;
                bounds.map(&function.attributes)?;
                for field in function.parameters.iter().chain(&function.results) {
                    bounds.charge(64)?;
                    bounds.string(&field.name)?;
                    bounds.optional(field.documentation.as_deref())?;
                    bounds.value_type(&field.value_type, 0)?;
                }
            }
        }
    }
    let mut writer = Fingerprint {
        hasher: Sha256::new(),
        maximum_bytes,
        bytes: 0,
    };
    writer
        .hasher
        .update(b"lsf-wasmtime-preparation-metadata-v1\0");
    write!(
        &mut writer,
        "{:?}\n{:?}\n{:?}",
        artifact.descriptor, manifest, artifact.contracts
    )
    .map_err(|_| exhausted())?;
    Ok(MetadataIdentity {
        digest: format!("{:x}", writer.hasher.finalize()),
        bytes: writer.bytes.max(maximum_bytes - bounds.remaining),
    })
}

struct Bounds {
    remaining: usize,
    maximum_depth: usize,
}

impl Bounds {
    fn charge(&mut self, bytes: usize) -> Result<(), PlatformError> {
        self.remaining = self.remaining.checked_sub(bytes).ok_or_else(exhausted)?;
        Ok(())
    }

    fn string(&mut self, value: &str) -> Result<(), PlatformError> {
        self.charge(value.len().checked_add(32).ok_or_else(exhausted)?)
    }

    fn optional(&mut self, value: Option<&str>) -> Result<(), PlatformError> {
        value.map_or(Ok(()), |value| self.string(value))
    }

    fn map(&mut self, values: &Metadata) -> Result<(), PlatformError> {
        for (key, value) in values {
            self.string(key)?;
            self.string(value)?;
        }
        Ok(())
    }

    fn value_type(&mut self, value: &ValueType, depth: usize) -> Result<(), PlatformError> {
        if depth >= self.maximum_depth {
            return Err(exhausted());
        }
        self.charge(64)?;
        match value {
            ValueType::List(inner)
            | ValueType::Option(inner)
            | ValueType::Future(inner)
            | ValueType::Stream(inner) => self.value_type(inner, depth + 1),
            ValueType::Result { ok, error } => {
                for inner in ok.iter().chain(error.iter()) {
                    self.value_type(inner, depth + 1)?;
                }
                Ok(())
            }
            ValueType::Tuple(fields) => {
                for field in fields {
                    self.value_type(field, depth + 1)?;
                }
                Ok(())
            }
            ValueType::Record(name) | ValueType::Variant(name) | ValueType::Resource(name) => {
                self.string(name)
            }
            _ => Ok(()),
        }
    }
}

struct Fingerprint {
    hasher: Sha256,
    maximum_bytes: usize,
    bytes: usize,
}

impl Write for Fingerprint {
    fn write_str(&mut self, value: &str) -> fmt::Result {
        let next = self.bytes.checked_add(value.len()).ok_or(fmt::Error)?;
        if next > self.maximum_bytes {
            return Err(fmt::Error);
        }
        self.bytes = next;
        self.hasher.update(value.as_bytes());
        Ok(())
    }
}

fn exhausted() -> PlatformError {
    platform_error(
        PlatformErrorCode::ResourceExhausted,
        "preparation metadata exceeds its configured bound",
        false,
    )
}
