//! Atomic publication metadata and bounded component/reference lookup indexes.

mod sizing;
use super::{
    corrupt, error, resource_exhausted, DirectoryArtifactRepositoryConfig, PlatformError,
    PlatformErrorCode,
};
#[cfg(test)]
use crate::CapsuleArtifact;
use crate::{
    ArtifactCatalogEntry, ArtifactDescriptor, LifecycleScope, PreparationMetadataFingerprint,
    PublicationRef, VerifiedArtifactMetadata,
};
use latent_core::{ArtifactReference, PublicationId, ReleaseDigest, ServiceId, TenantId};
use latent_manifest::CapsuleManifest;
pub(super) use sizing::descriptor_bytes;
use std::collections::{BTreeMap, BTreeSet};

pub(super) const REPOSITORY_ACCOUNTED_BYTES: usize = crate::preparation::EPOCH_RETAINED_BYTES
    + std::mem::size_of::<crate::verification_statistics::VerificationStatistics>();
pub(super) type Rows = BTreeSet<PublicationId>;

#[derive(Debug)]
pub(super) struct IndexedEntry {
    pub(super) publication: PublicationRef,
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
    pub(super) by_publication: BTreeMap<PublicationId, Box<IndexedEntry>>,
    by_component: BTreeMap<ReleaseDigest, Rows>,
    by_scoped_component: BTreeMap<(LifecycleScope, ReleaseDigest), Rows>,
    by_reference: BTreeMap<ArtifactReference, Rows>,
    by_scoped_reference: BTreeMap<(LifecycleScope, ArtifactReference), Rows>,
    pending_reservations: BTreeMap<PublicationId, usize>,
    by_tenant: BTreeMap<TenantId, Rows>,
    by_service: BTreeMap<TenantId, BTreeMap<ServiceId, Rows>>,
    pub(super) accounted_bytes: usize,
    pub(super) generation: u64,
}

impl Default for CatalogIndex {
    fn default() -> Self {
        Self {
            by_publication: BTreeMap::new(),
            by_component: BTreeMap::new(),
            by_scoped_component: BTreeMap::new(),
            by_reference: BTreeMap::new(),
            by_scoped_reference: BTreeMap::new(),
            pending_reservations: BTreeMap::new(),
            by_tenant: BTreeMap::new(),
            by_service: BTreeMap::new(),
            accounted_bytes: REPOSITORY_ACCOUNTED_BYTES,
            generation: 0,
        }
    }
}

fn remove_row<K: Ord>(map: &mut BTreeMap<K, Rows>, key: &K, id: &PublicationId) {
    if let Some(rows) = map.get_mut(key) {
        rows.remove(id);
        if rows.is_empty() {
            map.remove(key);
        }
    }
}

fn unique(rows: Option<&Rows>) -> Result<Option<&PublicationId>, PlatformError> {
    match rows {
        None => Ok(None),
        Some(rows) if rows.len() <= 1 => Ok(rows.first()),
        Some(_) => Err(crate::publication::ambiguous()),
    }
}

impl CatalogIndex {
    pub(super) fn pending_ids(&self, maximum: usize) -> Vec<PublicationId> {
        self.pending_reservations
            .keys()
            .take(maximum)
            .cloned()
            .collect()
    }
    pub(super) fn forget_pending(&mut self, id: &PublicationId) -> Result<(), PlatformError> {
        let bytes = self
            .pending_reservations
            .remove(id)
            .ok_or_else(|| corrupt("pending-publication-missing"))?;
        self.accounted_bytes = self
            .accounted_bytes
            .checked_sub(bytes)
            .ok_or_else(|| corrupt("publication-index-accounting"))?;
        Ok(())
    }
    pub(super) fn legacy_component(
        &self,
        scope: Option<&LifecycleScope>,
        component: &ReleaseDigest,
    ) -> Result<Option<&IndexedEntry>, PlatformError> {
        crate::publication::validate_component(component)?;
        let rows = match scope {
            Some(scope) => self
                .by_scoped_component
                .get(&(scope.clone(), component.clone())),
            None => self.by_component.get(component),
        };
        Ok(unique(rows)?.and_then(|id| self.by_publication.get(id).map(Box::as_ref)))
    }
    pub(super) fn legacy_reference(
        &self,
        scope: Option<&LifecycleScope>,
        reference: &ArtifactReference,
    ) -> Result<Option<&IndexedEntry>, PlatformError> {
        let rows = match scope {
            Some(scope) => self
                .by_scoped_reference
                .get(&(scope.clone(), reference.clone())),
            None => self.by_reference.get(reference),
        };
        Ok(unique(rows)?.and_then(|id| self.by_publication.get(id).map(Box::as_ref)))
    }
    pub(super) fn exact(
        &self,
        reference: &PublicationRef,
    ) -> Result<Option<&IndexedEntry>, PlatformError> {
        reference.scope.validate()?;
        Ok(self
            .by_publication
            .get(&reference.id)
            .filter(|e| e.publication.scope == reference.scope)
            .map(Box::as_ref))
    }
    pub(super) fn component_rows(&self) -> &BTreeMap<ReleaseDigest, Rows> {
        &self.by_component
    }

    pub(super) fn remove_pending(&mut self, id: &PublicationId) {
        let Some(entry) = self.by_publication.remove(id) else {
            return;
        };
        let reserved = entry.retained_base
            + entry
                .admission_binding
                .as_ref()
                .map_or(0, |b| history_bytes(b))
            + entry
                .eligibility
                .as_ref()
                .map_or(0, crate::ReleaseEligibility::retained_bytes);
        self.pending_reservations.insert(id.clone(), reserved);
        let scope = &entry.publication.scope;
        let descriptor = &entry.value.descriptor;
        remove_row(&mut self.by_component, &descriptor.release_digest, id);
        remove_row(
            &mut self.by_scoped_component,
            &(scope.clone(), descriptor.release_digest.clone()),
            id,
        );
        remove_row(&mut self.by_reference, &descriptor.reference, id);
        remove_row(
            &mut self.by_scoped_reference,
            &(scope.clone(), descriptor.reference.clone()),
            id,
        );
        if let Some(tenant) = &entry.value.tenant {
            remove_row(&mut self.by_tenant, tenant, id);
            if let Some(services) = self.by_service.get_mut(tenant) {
                remove_row(services, &entry.value.service, id);
                if services.is_empty() {
                    self.by_service.remove(tenant);
                }
            }
        }
    }

    pub(super) fn rows(&self, tenant: &TenantId, service: Option<&ServiceId>) -> Option<&Rows> {
        match service {
            Some(service) => self.by_service.get(tenant)?.get(service),
            None => self.by_tenant.get(tenant),
        }
    }

    pub(super) fn preflight(
        &self,
        publication: &PublicationRef,
        descriptor: &ArtifactDescriptor,
        manifest: &CapsuleManifest,
        config: DirectoryArtifactRepositoryConfig,
    ) -> Result<(), PlatformError> {
        publication.scope.validate()?;
        if manifest
            .metadata
            .tenant
            .as_ref()
            .is_some_and(|tenant| Some(tenant) != publication.scope.tenant())
        {
            return Err(corrupt("publication-embedded-tenant-mismatch"));
        }
        let cost = sizing::measure(descriptor, manifest, publication.scope.tenant(), config)?;
        if let Some(existing) = self.by_publication.get(&publication.id) {
            let value = &existing.value;
            if existing.publication == *publication
                && value.descriptor == *descriptor
                && value.tenant.as_ref() == publication.scope.tenant()
                && value.service.0 == manifest.metadata.name
                && value.semantic_version == manifest.semantic_version
                && value.world == manifest.world
            {
                return Ok(());
            }
            return Err(error(
                PlatformErrorCode::AlreadyExists,
                "publication already indexes different immutable metadata",
            ));
        }
        self.check_capacity(&publication.id, cost.retained, config)
    }

    fn check_capacity(
        &self,
        id: &PublicationId,
        additional: usize,
        config: DirectoryArtifactRepositoryConfig,
    ) -> Result<(), PlatformError> {
        if !self.pending_reservations.contains_key(id)
            && self.by_publication.len() + self.pending_reservations.len()
                >= config.max_index_entries
        {
            return Err(resource_exhausted("catalog index entry limit reached"));
        }
        if self
            .accounted_bytes
            .checked_sub(self.pending_reservations.get(id).copied().unwrap_or(0))
            .and_then(|used| used.checked_add(additional))
            .is_none_or(|used| used > config.max_index_bytes)
        {
            return Err(resource_exhausted("catalog index byte limit reached"));
        }
        if self.generation == u64::MAX {
            return Err(resource_exhausted("artifact-catalog-generation-exhausted"));
        }
        Ok(())
    }

    #[cfg(test)]
    pub(super) fn insert(
        &mut self,
        publication: PublicationRef,
        artifact: CapsuleArtifact,
        stamp: Option<PreparationMetadataFingerprint>,
        config: DirectoryArtifactRepositoryConfig,
    ) -> Result<ArtifactDescriptor, PlatformError> {
        self.insert_parts(
            publication,
            artifact.descriptor,
            artifact.manifest,
            stamp,
            config,
        )
    }
    pub(super) fn insert_verified(
        &mut self,
        publication: PublicationRef,
        metadata: VerifiedArtifactMetadata,
        stamp: Option<PreparationMetadataFingerprint>,
        config: DirectoryArtifactRepositoryConfig,
    ) -> Result<ArtifactDescriptor, PlatformError> {
        let (descriptor, manifest, _) = metadata.into_parts();
        self.insert_parts(publication, descriptor, manifest, stamp, config)
    }
    fn insert_parts(
        &mut self,
        publication: PublicationRef,
        descriptor: ArtifactDescriptor,
        manifest: CapsuleManifest,
        stamp: Option<PreparationMetadataFingerprint>,
        config: DirectoryArtifactRepositoryConfig,
    ) -> Result<ArtifactDescriptor, PlatformError> {
        self.preflight(&publication, &descriptor, &manifest, config)?;
        if let Some(existing) = self.by_publication.get(&publication.id) {
            if existing.preparation_stamp != stamp {
                return Err(corrupt(
                    "verified preparation metadata changed after adoption",
                ));
            }
            return Ok(descriptor);
        }
        let cost = sizing::measure(&descriptor, &manifest, publication.scope.tenant(), config)?;
        let mut value = ArtifactCatalogEntry {
            publication: Some(publication.id.clone()),
            package: None,
            descriptor,
            tenant: publication.scope.tenant().cloned(),
            service: ServiceId(manifest.metadata.name),
            semantic_version: manifest.semantic_version,
            world: manifest.world,
        };
        compact(&mut value);
        let receipt = value.descriptor.clone();
        if let Some(reserved) = self.pending_reservations.remove(&publication.id) {
            self.accounted_bytes -= reserved;
        }
        let id = &publication.id;
        let scope = &publication.scope;
        let descriptor = &value.descriptor;
        self.by_component
            .entry(descriptor.release_digest.clone())
            .or_default()
            .insert(id.clone());
        self.by_scoped_component
            .entry((scope.clone(), descriptor.release_digest.clone()))
            .or_default()
            .insert(id.clone());
        self.by_reference
            .entry(descriptor.reference.clone())
            .or_default()
            .insert(id.clone());
        self.by_scoped_reference
            .entry((scope.clone(), descriptor.reference.clone()))
            .or_default()
            .insert(id.clone());
        if let Some(tenant) = &value.tenant {
            self.by_tenant
                .entry(tenant.clone())
                .or_default()
                .insert(id.clone());
            self.by_service
                .entry(tenant.clone())
                .or_default()
                .entry(value.service.clone())
                .or_default()
                .insert(id.clone());
        }
        self.by_publication.insert(
            id.clone(),
            Box::new(IndexedEntry {
                publication,
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
        Ok(receipt)
    }

    #[allow(clippy::too_many_arguments)]
    pub(super) fn preflight_admission(
        &self,
        publication: &PublicationRef,
        descriptor: &ArtifactDescriptor,
        manifest: &CapsuleManifest,
        binding: &crate::AdmissionBinding,
        completion: [u8; 32],
        eligibility_bytes: usize,
        config: DirectoryArtifactRepositoryConfig,
    ) -> Result<(), PlatformError> {
        if PublicationRef::package(
            LifecycleScope::Tenant(binding.tenant.clone()),
            &binding.package,
        )? != *publication
            || binding.release != descriptor.release_digest
        {
            return Err(corrupt("admission-publication-association"));
        }
        self.preflight(publication, descriptor, manifest, config)?;
        let old = self.by_publication.get(&publication.id);
        if old.is_some_and(|e| {
            e.admission_binding
                .as_ref()
                .is_some_and(|b| b.as_ref() != binding)
                || e.admission_completion.is_some_and(|c| c != completion)
        }) {
            return Err(corrupt("admission-history-changed"));
        }
        let base = if old.is_none() {
            sizing::measure(descriptor, manifest, publication.scope.tenant(), config)?.retained
        } else {
            0
        };
        let history = if old.is_none_or(|e| e.admission_binding.is_none()) {
            history_bytes(binding)
        } else {
            0
        };
        let previous = old
            .and_then(|e| e.eligibility.as_ref())
            .map_or(0, crate::ReleaseEligibility::retained_bytes);
        if self
            .accounted_bytes
            .checked_sub(
                self.pending_reservations
                    .get(&publication.id)
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
    #[allow(clippy::too_many_arguments)]
    pub(super) fn insert_admitted(
        &mut self,
        publication: PublicationRef,
        metadata: VerifiedArtifactMetadata,
        stamp: Option<PreparationMetadataFingerprint>,
        binding: crate::AdmissionBinding,
        eligibility: Option<crate::ReleaseEligibility>,
        completion: [u8; 32],
        config: DirectoryArtifactRepositoryConfig,
    ) -> Result<(), PlatformError> {
        self.preflight_admission(
            &publication,
            metadata.descriptor(),
            metadata.manifest(),
            &binding,
            completion,
            eligibility
                .as_ref()
                .map_or(0, crate::ReleaseEligibility::retained_bytes),
            config,
        )?;
        let id = publication.id.clone();
        self.insert_verified(publication, metadata, stamp, config)?;
        self.install_history(&id, binding, completion, config)?;
        if let Some(eligibility) = eligibility {
            self.install_eligibility(&id, eligibility, completion, config)?;
        }
        Ok(())
    }
    pub(super) fn install_history(
        &mut self,
        id: &PublicationId,
        binding: crate::AdmissionBinding,
        completion: [u8; 32],
        config: DirectoryArtifactRepositoryConfig,
    ) -> Result<(), PlatformError> {
        let entry = self
            .by_publication
            .get(id)
            .ok_or_else(|| corrupt("admission-index-entry-missing"))?;
        if entry.admission_completion.is_some_and(|c| c != completion)
            || entry
                .admission_binding
                .as_ref()
                .is_some_and(|b| b.as_ref() != &binding)
        {
            return Err(corrupt("admission-history-changed"));
        }
        if entry.admission_binding.is_some() {
            return Ok(());
        }
        let charge = history_bytes(&binding);
        if self
            .accounted_bytes
            .checked_add(charge)
            .is_none_or(|used| used > config.max_index_bytes)
        {
            return Err(resource_exhausted("admission-history-byte-limit"));
        }
        let entry = self.by_publication.get_mut(id).expect("checked entry");
        entry.value.package = Some(binding.package.clone());
        entry.admission_binding = Some(std::sync::Arc::new(binding));
        entry.admission_completion = Some(completion);
        self.accounted_bytes += charge;
        Ok(())
    }
    pub(super) fn eligibility_capacity(
        &self,
        id: &PublicationId,
        bytes: usize,
        config: DirectoryArtifactRepositoryConfig,
    ) -> Result<(), PlatformError> {
        let old = self
            .by_publication
            .get(id)
            .and_then(|e| e.eligibility.as_ref())
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
        id: &PublicationId,
        eligibility: crate::ReleaseEligibility,
        completion: [u8; 32],
        config: DirectoryArtifactRepositoryConfig,
    ) -> Result<(), PlatformError> {
        let entry = self
            .by_publication
            .get(id)
            .ok_or_else(|| corrupt("admission-index-entry-missing"))?;
        if entry
            .admission_binding
            .as_ref()
            .is_none_or(|b| b.as_ref() != eligibility.binding())
        {
            return Err(corrupt("admission-index-association-changed"));
        }
        self.install_selected_eligibility(id, Some(eligibility), completion, config)
    }
    pub(super) fn install_selected_eligibility(
        &mut self,
        id: &PublicationId,
        eligibility: Option<crate::ReleaseEligibility>,
        completion: [u8; 32],
        config: DirectoryArtifactRepositoryConfig,
    ) -> Result<(), PlatformError> {
        let bytes = eligibility
            .as_ref()
            .map_or(0, crate::ReleaseEligibility::retained_bytes);
        self.eligibility_capacity(id, bytes, config)?;
        let entry = self
            .by_publication
            .get_mut(id)
            .ok_or_else(|| corrupt("admission-index-entry-missing"))?;
        let original = entry
            .admission_binding
            .as_ref()
            .ok_or_else(|| corrupt("admission-index-history-missing"))?;
        if entry.admission_completion != Some(completion)
            || eligibility.as_ref().is_some_and(|proof| {
                proof.release() != &entry.value.descriptor.release_digest
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
    sizing::measure(
        &artifact.descriptor,
        &artifact.manifest,
        artifact.manifest.metadata.tenant.as_ref(),
        config,
    )
    .expect("fixture entry fits")
    .retained
}
