use std::io::{self, Write};
use std::mem::size_of;

use latent_core::{Metadata, PlatformError};
use latent_manifest::{
    __serde::{ser::SerializeSeq, Serialize, Serializer},
    __serde_json as serde_json, CapsuleManifest,
};

use super::super::{resource_exhausted, DirectoryArtifactRepositoryConfig};
use crate::{ArtifactCatalogEntry, ArtifactDescriptor, ArtifactLayer};

/// Byte charges for the encoded descriptor, retained index and materialized page row.
#[derive(Clone, Copy)]
pub(super) struct EntryCost {
    pub(super) descriptor: usize,
    pub(super) retained: usize,
    pub(super) page: usize,
}

/// Exact persisted descriptor encoding without allocating a cloned storage DTO.
#[derive(Serialize)]
#[serde(crate = "latent_manifest::__serde")]
struct Descriptor<'a> {
    reference: &'a str,
    release_digest: &'a str,
    media_type: &'a str,
    size_bytes: u64,
    publisher: Option<&'a str>,
    layers: Layers<'a>,
    annotations: &'a Metadata,
}

#[derive(Serialize)]
#[serde(crate = "latent_manifest::__serde")]
struct Summary<'a> {
    descriptor: Descriptor<'a>,
    tenant: Option<&'a str>,
    service: &'a str,
    semantic_version: &'a str,
    world: &'a str,
}

impl<'a> From<&'a ArtifactDescriptor> for Descriptor<'a> {
    fn from(value: &'a ArtifactDescriptor) -> Self {
        Self {
            reference: &value.reference.0,
            release_digest: &value.release_digest.0,
            media_type: &value.media_type,
            size_bytes: value.size_bytes,
            publisher: value.publisher.as_ref().map(|p| p.0.as_str()),
            layers: Layers(&value.layers),
            annotations: &value.annotations,
        }
    }
}

struct Layers<'a>(&'a [ArtifactLayer]);
impl Serialize for Layers<'_> {
    fn serialize<S: Serializer>(&self, serializer: S) -> Result<S::Ok, S::Error> {
        #[derive(Serialize)]
        #[serde(crate = "latent_manifest::__serde")]
        struct Layer<'a> {
            media_type: &'a str,
            digest: &'a str,
            size_bytes: u64,
            annotations: &'a Metadata,
        }
        let mut seq = serializer.serialize_seq(Some(self.0.len()))?;
        for value in self.0 {
            seq.serialize_element(&Layer {
                media_type: &value.media_type,
                digest: &value.digest,
                size_bytes: value.size_bytes,
                annotations: &value.annotations,
            })?;
        }
        seq.end()
    }
}

struct Counter {
    used: usize,
    maximum: usize,
}
impl Write for Counter {
    fn write(&mut self, bytes: &[u8]) -> io::Result<usize> {
        self.used = self
            .used
            .checked_add(bytes.len())
            .filter(|next| *next <= self.maximum)
            .ok_or_else(|| io::Error::other("bounded encoding"))?;
        Ok(bytes.len())
    }
    fn flush(&mut self) -> io::Result<()> {
        Ok(())
    }
}

pub(in super::super) fn descriptor_bytes(
    value: &ArtifactDescriptor,
    maximum: usize,
) -> Result<usize, PlatformError> {
    let mut counter = Counter { used: 0, maximum };
    serde_json::to_writer(&mut counter, &Descriptor::from(value))
        .map_err(|_| resource_exhausted("artifact descriptor exceeds configured byte limit"))?;
    Ok(counter.used)
}

pub(super) fn measure(
    descriptor: &ArtifactDescriptor,
    manifest: &CapsuleManifest,
    config: DirectoryArtifactRepositoryConfig,
) -> Result<EntryCost, PlatformError> {
    let descriptor_bytes = descriptor_bytes(descriptor, config.max_descriptor_bytes)?;
    let mut retained = Retained {
        used: size_of::<ArtifactCatalogEntry>(),
        maximum: config.max_index_bytes,
    };
    retained.add(
        descriptor
            .layers
            .len()
            .checked_mul(size_of::<ArtifactLayer>()),
    )?;
    for text in [
        &descriptor.reference.0,
        &descriptor.release_digest.0,
        &descriptor.media_type,
    ] {
        retained.string(text)?;
    }
    if let Some(publisher) = &descriptor.publisher {
        retained.string(&publisher.0)?;
    }
    retained.metadata(&descriptor.annotations)?;
    for layer in &descriptor.layers {
        retained.string(&layer.media_type)?;
        retained.string(&layer.digest)?;
        retained.metadata(&layer.annotations)?;
    }
    for text in [
        &manifest.metadata.name,
        &manifest.semantic_version,
        &manifest.world.0,
    ] {
        retained.string(text)?;
    }
    if let Some(tenant) = &manifest.metadata.tenant {
        retained.string(&tenant.0)?;
    }
    // This covers all allocations in the returned owned entry, including sparse maps.
    let materialized_bytes = retained.used;
    retained.add(Some(
        size_of::<Option<crate::PreparationMetadataFingerprint>>(),
    ))?;
    // Seven potentially sparse index nodes plus boxed record and collection bookkeeping.
    // Repeated charging for shared scope keys intentionally overestimates their storage.
    retained.add(Some(8192))?;
    retained.add(Some(descriptor.reference.0.len()))?;
    for _ in 0..4 {
        retained.add(Some(descriptor.release_digest.0.len()))?;
    }
    if let Some(tenant) = &manifest.metadata.tenant {
        retained.add(tenant.0.len().checked_mul(2))?;
        retained.add(Some(manifest.metadata.name.len()))?;
    }
    let mut counter = Counter {
        used: 0,
        maximum: usize::MAX,
    };
    serde_json::to_writer(
        &mut counter,
        &Summary {
            descriptor: Descriptor::from(descriptor),
            tenant: manifest.metadata.tenant.as_ref().map(|t| t.0.as_str()),
            service: &manifest.metadata.name,
            semantic_version: &manifest.semantic_version,
            world: &manifest.world.0,
        },
    )
    .map_err(|_| limit())?;
    let page_bytes = counter
        .used
        .checked_add(materialized_bytes)
        .ok_or_else(limit)?;
    Ok(EntryCost {
        descriptor: descriptor_bytes,
        retained: retained.used,
        page: page_bytes,
    })
}

struct Retained {
    used: usize,
    maximum: usize,
}
impl Retained {
    fn add(&mut self, bytes: Option<usize>) -> Result<(), PlatformError> {
        self.used = bytes
            .and_then(|bytes| self.used.checked_add(bytes))
            .filter(|total| *total <= self.maximum)
            .ok_or_else(limit)?;
        Ok(())
    }
    fn string(&mut self, text: &str) -> Result<(), PlatformError> {
        self.add(Some(text.len()))
    }
    fn metadata(&mut self, value: &Metadata) -> Result<(), PlatformError> {
        // A sparse B-tree node has eleven slots; this charge also covers keys/values.
        self.add(value.len().checked_mul(1024))?;
        for (key, value) in value {
            self.string(key)?;
            self.string(value)?;
        }
        Ok(())
    }
}
fn limit() -> PlatformError {
    resource_exhausted("catalog index byte limit reached")
}
