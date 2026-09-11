//! Bounded, deterministic identity for the metadata retained by preparation.

use std::fmt::{self, Write};

use crate::{ArtifactDescriptor, ContractDescriptor, ValueType};
use latent_core::{Metadata, PlatformError, PlatformErrorCode};
use latent_manifest::CapsuleManifest;
use sha2::{Digest, Sha256};

/// Fixed-size fingerprint of complete preparation metadata and its checked cost.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub struct PreparationMetadataFingerprint {
    digest: [u8; 32],
    charged_bytes: usize,
    required_type_depth: usize,
}

impl PreparationMetadataFingerprint {
    #[must_use]
    pub fn digest(&self) -> &[u8; 32] {
        &self.digest
    }
    #[must_use]
    pub fn charged_bytes(&self) -> usize {
        self.charged_bytes
    }
    #[must_use]
    pub fn required_type_depth(&self) -> usize {
        self.required_type_depth
    }
}

/// The identity is internal to this engine version, never a release digest or
/// persisted format. Derived `Debug` on these owned domain records has fixed field
/// order; metadata maps are ordered. Streaming avoids another metadata buffer.
pub fn preparation_metadata_fingerprint(
    descriptor: &ArtifactDescriptor,
    manifest: &CapsuleManifest,
    contracts: &[ContractDescriptor],
    maximum_bytes: usize,
    maximum_depth: usize,
) -> Result<PreparationMetadataFingerprint, PlatformError> {
    let mut bounds = Bounds {
        remaining: maximum_bytes,
        maximum_depth,
        required_type_depth: 0,
    };
    bounds.descriptor(descriptor)?;
    bounds.manifest(manifest)?;
    bounds.contracts(contracts)?;
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
        descriptor, manifest, contracts
    )
    .map_err(|_| exhausted())?;
    Ok(PreparationMetadataFingerprint {
        digest: writer.hasher.finalize().into(),
        charged_bytes: writer.bytes.max(maximum_bytes - bounds.remaining),
        required_type_depth: bounds.required_type_depth,
    })
}

struct Bounds {
    remaining: usize,
    maximum_depth: usize,
    required_type_depth: usize,
}

impl Bounds {
    fn descriptor(&mut self, descriptor: &ArtifactDescriptor) -> Result<(), PlatformError> {
        self.map(&descriptor.annotations)?;
        self.string(&descriptor.reference.0)?;
        self.string(&descriptor.release_digest.0)?;
        self.string(&descriptor.media_type)?;
        if let Some(publisher) = &descriptor.publisher {
            self.string(&publisher.0)?;
        }
        for layer in &descriptor.layers {
            self.charge(128)?;
            self.string(&layer.media_type)?;
            self.string(&layer.digest)?;
            self.map(&layer.annotations)?;
        }
        Ok(())
    }

    fn manifest(&mut self, manifest: &CapsuleManifest) -> Result<(), PlatformError> {
        // The manifest has fixed type depth, but its strings and collections are
        // untrusted even when prepare is called without a directory repository.
        self.string(&manifest.api_version)?;
        self.string(&manifest.metadata.name)?;
        self.optional(
            manifest
                .metadata
                .tenant
                .as_ref()
                .map(|tenant| tenant.0.as_str()),
        )?;
        self.optional(manifest.metadata.namespace.as_deref())?;
        self.map(&manifest.metadata.labels)?;
        self.map(&manifest.metadata.annotations)?;
        self.string(&manifest.semantic_version)?;
        self.string(&manifest.component_digest.0)?;
        self.string(&manifest.world.0)?;
        self.string(&manifest.minimum_fabric_version)?;
        for export in &manifest.exports {
            self.charge(64)?;
            self.string(&export.contract.0)?;
        }
        for import in &manifest.imports {
            self.charge(64)?;
            self.string(&import.contract.0)?;
        }
        Ok(())
    }

    fn contracts(&mut self, contracts: &[ContractDescriptor]) -> Result<(), PlatformError> {
        for contract in contracts {
            self.charge(128)?;
            for text in [
                &contract.id.0,
                &contract.package_name,
                &contract.semantic_version,
                &contract.digest,
            ] {
                self.string(text)?;
            }
            for dependency in &contract.dependencies {
                self.string(&dependency.0)?;
            }
            for interface in &contract.interfaces {
                self.charge(128)?;
                self.string(&interface.id.0)?;
                self.string(&interface.digest)?;
                self.optional(interface.documentation.as_deref())?;
                for function in &interface.functions {
                    self.charge(128)?;
                    self.string(&function.id.0)?;
                    self.string(&function.name)?;
                    self.optional(function.documentation.as_deref())?;
                    self.map(&function.attributes)?;
                    for field in function.parameters.iter().chain(&function.results) {
                        self.charge(64)?;
                        self.string(&field.name)?;
                        self.optional(field.documentation.as_deref())?;
                        self.value_type(&field.value_type, 0)?;
                    }
                }
            }
        }
        Ok(())
    }
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
        self.required_type_depth = self.required_type_depth.max(depth + 1);
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
    PlatformError {
        code: PlatformErrorCode::ResourceExhausted,
        message: "preparation metadata exceeds its configured bound".to_owned(),
        retryable: false,
        details: Vec::new(),
    }
}
