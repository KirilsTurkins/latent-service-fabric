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
    retained_base: usize,
    pub(super) preparation_stamp: Option<PreparationMetadataFingerprint>,
    pub(super) eligibility: Option<crate::ReleaseEligibility>,
    pub(super) admission_completion: Option<[u8; 32]>,
    pub(super) admission_binding: Option<std::sync::Arc<crate::AdmissionBinding>>,
}

#[derive(Debug)]
pub(super) struct CatalogIndex {
    pub(super) by_digest: BTreeMap<ReleaseDigest, Box<IndexedEntry>>,
    pub(super) by_reference: BTreeMap<ArtifactReference, ReleaseDigest>,
    pending_reservations: BTreeMap<ReleaseDigest, usize>,
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
            pending_reservations: BTreeMap::new(),
            by_tenant: BTreeMap::new(),
            by_service: BTreeMap::new(),
            accounted_bytes: REPOSITORY_ACCOUNTED_BYTES,
            generation: 0,
        }
    }
}

impl CatalogIndex {
    /// Startup-only removal of completed payloads without committed membership.
    /// Keep their conservative capacity charge until reopening/reconciliation.
    pub(super) fn remove_pending(&mut self, release: &ReleaseDigest) {
        let Some(entry) = self.by_digest.remove(release) else {
            return;
        };
        let reserved = entry.retained_base
            + entry
                .admission_binding
                .as_ref()
                .map_or(0, |binding| history_bytes(binding))
            + entry
                .eligibility
                .as_ref()
                .map_or(0, crate::ReleaseEligibility::retained_bytes);
        self.pending_reservations.insert(release.clone(), reserved);
        // Keep the hidden reference reservation: admitting another digest under
        // this reference would make the retained orphan conflict on next reopen.
        // Resolution still returns None because by_digest has no visible row.
        if let Some(tenant) = &entry.value.tenant {
            if let Some(rows) = self.by_tenant.get_mut(tenant) {
                rows.remove(release);
            }
            if let Some(services) = self.by_service.get_mut(tenant) {
                if let Some(rows) = services.get_mut(&entry.value.service) {
                    rows.remove(release);
                }
            }
        }
    }

    /// Only the concrete catalog calls this after verifying the selected durable
    /// evidence revision against the immutable original package and COMPLETE.
    pub(super) fn install_selected_eligibility(
        &mut self,
        release: &ReleaseDigest,
        eligibility: Option<crate::ReleaseEligibility>,
        completion: [u8; 32],
        config: DirectoryArtifactRepositoryConfig,
    ) -> Result<(), PlatformError> {
        let bytes = eligibility
            .as_ref()
            .map_or(0, crate::ReleaseEligibility::retained_bytes);
        self.eligibility_capacity(release, bytes, config)?;
        let entry = self
            .by_digest
            .get_mut(release)
            .ok_or_else(|| corrupt("admission-index-entry-missing"))?;
        let original = entry
            .admission_binding
            .as_ref()
            .ok_or_else(|| corrupt("admission-index-history-missing"))?;
        if entry.admission_completion != Some(completion)
            || eligibility.as_ref().is_some_and(|proof| {
                proof.release() != release
                    || proof.binding().tenant != original.tenant
                    || proof.binding().package != original.package
            })
        {
            return Err(corrupt("renewed-admission-index-association"));
        }
        let previous = entry
            .eligibility
            .as_ref()
            .map_or(0, crate::ReleaseEligibility::retained_bytes);
        self.accounted_bytes = self.accounted_bytes - previous + bytes;
        entry.eligibility = eligibility;
        Ok(())
    }

    pub(super) fn preflight_admission(
        &self,
        descriptor: &ArtifactDescriptor,
        manifest: &CapsuleManifest,
        binding: &crate::AdmissionBinding,
        completion: [u8; 32],
        eligibility_bytes: usize,
        config: DirectoryArtifactRepositoryConfig,
    ) -> Result<(), PlatformError> {
        self.preflight(descriptor, manifest, config)?;
        let old = self.by_digest.get(&descriptor.release_digest);
        if old.is_some_and(|entry| {
            entry
                .admission_binding
                .as_ref()
                .is_some_and(|value| value.as_ref() != binding)
                || entry
                    .admission_completion
                    .is_some_and(|value| value != completion)
        }) {
            return Err(corrupt("admission-history-changed"));
        }
        let base = if old.is_none() {
            sizing::measure(descriptor, manifest, config)?.retained
        } else {
            0
        };
        let history = if old.is_none_or(|entry| entry.admission_binding.is_none()) {
            history_bytes(binding)
        } else {
            0
        };
        let previous = old
            .and_then(|entry| entry.eligibility.as_ref())
            .map_or(0, crate::ReleaseEligibility::retained_bytes);
        if self
            .accounted_bytes
            .checked_sub(
                self.pending_reservations
                    .get(&descriptor.release_digest)
                    .copied()
                    .unwrap_or(0),
            )
            .and_then(|used| used.checked_sub(previous))
            .and_then(|used| used.checked_add(base))
            .and_then(|used| used.checked_add(history))
            .and_then(|used| used.checked_add(eligibility_bytes))
            .is_none_or(|used| used > config.max_index_bytes)
        {
            return Err(resource_exhausted("admission-index-byte-limit"));
        }
        Ok(())
    }

    pub(super) fn insert_admitted(
        &mut self,
        metadata: VerifiedArtifactMetadata,
        stamp: Option<PreparationMetadataFingerprint>,
        binding: crate::AdmissionBinding,
        eligibility: Option<crate::ReleaseEligibility>,
        completion: [u8; 32],
        config: DirectoryArtifactRepositoryConfig,
    ) -> Result<(), PlatformError> {
        self.preflight_admission(
            metadata.descriptor(),
            metadata.manifest(),
            &binding,
            completion,
            eligibility
                .as_ref()
                .map_or(0, crate::ReleaseEligibility::retained_bytes),
            config,
        )?;
        let release = metadata.verified_digest().clone();
        self.insert_verified(metadata, stamp, config)?;
        self.install_history(&release, binding, completion, config)?;
        if let Some(eligibility) = eligibility {
            self.install_eligibility(&release, eligibility, completion, config)?;
        }
        Ok(())
    }

    pub(super) fn install_history(
        &mut self,
        release: &ReleaseDigest,
        binding: crate::AdmissionBinding,
        completion: [u8; 32],
        config: DirectoryArtifactRepositoryConfig,
    ) -> Result<(), PlatformError> {
        let entry = self
            .by_digest
            .get(release)
            .ok_or_else(|| corrupt("admission-index-entry-missing"))?;
        if entry
            .admission_completion
            .is_some_and(|old| old != completion)
        {
            return Err(corrupt("admission-history-changed"));
        }
        let old = entry.admission_binding.as_ref();
        if old.is_some_and(|old| old.as_ref() != &binding) {
            return Err(corrupt("admission-history-changed"));
        }
        if old.is_some() {
            return Ok(());
        }
        if old.is_none() {
            let charge = history_bytes(&binding);
            if self
                .accounted_bytes
                .checked_add(charge)
                .is_none_or(|used| used > config.max_index_bytes)
            {
                return Err(resource_exhausted("admission-history-byte-limit"));
            }
            self.accounted_bytes += charge;
        }
        let entry = self
            .by_digest
            .get_mut(release)
            .ok_or_else(|| corrupt("admission-index-entry-missing"))?;
        entry.admission_binding = Some(std::sync::Arc::new(binding));
        entry.admission_completion = Some(completion);
        Ok(())
    }
    pub(super) fn eligibility_capacity(
        &self,
        release: &ReleaseDigest,
        bytes: usize,
        config: DirectoryArtifactRepositoryConfig,
    ) -> Result<(), PlatformError> {
        let old = self
            .by_digest
            .get(release)
            .and_then(|entry| entry.eligibility.as_ref())
            .map_or(0, crate::ReleaseEligibility::retained_bytes);
        if self
            .accounted_bytes
            .checked_sub(old)
            .and_then(|used| used.checked_add(bytes))
            .is_none_or(|used| used > config.max_index_bytes)
        {
            return Err(resource_exhausted("admission-index-byte-limit"));
        }
        Ok(())
    }

    pub(super) fn install_eligibility(
        &mut self,
        release: &ReleaseDigest,
        eligibility: crate::ReleaseEligibility,
        completion: [u8; 32],
        config: DirectoryArtifactRepositoryConfig,
    ) -> Result<(), PlatformError> {
        self.eligibility_capacity(release, eligibility.retained_bytes(), config)?;
        let entry = self
            .by_digest
            .get_mut(release)
            .ok_or_else(|| corrupt("admission-index-entry-missing"))?;
        if entry
            .admission_completion
            .is_some_and(|old| old != completion)
            || entry
                .admission_binding
                .as_ref()
                .is_some_and(|old| old.as_ref() != eligibility.binding())
        {
            return Err(corrupt("admission-index-association-changed"));
        }
        let old = entry
            .eligibility
            .as_ref()
            .map_or(0, crate::ReleaseEligibility::retained_bytes);
        self.accounted_bytes = self.accounted_bytes - old + eligibility.retained_bytes();
        entry.eligibility = Some(eligibility);
        entry.admission_completion = Some(completion);
        Ok(())
    }
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
        self.check_capacity(&descriptor.release_digest, cost.retained, config)
    }

    fn check_capacity(
        &self,
        release: &ReleaseDigest,
        additional: usize,
        config: DirectoryArtifactRepositoryConfig,
    ) -> Result<(), PlatformError> {
        if !self.pending_reservations.contains_key(release)
            && self.by_digest.len() + self.pending_reservations.len() >= config.max_index_entries
        {
            return Err(resource_exhausted("catalog index entry limit reached"));
        }
        if self
            .accounted_bytes
            .checked_sub(self.pending_reservations.get(release).copied().unwrap_or(0))
            .and_then(|used| used.checked_add(additional))
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
    #[cfg(test)]
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
        if let Some(reserved) = self
            .pending_reservations
            .remove(&value.descriptor.release_digest)
        {
            self.accounted_bytes -= reserved;
        }
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
                retained_base: cost.retained,
                preparation_stamp: stamp,
                eligibility: None,
                admission_completion: None,
                admission_binding: None,
            }),
        );
        self.accounted_bytes += cost.retained;
        self.generation += 1;
    }
}

pub(super) fn history_bytes(binding: &crate::AdmissionBinding) -> usize {
    std::mem::size_of::<crate::AdmissionBinding>()
        .saturating_add(64)
        .saturating_add(binding.tenant.0.capacity())
        .saturating_add(binding.package.as_str().len())
        .saturating_add(binding.release.0.capacity())
        .saturating_add(binding.receipt.capacity())
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
