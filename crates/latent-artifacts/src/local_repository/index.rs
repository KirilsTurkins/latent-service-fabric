//! One atomic immutable metadata index, including bounded scoped selection paths.

mod sizing;
pub(super) use sizing::descriptor_bytes;

use std::collections::{BTreeMap, BTreeSet};

use latent_core::{ArtifactReference, ReleaseDigest, ServiceId, TenantId};
use latent_manifest::CapsuleManifest;

use super::{
    corrupt, error, resource_exhausted, DirectoryArtifactRepositoryConfig, PlatformError,
    PlatformErrorCode,
};
use crate::{
    ArtifactCatalogEntry, ArtifactDescriptor, CapsuleArtifact, PreparationMetadataFingerprint,
    VerifiedArtifactMetadata,
};

pub(super) const REPOSITORY_ACCOUNTED_BYTES: usize = crate::preparation::EPOCH_RETAINED_BYTES
    + std::mem::size_of::<crate::verification_statistics::VerificationStatistics>();

pub(super) type Rows = BTreeSet<ReleaseDigest>;

#[derive(Debug)]
pub(super) struct IndexedEntry {
    pub(super) value: ArtifactCatalogEntry,
    pub(super) descriptor_bytes: usize,
    pub(super) page_bytes: usize,
    pub(super) preparation_stamp: Option<PreparationMetadataFingerprint>,
}

#[derive(Debug)]
pub(super) struct CatalogIndex {
    pub(super) by_digest: BTreeMap<ReleaseDigest, Box<IndexedEntry>>,
    pub(super) by_reference: BTreeMap<ArtifactReference, ReleaseDigest>,
    by_tenant: BTreeMap<TenantId, Rows>,
    by_service: BTreeMap<TenantId, BTreeMap<ServiceId, Rows>>,
    pub(super) accounted_bytes: usize,
    pub(super) generation: u64,
}

impl Default for CatalogIndex {
    fn default() -> Self {
        Self {
            by_digest: BTreeMap::new(),
            by_reference: BTreeMap::new(),
            by_tenant: BTreeMap::new(),
            by_service: BTreeMap::new(),
            accounted_bytes: REPOSITORY_ACCOUNTED_BYTES,
            generation: 0,
        }
    }
}

impl CatalogIndex {
    pub(super) fn rows(&self, tenant: &TenantId, service: Option<&ServiceId>) -> Option<&Rows> {
        match service {
            Some(service) => self.by_service.get(tenant)?.get(service),
            None => self.by_tenant.get(tenant),
        }
    }

    pub(super) fn preflight(
        &self,
        descriptor: &ArtifactDescriptor,
        manifest: &CapsuleManifest,
        config: DirectoryArtifactRepositoryConfig,
    ) -> Result<(), PlatformError> {
        let cost = sizing::measure(descriptor, manifest, config)?;
        if let Some(existing) = self.by_digest.get(&descriptor.release_digest) {
            let value = &existing.value;
            if value.descriptor == *descriptor
                && value.tenant == manifest.metadata.tenant
                && value.service.0 == manifest.metadata.name
                && value.semantic_version == manifest.semantic_version
                && value.world == manifest.world
            {
                return Ok(());
            }
            return Err(error(
                PlatformErrorCode::AlreadyExists,
                "release digest already indexes different catalog metadata",
            ));
        }
        if self
            .by_reference
            .get(&descriptor.reference)
            .is_some_and(|existing| existing != &descriptor.release_digest)
        {
            return Err(error(
                PlatformErrorCode::AlreadyExists,
                "artifact reference already resolves to another release",
            ));
        }
        self.check_capacity(cost.retained, config)
    }

    fn check_capacity(
        &self,
        additional: usize,
        config: DirectoryArtifactRepositoryConfig,
    ) -> Result<(), PlatformError> {
        if self.by_digest.len() >= config.max_index_entries {
            return Err(resource_exhausted("catalog index entry limit reached"));
        }
        if self
            .accounted_bytes
            .checked_add(additional)
            .is_none_or(|next| next > config.max_index_bytes)
        {
            return Err(resource_exhausted("catalog index byte limit reached"));
        }
        if self.generation == u64::MAX {
            return Err(resource_exhausted("artifact-catalog-generation-exhausted"));
        }
        Ok(())
    }

    /// Moves only compact metadata after checking all allocations for every index.
    pub(super) fn insert(
        &mut self,
        artifact: CapsuleArtifact,
        stamp: Option<PreparationMetadataFingerprint>,
        config: DirectoryArtifactRepositoryConfig,
    ) -> Result<ArtifactDescriptor, PlatformError> {
        let CapsuleArtifact {
            descriptor,
            manifest,
            ..
        } = artifact;
        self.insert_parts(descriptor, manifest, stamp, config)
    }

    pub(super) fn insert_verified(
        &mut self,
        metadata: VerifiedArtifactMetadata,
        stamp: Option<PreparationMetadataFingerprint>,
        config: DirectoryArtifactRepositoryConfig,
    ) -> Result<ArtifactDescriptor, PlatformError> {
        let (descriptor, manifest, contracts) = metadata.into_parts();
        drop(contracts);
        self.insert_parts(descriptor, manifest, stamp, config)
    }

    fn insert_parts(
        &mut self,
        descriptor: ArtifactDescriptor,
        manifest: CapsuleManifest,
        stamp: Option<PreparationMetadataFingerprint>,
        config: DirectoryArtifactRepositoryConfig,
    ) -> Result<ArtifactDescriptor, PlatformError> {
        let cost = sizing::measure(&descriptor, &manifest, config)?;
        self.preflight(&descriptor, &manifest, config)
            .map_err(|failure| {
                if failure.code == PlatformErrorCode::AlreadyExists {
                    corrupt("duplicate release digest or reference has conflicting metadata")
                } else {
                    failure
                }
            })?;
        if let Some(existing) = self.by_digest.get(&descriptor.release_digest) {
            if existing.preparation_stamp != stamp {
                return Err(corrupt(
                    "verified preparation metadata changed after adoption",
                ));
            }
            return Ok(descriptor);
        }
        let mut value = ArtifactCatalogEntry {
            descriptor,
            tenant: manifest.metadata.tenant,
            service: ServiceId(manifest.metadata.name),
            semantic_version: manifest.semantic_version,
            world: manifest.world,
        };
        compact(&mut value);
        let receipt = value.descriptor.clone();
        self.install(value, stamp, cost);
        Ok(receipt)
    }

    fn install(
        &mut self,
        value: ArtifactCatalogEntry,
        stamp: Option<PreparationMetadataFingerprint>,
        cost: sizing::EntryCost,
    ) {
        let descriptor = &value.descriptor;
        if let Some(tenant) = &value.tenant {
            self.by_tenant
                .entry(tenant.clone())
                .or_default()
                .insert(descriptor.release_digest.clone());
            self.by_service
                .entry(tenant.clone())
                .or_default()
                .entry(value.service.clone())
                .or_default()
                .insert(descriptor.release_digest.clone());
        }
        self.by_reference.insert(
            descriptor.reference.clone(),
            descriptor.release_digest.clone(),
        );
        self.by_digest.insert(
            descriptor.release_digest.clone(),
            Box::new(IndexedEntry {
                value,
                descriptor_bytes: cost.descriptor,
                page_bytes: cost.page,
                preparation_stamp: stamp,
            }),
        );
        self.accounted_bytes += cost.retained;
        self.generation += 1;
    }
}

// Box round-trips give exact observable capacity, including caller spare capacity.
// Measurement uses lengths because every moved indexed collection is compacted here.
fn compact(value: &mut ArtifactCatalogEntry) {
    fn string(value: &mut String) {
        *value = std::mem::take(value).into_boxed_str().into_string();
    }
    fn metadata(value: &mut latent_core::Metadata) {
        // Keys cannot be mutated in place, so rebuild them after the checked charge.
        *value = std::mem::take(value)
            .into_iter()
            .map(|(mut key, mut value)| {
                string(&mut key);
                string(&mut value);
                (key, value)
            })
            .collect();
    }
    let descriptor = &mut value.descriptor;
    for value in [
        &mut descriptor.reference.0,
        &mut descriptor.release_digest.0,
        &mut descriptor.media_type,
    ] {
        string(value);
    }
    if let Some(publisher) = &mut descriptor.publisher {
        string(&mut publisher.0);
    }
    descriptor.layers = std::mem::take(&mut descriptor.layers)
        .into_boxed_slice()
        .into_vec();
    metadata(&mut descriptor.annotations);
    for layer in &mut descriptor.layers {
        string(&mut layer.media_type);
        string(&mut layer.digest);
        metadata(&mut layer.annotations);
    }
    if let Some(tenant) = &mut value.tenant {
        string(&mut tenant.0);
    }
    for value in [
        &mut value.service.0,
        &mut value.semantic_version,
        &mut value.world.0,
    ] {
        string(value);
    }
}

#[cfg(test)]
pub(super) fn entry_cost(
    artifact: &CapsuleArtifact,
    config: DirectoryArtifactRepositoryConfig,
) -> usize {
    sizing::measure(&artifact.descriptor, &artifact.manifest, config)
        .expect("fixture entry fits")
        .retained
}
