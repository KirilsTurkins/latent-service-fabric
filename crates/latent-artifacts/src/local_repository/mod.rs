mod component_reader;
pub(crate) mod contract_metadata;
mod index;
mod integrity;
mod metadata;
mod metadata_codec;
mod paging;
mod root_durability;
mod sha256;

#[cfg(test)]
mod tests;

use std::collections::hash_map::RandomState;
use std::fs::{self, File, OpenOptions};
use std::io::{Read, Write};
use std::ops::Bound::{Excluded, Unbounded};
use std::path::{Path, PathBuf};
use std::sync::{Arc, Mutex, RwLock};
use std::time::{SystemTime, UNIX_EPOCH};

#[cfg(test)]
use std::sync::atomic::{AtomicBool, Ordering};

use latent_core::{BoxFuture, PlatformError, PlatformErrorCode, ReleaseDigest};
use latent_manifest::{
    JsonManifestCodec, ManifestCodec, ManifestValidator, Phase1ManifestValidator,
};

use crate::preparation::{repository_stamp, RepositoryEpoch};
use crate::verification_statistics::{add, VerificationStatistics};
use crate::{
    ArtifactDescriptor, ArtifactPage, ArtifactPreparationIdentity, ArtifactPreparationSource,
    ArtifactQuery, ArtifactRepository, ArtifactVerificationSnapshot, CapsuleArtifact,
    PreparationMetadataFingerprint, VerifiedArtifactMetadata,
};
use component_reader::{read_component, Retention};
use index::CatalogIndex;
use integrity::CompletionRecord;
use metadata_codec::{decode_metadata, encode_metadata};
use sha256::release_digest;

const RELEASES_DIR: &str = "releases";
const TEMP_DIR: &str = ".tmp";
const OWNER_LOCK_FILE: &str = ".catalog.lock";
const METADATA_FILE: &str = "metadata.json";
const MANIFEST_FILE: &str = "manifest.json";
const COMPONENT_FILE: &str = "component.wasm";
const COMPLETE_FILE: &str = "COMPLETE";

const DEFAULT_MAX_INDEX_ENTRIES: usize = 250_000;
const DEFAULT_MAX_INDEX_BYTES: usize = 64 * 1024 * 1024;
const DEFAULT_MAX_PAGE_SIZE: usize = 1_000;
const DEFAULT_MAX_PAGE_BYTES: usize = 4 * 1024 * 1024;
const DEFAULT_MAX_DESCRIPTOR_BYTES: usize = 256 * 1024;
const DEFAULT_MAX_METADATA_BYTES: usize = 4 * 1024 * 1024;
const DEFAULT_MAX_COMPONENT_BYTES: usize = 256 * 1024 * 1024;
const DEFAULT_MAX_RECOVERY_DIRECTORIES: usize = 1_000_000;

/// Explicit catalog resource bounds.
///
/// `max_index_bytes` bounds a conservative accounting value for all retained
/// compact summaries, descriptors, reference keys and tenant/service index nodes.
/// It also charges fixed preparation stamps, one repository epoch allocation,
/// and fixed verification-counter storage. Optional stamp ineligibility does not
/// change the persisted artifact contract or full-fetch behavior.
/// `max_descriptor_bytes` bounds individual descriptor encodings. Scoped pages
/// charge both canonical summary bytes and owned materialization (including
/// collection slots); `max_page_bytes` bounds their aggregate. Persisted
/// metadata and component reads are also bounded before allocation.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct DirectoryArtifactRepositoryConfig {
    pub max_index_entries: usize,
    pub max_index_bytes: usize,
    pub max_page_size: usize,
    pub max_page_bytes: usize,
    pub max_descriptor_bytes: usize,
    pub max_metadata_bytes: usize,
    pub max_component_bytes: usize,
    /// Bounds all release directories at startup and during publication,
    /// including retained incomplete entries and pending durable adoption.
    /// This can limit publication before the completed-release index quota.
    pub max_recovery_directories: usize,
}

impl Default for DirectoryArtifactRepositoryConfig {
    fn default() -> Self {
        Self {
            max_index_entries: DEFAULT_MAX_INDEX_ENTRIES,
            max_index_bytes: DEFAULT_MAX_INDEX_BYTES,
            max_page_size: DEFAULT_MAX_PAGE_SIZE,
            max_page_bytes: DEFAULT_MAX_PAGE_BYTES,
            max_descriptor_bytes: DEFAULT_MAX_DESCRIPTOR_BYTES,
            max_metadata_bytes: DEFAULT_MAX_METADATA_BYTES,
            max_component_bytes: DEFAULT_MAX_COMPONENT_BYTES,
            max_recovery_directories: DEFAULT_MAX_RECOVERY_DIRECTORIES,
        }
    }
}

#[derive(Debug, Default)]
struct PublicationState {
    pending: Option<ReleaseDigest>,
    // Includes indexed, pending and incomplete directories, not just releases
    // visible to readers. Root ownership and the writer mutex protect this count.
    release_directories: usize,
}

struct VerifiedEntry {
    metadata: VerifiedArtifactMetadata,
    component_bytes: Vec<u8>,
    completion: CompletionRecord,
}

struct PublicationAdoption {
    artifact: CapsuleArtifact,
    stamp: Option<PreparationMetadataFingerprint>,
}

struct PreparedPublication {
    artifact: CapsuleArtifact,
    metadata_bytes: Vec<u8>,
    manifest_bytes: Vec<u8>,
    completion: CompletionRecord,
}

impl PreparedPublication {
    /// Release caller-owned payloads before materializing the persisted entry.
    fn into_completion(self) -> CompletionRecord {
        self.completion
    }
}

/// Releases ownership even while a forked child still has a duplicate descriptor.
/// Construct only after acquisition succeeds, before fallible initialization.
struct OwnerLock(File);

impl Drop for OwnerLock {
    fn drop(&mut self) {
        // Closing alone leaves a Unix flock alive until all inherited handles
        // close. Explicit unlock releases our ownership before the file closes.
        let _ = self.0.unlock();
    }
}

/// Crash-safe local trusted release catalog for standalone `latentd`.
///
/// A repository owns its root exclusively for its lifetime using an OS file
/// lock acquired before temporary cleanup or index rebuild. The lock is
/// released automatically on normal drop and process exit/crash.
pub struct DirectoryArtifactRepository {
    root: PathBuf,
    config: DirectoryArtifactRepositoryConfig,
    codec: JsonManifestCodec,
    validator: Phase1ManifestValidator,
    index: RwLock<CatalogIndex>,
    pagination_fingerprint: RandomState,
    preparation_epoch: Arc<RepositoryEpoch>,
    verification_statistics: VerificationStatistics,
    /// Serializes writers, reserves directory capacity and gates mutations after
    /// indeterminate durability. Only a retry of the pending digest may proceed.
    publish_lock: Mutex<PublicationState>,
    _owner_lock: OwnerLock,
    #[cfg(test)]
    fail_parent_sync_once: AtomicBool,
    #[cfg(test)]
    stamp_byte_limit: usize,
}

impl std::fmt::Debug for DirectoryArtifactRepository {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        formatter
            .debug_struct("DirectoryArtifactRepository")
            .field("root", &self.root)
            .field("config", &self.config)
            .finish_non_exhaustive()
    }
}

impl DirectoryArtifactRepository {
    pub fn open(
        root: impl Into<PathBuf>,
        config: DirectoryArtifactRepositoryConfig,
    ) -> Result<Self, PlatformError> {
        validate_config(config)?;
        let root = root.into();
        let root = root_durability::create_durable_root(&root)?;

        let owner_lock = OpenOptions::new()
            .create(true)
            .read(true)
            .write(true)
            .open(root.join(OWNER_LOCK_FILE))
            .map_err(io_error)?;
        owner_lock.try_lock().map_err(|_| {
            error(
                PlatformErrorCode::Unavailable,
                "catalog root is already owned by another live repository handle",
            )
        })?;
        let owner_lock = OwnerLock(owner_lock);

        fs::create_dir_all(root.join(RELEASES_DIR)).map_err(io_error)?;
        fs::create_dir_all(root.join(TEMP_DIR)).map_err(io_error)?;
        cleanup_temporary_entries(&root)?;
        sync_dir(&root)?;

        let repository = Self {
            root,
            config,
            codec: JsonManifestCodec::default(),
            validator: Phase1ManifestValidator::new(),
            index: RwLock::new(CatalogIndex::default()),
            pagination_fingerprint: RandomState::new(),
            preparation_epoch: Arc::new(RepositoryEpoch),
            verification_statistics: VerificationStatistics::default(),
            publish_lock: Mutex::new(PublicationState::default()),
            _owner_lock: owner_lock,
            #[cfg(test)]
            fail_parent_sync_once: AtomicBool::new(false),
            #[cfg(test)]
            stamp_byte_limit: crate::preparation::MAXIMUM_STAMP_BYTES,
        };
        repository.rebuild_index()?;
        Ok(repository)
    }

    /// Canonical absolute directory whose ownership lock this handle retains.
    /// Later process working-directory changes do not redirect repository I/O.
    #[must_use]
    pub fn root(&self) -> &Path {
        &self.root
    }

    /// Fixed-memory counters for fresh disk verification and stamp creation.
    /// Warm preparation identity lookups do not modify these counters.
    #[must_use]
    pub fn verification_snapshot(&self) -> ArtifactVerificationSnapshot {
        self.verification_statistics.snapshot()
    }

    pub(crate) fn preparation_identity(
        &self,
        release: &ReleaseDigest,
    ) -> Result<Option<ArtifactPreparationIdentity>, PlatformError> {
        let index = self.index.read().map_err(lock_error)?;
        let entry = index
            .by_digest
            .get(release)
            .ok_or_else(|| error(PlatformErrorCode::NotFound, "release digest not found"))?;
        entry
            .preparation_stamp
            .map(|stamp| {
                ArtifactPreparationIdentity::new(
                    Arc::clone(&self.preparation_epoch),
                    release,
                    entry.value.descriptor.size_bytes,
                    stamp,
                )
            })
            .transpose()
    }

    fn preparation_stamp(
        &self,
        metadata: &VerifiedArtifactMetadata,
    ) -> Option<PreparationMetadataFingerprint> {
        add(
            &self.verification_statistics.metadata_fingerprint_attempts,
            1,
        );
        #[cfg(not(test))]
        let maximum = crate::preparation::MAXIMUM_STAMP_BYTES;
        #[cfg(test)]
        let maximum = self.stamp_byte_limit;
        repository_stamp(metadata, maximum)
    }

    fn rebuild_index(&self) -> Result<(), PlatformError> {
        let mut publication = self.publish_lock.lock().map_err(lock_error)?;
        let releases = self.root.join(RELEASES_DIR);
        let mut complete_entries = Vec::new();
        let mut scanned = 0_usize;
        for entry in fs::read_dir(&releases).map_err(io_error)? {
            let entry = entry.map_err(io_error)?;
            if !entry.file_type().map_err(io_error)?.is_dir() {
                continue;
            }
            scanned = scanned.saturating_add(1);
            if scanned > self.config.max_recovery_directories {
                return Err(resource_exhausted(
                    "catalog recovery directory scan limit reached",
                ));
            }
            let path = entry.path();
            if !is_recovery_candidate(&path)? {
                continue;
            }
            if complete_entries.len() >= self.config.max_index_entries {
                return Err(resource_exhausted(
                    "catalog contains more complete releases than the configured index bound",
                ));
            }
            complete_entries.push(path);
        }
        complete_entries.sort();

        let mut next = CatalogIndex::default();
        for path in complete_entries {
            let metadata = self
                .load_complete_entry(&path, Retention::Metadata)?
                .metadata;
            let stamp = self.preparation_stamp(&metadata);
            next.insert_verified(metadata, stamp, self.config)?;
        }
        // Reconcile completed entries from an interrupted publication before
        // exposing the rebuilt index or allowing further mutations.
        sync_dir(&releases)?;
        *self.index.write().map_err(lock_error)? = next;
        publication.release_directories = scanned;
        publication.pending = None;
        Ok(())
    }

    fn load_complete_entry(
        &self,
        path: &Path,
        retention: Retention,
    ) -> Result<VerifiedEntry, PlatformError> {
        let completion = CompletionRecord::read(path)?;
        let metadata_bytes = read_bounded_file(
            &path.join(METADATA_FILE),
            self.config.max_metadata_bytes,
            "catalog metadata",
        )?;
        completion.verify_metadata(&metadata_bytes)?;
        let (descriptor, contracts) =
            decode_metadata(&metadata_bytes, self.config.max_metadata_bytes)?;
        drop(metadata_bytes);
        self.validate_descriptor_bounds(&descriptor)?;
        completion.verify_component_association(&descriptor)?;
        if descriptor.size_bytes > self.config.max_component_bytes as u64 {
            return Err(resource_exhausted(
                "stored component exceeds configured component byte limit",
            ));
        }
        let manifest_bytes = read_bounded_file(
            &path.join(MANIFEST_FILE),
            self.codec.limits().max_document_bytes,
            "capsule manifest",
        )?;
        completion.verify_manifest(&manifest_bytes)?;
        let manifest = self
            .codec
            .decode_capsule(&manifest_bytes)
            .map_err(|_| corrupt("stored capsule manifest is invalid"))?;
        self.validator
            .validate_capsule(&manifest)
            .map_err(|_| corrupt("stored capsule manifest violates Phase 1 rules"))?;
        let canonical = self
            .codec
            .encode_capsule(&manifest)
            .map_err(|_| corrupt("stored capsule manifest cannot be canonicalized"))?;
        if canonical != manifest_bytes {
            return Err(corrupt("stored capsule manifest is not canonical"));
        }
        drop(canonical);
        drop(manifest_bytes);
        let component = read_component(
            &path.join(COMPONENT_FILE),
            self.config.max_component_bytes,
            retention,
            &self.verification_statistics,
        )?;
        verify_component_digest(
            &descriptor,
            &manifest.component_digest,
            &component.digest,
            component.size,
        )?;
        let expected_dir = digest_hex(&descriptor.release_digest)?;
        if path.file_name().and_then(|value| value.to_str()) != Some(expected_dir.as_str()) {
            return Err(corrupt("release directory does not match its digest"));
        }
        Ok(VerifiedEntry {
            metadata: VerifiedArtifactMetadata::from_verified_parts(
                descriptor,
                manifest,
                contracts,
                component.digest,
            ),
            component_bytes: component.bytes,
            completion,
        })
    }

    fn entry_path(&self, digest: &ReleaseDigest) -> Result<PathBuf, PlatformError> {
        Ok(self.root.join(RELEASES_DIR).join(digest_hex(digest)?))
    }

    fn validate_descriptor_bounds(
        &self,
        descriptor: &ArtifactDescriptor,
    ) -> Result<usize, PlatformError> {
        index::descriptor_bytes(descriptor, self.config.max_descriptor_bytes)
    }

    fn finalize_adoption(
        &self,
        artifact: CapsuleArtifact,
        stamp: Option<PreparationMetadataFingerprint>,
    ) -> Result<ArtifactDescriptor, PlatformError> {
        let mut index = self.index.write().map_err(lock_error)?;
        index.insert(artifact, stamp, self.config)
    }

    fn preflight_adoption(&self, artifact: &CapsuleArtifact) -> Result<(), PlatformError> {
        let index = self.index.read().map_err(lock_error)?;
        index.preflight(&artifact.descriptor, &artifact.manifest, self.config)
    }

    fn sync_and_adopt(
        &self,
        adoption: PublicationAdoption,
        pending: &mut Option<ReleaseDigest>,
    ) -> Result<ArtifactDescriptor, PlatformError> {
        // The completed destination now exists. Keep the mutation gate closed
        // across every failure, including repeated sync or adoption failures.
        *pending = Some(adoption.artifact.descriptor.release_digest.clone());
        #[cfg(test)]
        if self.fail_parent_sync_once.swap(false, Ordering::SeqCst) {
            return Err(error(
                PlatformErrorCode::Internal,
                "injected parent-directory sync failure after rename",
            ));
        }
        sync_dir(&self.root.join(RELEASES_DIR))?;
        let adopted = self.finalize_adoption(adoption.artifact, adoption.stamp)?;
        *pending = None;
        Ok(adopted)
    }

    fn prepare_publication(
        &self,
        mut artifact: CapsuleArtifact,
    ) -> Result<PreparedPublication, PlatformError> {
        self.validator
            .validate_capsule(&artifact.manifest)
            .map_err(|_| {
                error(
                    PlatformErrorCode::InvalidArgument,
                    "capsule manifest validation failed",
                )
            })?;
        let manifest_bytes = self.codec.encode_capsule(&artifact.manifest).map_err(|_| {
            error(
                PlatformErrorCode::InvalidArgument,
                "capsule manifest encoding failed",
            )
        })?;
        // Compare retries with the same normalized model that fetch/reopen reads.
        // A caller may construct valid imports/exports in any order.
        artifact.manifest = self.codec.decode_capsule(&manifest_bytes).map_err(|_| {
            error(
                PlatformErrorCode::InvalidArgument,
                "canonical capsule manifest decoding failed",
            )
        })?;
        if artifact.component_bytes.len() > self.config.max_component_bytes {
            return Err(resource_exhausted(
                "component artifact exceeds configured byte limit",
            ));
        }
        verify_component_identity(
            &artifact.descriptor,
            &artifact.manifest.component_digest,
            &artifact.component_bytes,
        )?;
        self.preflight_adoption(&artifact)?;
        let metadata_bytes = encode_metadata(&artifact, self.config.max_metadata_bytes)?;
        let completion =
            CompletionRecord::from_payloads(&artifact.descriptor, &metadata_bytes, &manifest_bytes);
        Ok(PreparedPublication {
            artifact,
            metadata_bytes,
            manifest_bytes,
            completion,
        })
    }

    fn stage_publication(&self, prepared: &PreparedPublication) -> Result<PathBuf, PlatformError> {
        let nonce = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .map_err(|_| {
                error(
                    PlatformErrorCode::Internal,
                    "system clock is before Unix epoch",
                )
            })?
            .as_nanos();
        let tmp_path = self.root.join(TEMP_DIR).join(format!(
            "{}-{}-{nonce}",
            std::process::id(),
            digest_hex(&prepared.artifact.descriptor.release_digest)?
        ));
        fs::create_dir(&tmp_path).map_err(io_error)?;

        let staged = (|| {
            write_synced(&tmp_path.join(METADATA_FILE), &prepared.metadata_bytes)?;
            write_synced(&tmp_path.join(MANIFEST_FILE), &prepared.manifest_bytes)?;
            write_synced(
                &tmp_path.join(COMPONENT_FILE),
                &prepared.artifact.component_bytes,
            )?;
            write_synced(
                &tmp_path.join(COMPLETE_FILE),
                &prepared.completion.encode()?,
            )?;
            sync_dir(&tmp_path)
        })();
        if let Err(failure) = staged {
            let _ = fs::remove_dir_all(&tmp_path);
            return Err(failure);
        }
        Ok(tmp_path)
    }

    /// Only verified identical persisted bytes are eligible for publication adoption.
    /// Streams the component without retaining it before directory sync/index work.
    fn read_for_adoption(
        &self,
        path: &Path,
        expected: &CompletionRecord,
    ) -> Result<Option<PublicationAdoption>, PlatformError> {
        let verified = self.load_complete_entry(path, Retention::Metadata)?;
        if &verified.completion != expected {
            return Ok(None);
        }
        let stamp = self.preparation_stamp(&verified.metadata);
        // Adoption needs only descriptor/manifest. Release decoded contracts
        // before directory synchronization and index locking, as before.
        let (descriptor, manifest, contracts) = verified.metadata.into_parts();
        drop(contracts);
        Ok(Some(PublicationAdoption {
            artifact: CapsuleArtifact {
                descriptor,
                manifest,
                contracts: Vec::new(),
                component_bytes: Vec::new(),
            },
            stamp,
        }))
    }

    fn publish_sync(&self, artifact: CapsuleArtifact) -> Result<ArtifactDescriptor, PlatformError> {
        let mut publication = self.publish_lock.lock().map_err(lock_error)?;
        let digest = artifact.descriptor.release_digest.clone();
        if publication
            .pending
            .as_ref()
            .is_some_and(|pending| pending != &digest)
        {
            return Err(error(
                PlatformErrorCode::Unavailable,
                "catalog needs publication recovery: retry the pending release or reopen the root",
            ));
        }
        let prepared = self.prepare_publication(artifact)?;
        let destination = self.entry_path(&digest)?;
        if destination.exists() {
            let expected = prepared.into_completion();
            let descriptor = self
                .read_for_adoption(&destination, &expected)?
                .ok_or_else(|| {
                    error(
                        PlatformErrorCode::AlreadyExists,
                        "release digest already contains different catalog content",
                    )
                })?;
            return self.sync_and_adopt(descriptor, &mut publication.pending);
        }
        // Holding the writer mutex reserves this slot until rename or failure.
        // Existing-entry retries above use their already-accounted directory.
        if publication.release_directories >= self.config.max_recovery_directories {
            return Err(resource_exhausted(
                "catalog recovery directory capacity reached",
            ));
        }
        let tmp_path = self.stage_publication(&prepared)?;
        let expected = prepared.into_completion();

        if let Err(rename_failure) = fs::rename(&tmp_path, &destination).map_err(io_error) {
            let _ = fs::remove_dir_all(&tmp_path);
            if destination.exists() {
                // A destination appeared after the initial absence check.
                // Account for it before adoption, even if validation/sync fails.
                publication.release_directories += 1;
                publication.pending = Some(digest);
                let descriptor = self
                    .read_for_adoption(&destination, &expected)?
                    .ok_or_else(|| {
                        error(
                            PlatformErrorCode::AlreadyExists,
                            "release digest was externally published with different content",
                        )
                    })?;
                return self.sync_and_adopt(descriptor, &mut publication.pending);
            }
            return Err(rename_failure);
        }
        // Rename consumes the reserved slot independently of index visibility.
        // Keep the mutation gate and charge across every verification/sync failure.
        publication.release_directories += 1;
        publication.pending = Some(digest);
        #[cfg(test)]
        integrity::faults::after_rename(&destination);
        let descriptor = self
            .read_for_adoption(&destination, &expected)?
            .ok_or_else(integrity::invalid_record)?;
        self.sync_and_adopt(descriptor, &mut publication.pending)
    }

    #[cfg(test)]
    fn inject_parent_sync_failure_once(&self) {
        self.fail_parent_sync_once.store(true, Ordering::SeqCst);
    }
}

impl ArtifactRepository for DirectoryArtifactRepository {
    fn preparation_source(&self) -> Option<ArtifactPreparationSource<'_>> {
        Some(ArtifactPreparationSource::new(self))
    }
    fn get_catalog_entry<'a>(
        &'a self,
        tenant: &'a latent_core::TenantId,
        digest: &'a ReleaseDigest,
    ) -> BoxFuture<'a, Result<Option<crate::ArtifactCatalogEntry>, PlatformError>> {
        Box::pin(async move { self.catalog_entry(tenant, digest) })
    }

    fn list_catalog_entries<'a>(
        &'a self,
        request: &'a crate::ArtifactCatalogPageRequest,
    ) -> BoxFuture<'a, Result<crate::ArtifactCatalogPage, PlatformError>> {
        Box::pin(async move { self.catalog_page(request) })
    }

    fn resolve<'a>(
        &'a self,
        query: &'a ArtifactQuery,
    ) -> BoxFuture<'a, Result<Option<ArtifactDescriptor>, PlatformError>> {
        Box::pin(async move {
            let index = self.index.read().map_err(lock_error)?;
            let descriptor = if let Some(digest) = &query.release_digest {
                index.by_digest.get(digest)
            } else if let Some(reference) = &query.reference {
                index
                    .by_reference
                    .get(reference)
                    .and_then(|digest| index.by_digest.get(digest))
            } else {
                None
            };
            Ok(descriptor
                .map(|entry| &entry.value.descriptor)
                .filter(|value| {
                    query
                        .reference
                        .as_ref()
                        .is_none_or(|reference| &value.reference == reference)
                        && query
                            .media_type
                            .as_ref()
                            .is_none_or(|media_type| &value.media_type == media_type)
                })
                .cloned())
        })
    }

    fn fetch<'a>(
        &'a self,
        digest: &'a ReleaseDigest,
    ) -> BoxFuture<'a, Result<CapsuleArtifact, PlatformError>> {
        Box::pin(async move {
            add(&self.verification_statistics.full_fetch_attempts, 1);
            if !self
                .index
                .read()
                .map_err(lock_error)?
                .by_digest
                .contains_key(digest)
            {
                return Err(error(
                    PlatformErrorCode::NotFound,
                    "release digest not found",
                ));
            }
            let verified =
                self.load_complete_entry(&self.entry_path(digest)?, Retention::Component)?;
            let (descriptor, manifest, contracts) = verified.metadata.into_parts();
            Ok(CapsuleArtifact {
                descriptor,
                manifest,
                contracts,
                component_bytes: verified.component_bytes,
            })
        })
    }

    fn fetch_verified_metadata<'a>(
        &'a self,
        digest: &'a ReleaseDigest,
    ) -> BoxFuture<'a, Result<VerifiedArtifactMetadata, PlatformError>> {
        Box::pin(async move {
            add(&self.verification_statistics.metadata_fetch_attempts, 1);
            if !self
                .index
                .read()
                .map_err(lock_error)?
                .by_digest
                .contains_key(digest)
            {
                return Err(error(
                    PlatformErrorCode::NotFound,
                    "release digest not found",
                ));
            }
            let verified =
                self.load_complete_entry(&self.entry_path(digest)?, Retention::Metadata)?;
            verified.metadata.verify_requested(digest)?;
            Ok(verified.metadata)
        })
    }

    fn publish<'a>(
        &'a self,
        artifact: CapsuleArtifact,
    ) -> BoxFuture<'a, Result<ArtifactDescriptor, PlatformError>> {
        Box::pin(async move { self.publish_sync(artifact) })
    }

    fn list<'a>(
        &'a self,
        after: Option<&'a ReleaseDigest>,
        limit: usize,
    ) -> BoxFuture<'a, Result<ArtifactPage, PlatformError>> {
        Box::pin(async move {
            if limit == 0 {
                return Err(error(
                    PlatformErrorCode::InvalidArgument,
                    "list limit must be greater than zero",
                ));
            }
            let entry_limit = limit.min(self.config.max_page_size);
            let index = self.index.read().map_err(lock_error)?;
            let mut entries = Vec::new();
            let mut response_bytes = 0_usize;
            let mut has_more = false;
            for descriptor in index
                .by_digest
                .range((after.map_or(Unbounded, Excluded), Unbounded))
                .map(|(_, descriptor)| descriptor)
            {
                if entries.len() >= entry_limit {
                    has_more = true;
                    break;
                }
                let descriptor_bytes = descriptor.descriptor_bytes;
                if response_bytes.saturating_add(descriptor_bytes) > self.config.max_page_bytes {
                    has_more = true;
                    break;
                }
                response_bytes = response_bytes.saturating_add(descriptor_bytes);
                entries.push(descriptor.value.descriptor.clone());
            }
            let next_after = if has_more {
                entries.last().map(|value| value.release_digest.clone())
            } else {
                None
            };
            Ok(ArtifactPage {
                entries,
                next_after,
            })
        })
    }
}

fn validate_config(config: DirectoryArtifactRepositoryConfig) -> Result<(), PlatformError> {
    if config.max_index_entries == 0
        || config.max_index_bytes == 0
        || config.max_page_size == 0
        || config.max_page_bytes == 0
        || config.max_descriptor_bytes == 0
        || config.max_metadata_bytes == 0
        || config.max_component_bytes == 0
        || config.max_recovery_directories == 0
    {
        return Err(error(
            PlatformErrorCode::InvalidArgument,
            "all catalog resource bounds must be greater than zero",
        ));
    }
    if config.max_descriptor_bytes > config.max_page_bytes
        || config.max_descriptor_bytes > config.max_metadata_bytes
    {
        return Err(error(
            PlatformErrorCode::InvalidArgument,
            "descriptor byte bound must fit within page and metadata byte bounds",
        ));
    }
    if config.max_index_bytes < index::REPOSITORY_ACCOUNTED_BYTES {
        return Err(resource_exhausted("catalog index byte limit reached"));
    }
    // Directory and index limits are independent; publication enforces both.
    // Retained debris can exhaust directory capacity before index capacity.
    Ok(())
}

fn is_recovery_candidate(path: &Path) -> Result<bool, PlatformError> {
    // A digest-named final directory can only follow publication's completed
    // staging rename. Losing COMPLETE must not silently erase it from recovery.
    if path
        .file_name()
        .and_then(|name| name.to_str())
        .is_some_and(|name| name.len() == 64 && name.bytes().all(|byte| byte.is_ascii_hexdigit()))
    {
        return Ok(true);
    }
    // Non-digest incomplete debris still counts toward the directory budget.
    // Any claimed completion is verified, including non-regular marker entries.
    match fs::symlink_metadata(path.join(COMPLETE_FILE)) {
        Ok(_) => Ok(true),
        Err(failure) if failure.kind() == std::io::ErrorKind::NotFound => Ok(false),
        Err(failure) => Err(io_error(failure)),
    }
}

fn cleanup_temporary_entries(root: &Path) -> Result<(), PlatformError> {
    let temp = root.join(TEMP_DIR);
    for entry in fs::read_dir(temp).map_err(io_error)? {
        let entry = entry.map_err(io_error)?;
        if entry.file_type().map_err(io_error)?.is_dir() {
            fs::remove_dir_all(entry.path()).map_err(io_error)?;
        } else {
            fs::remove_file(entry.path()).map_err(io_error)?;
        }
    }
    Ok(())
}

fn verify_component_identity(
    descriptor: &ArtifactDescriptor,
    manifest_digest: &ReleaseDigest,
    component_bytes: &[u8],
) -> Result<(), PlatformError> {
    let actual = release_digest(component_bytes);
    verify_component_digest(
        descriptor,
        manifest_digest,
        &actual,
        component_bytes.len() as u64,
    )
}

fn verify_component_digest(
    descriptor: &ArtifactDescriptor,
    manifest_digest: &ReleaseDigest,
    actual: &ReleaseDigest,
    size: u64,
) -> Result<(), PlatformError> {
    if actual != manifest_digest || actual != &descriptor.release_digest {
        return Err(corrupt(
            "manifest, release, and component content digests must agree",
        ));
    }
    if descriptor.size_bytes != size {
        return Err(corrupt(
            "artifact descriptor size does not match component bytes",
        ));
    }
    Ok(())
}

fn digest_hex(digest: &ReleaseDigest) -> Result<String, PlatformError> {
    let Some(hex) = digest.0.strip_prefix("sha256:") else {
        return Err(corrupt("release digest must use sha256"));
    };
    if hex.len() != 64 || !hex.bytes().all(|byte| byte.is_ascii_hexdigit()) {
        return Err(corrupt(
            "release digest must contain 64 hexadecimal characters",
        ));
    }
    Ok(hex.to_ascii_lowercase())
}

fn read_bounded_file(path: &Path, limit: usize, label: &str) -> Result<Vec<u8>, PlatformError> {
    let file = File::open(path).map_err(|_| corrupt("completed release is missing data"))?;
    let length = file
        .metadata()
        .map_err(|_| corrupt("completed release data metadata cannot be read"))?
        .len();
    if length > limit as u64 {
        return Err(resource_exhausted(format!(
            "stored {label} exceeds configured byte limit"
        )));
    }
    let capacity = usize::try_from(length)
        .map_err(|_| resource_exhausted("stored release file length cannot fit in memory"))?;
    let read_limit = u64::try_from(limit)
        .map_err(|_| resource_exhausted("configured file limit cannot fit in u64"))?
        .saturating_add(1);
    let mut reader = file.take(read_limit);
    let mut bytes = Vec::with_capacity(capacity);
    reader
        .read_to_end(&mut bytes)
        .map_err(|_| corrupt("completed release data cannot be read"))?;
    if bytes.len() > limit {
        return Err(resource_exhausted(format!(
            "stored {label} exceeds configured byte limit"
        )));
    }
    Ok(bytes)
}

fn write_synced(path: &Path, bytes: &[u8]) -> Result<(), PlatformError> {
    let mut file = OpenOptions::new()
        .create_new(true)
        .write(true)
        .open(path)
        .map_err(io_error)?;
    file.write_all(bytes).map_err(io_error)?;
    file.sync_all().map_err(io_error)
}

fn sync_dir(path: &Path) -> Result<(), PlatformError> {
    File::open(path)
        .and_then(|file| file.sync_all())
        .map_err(io_error)
}

fn io_error(error_value: std::io::Error) -> PlatformError {
    error(
        PlatformErrorCode::Internal,
        format!("catalog filesystem operation failed: {error_value}"),
    )
}

fn lock_error<T>(_: std::sync::PoisonError<T>) -> PlatformError {
    error(
        PlatformErrorCode::Internal,
        "catalog synchronization primitive was poisoned",
    )
}

fn corrupt(message: impl Into<String>) -> PlatformError {
    error(PlatformErrorCode::CorruptArtifact, message)
}

fn resource_exhausted(message: impl Into<String>) -> PlatformError {
    error(PlatformErrorCode::ResourceExhausted, message)
}

fn error(code: PlatformErrorCode, message: impl Into<String>) -> PlatformError {
    PlatformError {
        code,
        message: message.into(),
        retryable: false,
        details: Vec::new(),
    }
}
