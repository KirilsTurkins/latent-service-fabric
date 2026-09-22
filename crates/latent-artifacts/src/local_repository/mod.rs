mod admission;
mod admission_storage;
mod component_reader;
pub(crate) mod contract_metadata;
mod document_reader;
mod index;
mod integrity;
mod lifecycle;
mod metadata;
mod metadata_codec;
mod migration;
mod paging;
mod preparation_read;
mod publication_access;
mod publication_preparation;
mod retained_package;
mod root_durability;
mod shared_content;
pub use migration::{CatalogMigrationLimits, CatalogMigrationReceipt};
pub use shared_content::{PublicationContentReclamation, PublicationStorageSnapshot};
mod sha256;
mod web;

#[cfg(test)]
mod tests;

use std::collections::hash_map::RandomState;
use std::fs::{self, File, OpenOptions};
use std::io::Write;
use std::ops::Bound::{Excluded, Unbounded};
use std::path::{Path, PathBuf};
use std::sync::{Arc, Mutex, OnceLock, RwLock};
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
    ArtifactDescriptor, ArtifactPage, ArtifactPreparationIdentity, ArtifactPreparationReadLimits,
    ArtifactPreparationSource, ArtifactQuery, ArtifactRepository, ArtifactVerificationSnapshot,
    CapsuleArtifact, OwnedArtifactPreparationSource, PreparationMetadataFingerprint,
    VerifiedArtifactMetadata,
};
use component_reader::{read_component, Retention};
use document_reader::read_bounded_file;
use index::CatalogIndex;
use integrity::CompletionRecord;
use metadata_codec::{decode_metadata, encode_metadata};
use sha256::release_digest;

const RELEASES_DIR: &str = "publications";
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
    /// Conservative shared-file plus publication-link storage exposure ceiling.
    pub max_storage_bytes: u64,
    pub max_content_index_bytes: usize,
    pub max_content_blobs: usize,
    pub max_publication_files: usize,
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
            max_storage_bytes: 4 * 1024 * 1024 * 1024,
            max_content_index_bytes: 64 * 1024 * 1024,
            max_content_blobs: 1_000_000,
            max_publication_files: 1024,
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
    pending: Option<latent_core::PublicationId>,
    // Includes indexed, pending and incomplete directories, not just releases
    // visible to readers. Root ownership and the writer mutex protect this count.
    release_directories: usize,
}

struct VerifiedEntry {
    publication: crate::PublicationRef,
    metadata: VerifiedArtifactMetadata,
    component_bytes: Vec<u8>,
    completion: CompletionRecord,
    admission: Option<admission_storage::StoredAdmission>,
}

struct PreparedPublication {
    artifact: CapsuleArtifact,
    metadata_bytes: Vec<u8>,
    manifest_bytes: Vec<u8>,
    completion: CompletionRecord,
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

/// Crash-safe standalone release catalog with an explicit trust mode.
///
/// A repository owns its root exclusively for its lifetime using an OS file
/// lock acquired before temporary cleanup or index rebuild. The lock is
/// released automatically on normal drop and process exit/crash.
/// `open` retains the Phase 1 trusted-local contract; `open_enforced` requires a
/// configured admission authority and refuses raw publication. Catalog pages
/// retain bounded historical summaries, while resolution and preparation require
/// current eligibility. Enforced roots cannot reopen in trusted-local mode.
pub struct DirectoryArtifactRepository {
    root: PathBuf,
    config: DirectoryArtifactRepositoryConfig,
    lifecycle_limits: crate::LifecycleLimits,
    codec: JsonManifestCodec,
    validator: Phase1ManifestValidator,
    index: RwLock<CatalogIndex>,
    pagination_fingerprint: RandomState,
    preparation_epoch: Arc<RepositoryEpoch>,
    verification_statistics: VerificationStatistics,
    /// Serializes writers, reserves directory capacity and gates mutations after
    /// indeterminate durability. Only a retry of the pending digest may proceed.
    publish_lock: Mutex<PublicationState>,
    admission_work: Mutex<()>,
    content: Mutex<shared_content::SharedContent>,
    admission: Option<admission::RepositoryAdmission>,
    lifecycle: OnceLock<crate::lifecycle::LifecycleStore>,
    web: web::WebCatalog,
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
        Self::open_with_lifecycle_limits(root, config, crate::LifecycleLimits::default())
    }

    pub fn open_with_lifecycle_limits(
        root: impl Into<PathBuf>,
        config: DirectoryArtifactRepositoryConfig,
        lifecycle_limits: crate::LifecycleLimits,
    ) -> Result<Self, PlatformError> {
        Self::open_configured(root.into(), config, None, lifecycle_limits)
    }

    pub fn open_enforced(
        root: impl Into<PathBuf>,
        config: DirectoryArtifactRepositoryConfig,
        limits: crate::AdmissionStorageLimits,
        authority: Arc<dyn crate::AdmissionAuthority>,
    ) -> Result<Self, PlatformError> {
        Self::open_enforced_with_lifecycle_limits(
            root,
            config,
            limits,
            authority,
            crate::LifecycleLimits::default(),
        )
    }

    pub fn open_enforced_with_lifecycle_limits(
        root: impl Into<PathBuf>,
        config: DirectoryArtifactRepositoryConfig,
        limits: crate::AdmissionStorageLimits,
        authority: Arc<dyn crate::AdmissionAuthority>,
        lifecycle_limits: crate::LifecycleLimits,
    ) -> Result<Self, PlatformError> {
        limits.validate()?;
        Self::open_configured(
            root.into(),
            config,
            Some(admission::RepositoryAdmission::new(authority, limits)),
            lifecycle_limits,
        )
    }

    fn open_configured(
        root: PathBuf,
        config: DirectoryArtifactRepositoryConfig,
        admission: Option<admission::RepositoryAdmission>,
        lifecycle_limits: crate::LifecycleLimits,
    ) -> Result<Self, PlatformError> {
        let repository = Self::acquire_configured(root, config, admission, lifecycle_limits)?;
        migration::check_current_format(&repository.root)?;
        fs::create_dir_all(repository.root.join(RELEASES_DIR)).map_err(io_error)?;
        fs::create_dir_all(repository.root.join(TEMP_DIR)).map_err(io_error)?;
        cleanup_temporary_entries(&repository.root)?;
        repository.content.lock().map_err(lock_error)?.open()?;
        sync_dir(&repository.root)?;
        let baseline = repository.rebuild_index()?;
        repository.initialize_lifecycle(&baseline)?;
        repository.initialize_web()?;
        if repository.admission.is_some() {
            admission::persist_mode(&repository.root)?;
        }
        Ok(repository)
    }

    fn acquire_configured(
        root: PathBuf,
        config: DirectoryArtifactRepositoryConfig,
        admission: Option<admission::RepositoryAdmission>,
        lifecycle_limits: crate::LifecycleLimits,
    ) -> Result<Self, PlatformError> {
        validate_config(config)?;
        lifecycle_limits.validate()?;
        let config = DirectoryArtifactRepositoryConfig {
            max_index_entries: config.max_index_entries.min(lifecycle_limits.max_records),
            ..config
        };
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
        admission::check_mode(&root, admission.is_some())?;

        let repository = Self {
            content: Mutex::new(shared_content::SharedContent::new(&root, config)),
            root,
            config,
            lifecycle_limits,
            codec: JsonManifestCodec::default(),
            validator: Phase1ManifestValidator::new(),
            index: RwLock::new(CatalogIndex::default()),
            pagination_fingerprint: RandomState::new(),
            preparation_epoch: Arc::new(RepositoryEpoch),
            verification_statistics: VerificationStatistics::default(),
            publish_lock: Mutex::new(PublicationState::default()),
            admission_work: Mutex::new(()),
            web: web::WebCatalog::new(
                admission
                    .as_ref()
                    .map(|configured| Arc::clone(&configured.authority)),
            )?,
            admission,
            lifecycle: OnceLock::new(),
            _owner_lock: owner_lock,
            #[cfg(test)]
            fail_parent_sync_once: AtomicBool::new(false),
            #[cfg(test)]
            stamp_byte_limit: crate::preparation::MAXIMUM_STAMP_BYTES,
        };
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
        self.selected_preparation_identity(release, None)
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

    fn rebuild_index(&self) -> Result<Vec<crate::lifecycle::LifecycleIdentity>, PlatformError> {
        let releases = self.root.join(RELEASES_DIR);
        let mut complete_entries = Vec::new();
        let mut scanned = 0_usize;
        for entry in fs::read_dir(&releases).map_err(io_error)? {
            let entry = entry.map_err(io_error)?;
            shared_content::directory(&entry.path())?;
            scanned = scanned.saturating_add(1);
            if scanned > self.config.max_recovery_directories {
                return Err(resource_exhausted(
                    "catalog recovery directory scan limit reached",
                ));
            }
            let path = entry.path();
            if !is_recovery_candidate(&path)? {
                self.content
                    .lock()
                    .map_err(lock_error)?
                    .charge_incomplete(&path)?;
                continue;
            }
            if complete_entries.len()
                >= self
                    .config
                    .max_index_entries
                    .min(self.lifecycle_limits.max_records)
            {
                return Err(resource_exhausted(
                    "catalog contains more complete releases than the configured index bound",
                ));
            }
            complete_entries.push(path);
        }
        complete_entries.sort();

        let mut next = CatalogIndex::default();
        let mut baseline = Vec::with_capacity(complete_entries.len());
        for path in complete_entries {
            let verified = self.load_complete_entry(&path, Retention::Metadata)?;
            self.content
                .lock()
                .map_err(lock_error)?
                .register_directory(&verified.publication.id, &path)?;
            let eligibility = self.recover_eligibility(&path, &verified)?;
            let completion = verified.completion.identity()?;
            let metadata = verified.metadata;
            let publication_ref = verified.publication;
            baseline.push(crate::lifecycle::LifecycleIdentity {
                scope: publication_ref.scope.clone(),
                release: metadata.verified_digest().clone(),
                package: eligibility
                    .as_ref()
                    .map(|value| value.binding.package.clone()),
                completion,
            });
            let stamp = self.preparation_stamp(&metadata);
            if let Some(recovered) = eligibility {
                next.insert_admitted(
                    publication_ref,
                    metadata,
                    stamp,
                    recovered.binding,
                    recovered.eligibility,
                    completion,
                    self.config,
                )?;
            } else {
                next.insert_verified(publication_ref, metadata, stamp, self.config)?;
            }
        }
        // Reconcile completed entries from an interrupted publication before
        // exposing the rebuilt index or allowing further mutations.
        sync_dir(&releases)?;
        let mut publication = self.publish_lock.lock().map_err(lock_error)?;
        *self.index.write().map_err(lock_error)? = next;
        publication.release_directories = scanned;
        publication.pending = None;
        Ok(baseline)
    }

    fn load_complete_entry(
        &self,
        path: &Path,
        retention: Retention,
    ) -> Result<VerifiedEntry, PlatformError> {
        self.load_complete_entry_with_limits(path, retention, self.repository_read_limits())
    }

    fn load_complete_entry_with_limits(
        &self,
        path: &Path,
        retention: Retention,
        limits: ArtifactPreparationReadLimits,
    ) -> Result<VerifiedEntry, PlatformError> {
        self.load_complete_entry_at_format(path, retention, limits, false)
    }

    fn load_complete_entry_at_format(
        &self,
        path: &Path,
        retention: Retention,
        limits: ArtifactPreparationReadLimits,
        legacy: bool,
    ) -> Result<VerifiedEntry, PlatformError> {
        let completion = CompletionRecord::read(path)?;
        let admission = match (self.admission.as_ref(), completion.admission_digest()) {
            (Some(config), Some(digest)) => Some(admission_storage::StoredAdmission::read(
                path,
                digest,
                config.limits,
                self.config.max_component_bytes,
            )?),
            (None, None) => None,
            _ => return Err(corrupt("catalog-admission-mode-mismatch")),
        };
        let metadata_bytes = read_bounded_file(
            &path.join(METADATA_FILE),
            limits.maximum_metadata_document_bytes,
            "catalog metadata",
        )?;
        completion.verify_metadata(&metadata_bytes)?;
        let (descriptor, contracts) =
            decode_metadata(&metadata_bytes, limits.maximum_metadata_document_bytes)?;
        drop(metadata_bytes);
        self.validate_descriptor_bounds(&descriptor)?;
        completion.verify_component_association(&descriptor)?;
        if descriptor.size_bytes > limits.maximum_component_bytes as u64 {
            return Err(resource_exhausted(
                "stored component exceeds configured component byte limit",
            ));
        }
        let manifest_bytes = read_bounded_file(
            &path.join(MANIFEST_FILE),
            limits.maximum_manifest_document_bytes,
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
            limits.maximum_component_bytes,
            retention,
            &self.verification_statistics,
        )?;
        verify_component_digest(
            &descriptor,
            &manifest.component_digest,
            &component.digest,
            component.size,
        )?;
        let publication = if let Some(stored) = &admission {
            let binding =
                stored.binding(path, self.admission.as_ref().expect("enforced mode").limits)?;
            crate::PublicationRef::package(
                crate::LifecycleScope::Tenant(binding.tenant),
                &binding.package,
            )?
        } else {
            crate::PublicationRef::trusted_local(
                manifest.metadata.tenant.clone().map_or(
                    crate::LifecycleScope::LocalUnscoped,
                    crate::LifecycleScope::Tenant,
                ),
                &completion.identity()?,
            )?
        };
        let expected_dir = if legacy {
            digest_hex(&descriptor.release_digest)?
        } else {
            publication.id.hex().to_owned()
        };
        if path.file_name().and_then(|value| value.to_str()) != Some(expected_dir.as_str()) {
            return Err(corrupt(
                "publication directory does not match its immutable association",
            ));
        }
        Ok(VerifiedEntry {
            publication,
            metadata: VerifiedArtifactMetadata::from_verified_parts(
                descriptor,
                manifest,
                contracts,
                component.digest,
            ),
            component_bytes: component.bytes,
            completion,
            admission,
        })
    }

    fn entry_path(&self, digest: &ReleaseDigest) -> Result<PathBuf, PlatformError> {
        Ok(self.publication_path(&self.require_legacy_publication(None, digest)?.id))
    }

    fn validate_descriptor_bounds(
        &self,
        descriptor: &ArtifactDescriptor,
    ) -> Result<usize, PlatformError> {
        index::descriptor_bytes(descriptor, self.config.max_descriptor_bytes)
    }

    #[cfg(test)]
    fn finalize_adoption(
        &self,
        artifact: CapsuleArtifact,
        stamp: Option<PreparationMetadataFingerprint>,
    ) -> Result<ArtifactDescriptor, PlatformError> {
        let publication = self.local_publication_ref(&artifact)?;
        let mut index = self.index.write().map_err(lock_error)?;
        index.insert(publication, artifact, stamp, self.config)
    }

    #[cfg(test)]
    fn preflight_adoption(&self, artifact: &CapsuleArtifact) -> Result<(), PlatformError> {
        let index = self.index.read().map_err(lock_error)?;
        index.preflight(
            &self.local_publication_ref(artifact)?,
            &artifact.descriptor,
            &artifact.manifest,
            self.config,
        )
    }

    fn prepare_publication(
        &self,
        mut artifact: CapsuleArtifact,
    ) -> Result<PreparedPublication, PlatformError> {
        lifecycle::input::check(&artifact, self.config)?;
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
        self.validate_descriptor_bounds(&artifact.descriptor)?;
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

    fn stage_publication_with_admission(
        &self,
        prepared: &PreparedPublication,
        admission: Option<&admission_storage::PreparedAdmissionFiles>,
    ) -> Result<PathBuf, PlatformError> {
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
            let completion = prepared.completion.encode()?;
            let files = self.publication_content_files(prepared, admission, &completion)?;
            let mut content = self.content.lock().map_err(lock_error)?;
            for (name, bytes) in files {
                content.link_bytes(&tmp_path.join(name), bytes)?;
            }
            sync_dir(&tmp_path)
        })();
        if let Err(failure) = staged {
            let _ = fs::remove_dir_all(&tmp_path);
            return Err(failure);
        }
        Ok(tmp_path)
    }

    #[cfg(test)]
    fn inject_parent_sync_failure_once(&self) {
        self.fail_parent_sync_once.store(true, Ordering::SeqCst);
    }
}

impl ArtifactRepository for DirectoryArtifactRepository {
    fn get_selected_catalog_entry<'a>(
        &'a self,
        scope: &'a crate::LifecycleScope,
        selector: &'a crate::PublicationSelector,
    ) -> BoxFuture<'a, Result<Option<crate::ArtifactCatalogEntry>, PlatformError>> {
        Box::pin(async move {
            self.resolve_publication(scope, selector)?
                .as_ref()
                .map(|reference| self.publication_catalog_entry(reference))
                .transpose()
                .map(Option::flatten)
        })
    }
    fn get_selected_lifecycle<'a>(
        &'a self,
        scope: &'a crate::LifecycleScope,
        selector: &'a crate::PublicationSelector,
    ) -> BoxFuture<'a, Result<Option<crate::ReleaseLifecycleStatus>, PlatformError>> {
        Box::pin(async move {
            self.resolve_publication(scope, selector)?
                .as_ref()
                .map(|reference| self.publication_lifecycle_status(reference))
                .transpose()
                .map(Option::flatten)
        })
    }
    fn get_selected_operation<'a>(
        &'a self,
        scope: &'a crate::LifecycleScope,
        operation_id: &'a str,
    ) -> BoxFuture<
        'a,
        Result<
            (
                Option<latent_core::PublicationId>,
                crate::ReleaseOperationLookup,
            ),
            PlatformError,
        >,
    > {
        Box::pin(async move { self.life_store().selected_operation(scope, operation_id) })
    }
    fn select_web_publication(
        &self,
        reference: &crate::PublicationRef,
    ) -> Result<crate::web::WebSelection, PlatformError> {
        DirectoryArtifactRepository::select_web_publication(self, reference)
    }

    fn get_web_operation<'a>(
        &'a self,
        scope: &'a crate::LifecycleScope,
        operation_id: &'a str,
    ) -> BoxFuture<'a, Result<Option<crate::web::WebOperationReceipt>, PlatformError>> {
        Box::pin(async move { self.web_operation_status(scope, operation_id) })
    }
    fn change_selected_lifecycle<'a>(
        &'a self,
        context: crate::ReleaseMutationContext,
        selector: &'a crate::PublicationSelector,
        action: crate::ReleaseLifecycleAction,
        reason: crate::ReleaseLifecycleReason,
        preflight: &'a mut (dyn for<'p> FnMut(crate::ReleaseOperationPreview<'p>) -> Result<(), PlatformError>
                     + Send),
    ) -> BoxFuture<'a, Result<crate::PublicationOperationReceipt, PlatformError>> {
        Box::pin(async move {
            let mut publication = None;
            let operation = self.change_publication_lifecycle(
                context,
                selector,
                action,
                reason,
                &mut |preview| {
                    preflight(preview)?;
                    publication = preview.publication.cloned();
                    Ok(())
                },
            )?;
            Ok(crate::PublicationOperationReceipt {
                publication,
                operation,
            })
        })
    }
    fn renew_selected_evidence<'a>(
        &'a self,
        context: crate::ReleaseMutationContext,
        selector: &'a crate::PublicationSelector,
        package: &'a latent_core::PackageDigest,
        evidence: crate::ReleaseEvidenceUpload,
        preflight: &'a mut (dyn for<'p> FnMut(crate::ReleaseOperationPreview<'p>) -> Result<(), PlatformError>
                     + Send),
    ) -> BoxFuture<'a, Result<crate::PublicationOperationReceipt, PlatformError>> {
        Box::pin(async move {
            let mut publication = None;
            let operation = self.renew_publication_evidence(
                context,
                selector,
                package,
                evidence,
                &mut |preview| {
                    preflight(preview)?;
                    publication = preview.publication.cloned();
                    Ok(())
                },
            )?;
            Ok(crate::PublicationOperationReceipt {
                publication,
                operation,
            })
        })
    }
    fn retained_package_source<'a>(
        &'a self,
        tenant: &'a latent_core::TenantId,
        release: &'a ReleaseDigest,
        maximum_bytes: usize,
    ) -> BoxFuture<'a, Result<Option<crate::RetainedPackageSource>, PlatformError>> {
        Box::pin(async move { self.retained_package(tenant, release, maximum_bytes) })
    }
    fn execution_eligibility(
        &self,
        release: &ReleaseDigest,
    ) -> Result<Option<crate::ReleaseUseEligibility>, PlatformError> {
        self.current_execution_eligibility(release).map(Some)
    }
    fn historical_execution_snapshot<'a>(
        &'a self,
        release: &'a ReleaseDigest,
    ) -> BoxFuture<'a, Result<crate::HistoricalExecutionSnapshot, PlatformError>> {
        Box::pin(async move { self.historical_snapshot(release) })
    }
    fn publish_managed<'a>(
        &'a self,
        context: crate::ReleaseMutationContext,
        upload: crate::ManagedPublicationUpload,
        preflight: &'a mut (dyn for<'p> FnMut(crate::ReleaseOperationPreview<'p>) -> Result<(), PlatformError>
                     + Send),
    ) -> BoxFuture<'a, Result<crate::ManagedPublicationReceipt, PlatformError>> {
        Box::pin(async move { self.managed_publish(context, upload, preflight) })
    }
    fn get_release_lifecycle<'a>(
        &'a self,
        scope: &'a crate::LifecycleScope,
        release: &'a ReleaseDigest,
    ) -> BoxFuture<'a, Result<Option<crate::ReleaseLifecycleStatus>, PlatformError>> {
        Box::pin(async move { self.lifecycle_status(scope, release) })
    }
    fn get_release_operation<'a>(
        &'a self,
        scope: &'a crate::LifecycleScope,
        operation_id: &'a str,
    ) -> BoxFuture<'a, Result<crate::ReleaseOperationLookup, PlatformError>> {
        Box::pin(async move { self.life_store().operation(scope, operation_id) })
    }
    fn change_release_lifecycle<'a>(
        &'a self,
        context: crate::ReleaseMutationContext,
        release: &'a ReleaseDigest,
        action: crate::ReleaseLifecycleAction,
        reason: crate::ReleaseLifecycleReason,
        preflight: &'a mut (dyn for<'p> FnMut(crate::ReleaseOperationPreview<'p>) -> Result<(), PlatformError>
                     + Send),
    ) -> BoxFuture<'a, Result<crate::ReleaseOperationReceipt, PlatformError>> {
        Box::pin(async move { self.change_lifecycle(context, release, action, reason, preflight) })
    }
    fn renew_release_evidence<'a>(
        &'a self,
        context: crate::ReleaseMutationContext,
        release: &'a ReleaseDigest,
        package: &'a latent_core::PackageDigest,
        evidence: crate::ReleaseEvidenceUpload,
        preflight: &'a mut (dyn for<'p> FnMut(crate::ReleaseOperationPreview<'p>) -> Result<(), PlatformError>
                     + Send),
    ) -> BoxFuture<'a, Result<crate::ReleaseOperationReceipt, PlatformError>> {
        Box::pin(async move { self.renew_evidence(context, release, package, evidence, preflight) })
    }
    fn release_eligibility(
        &self,
        release: &ReleaseDigest,
    ) -> Result<Option<crate::ReleaseEligibility>, PlatformError> {
        self.current_eligibility(release)
    }

    fn admit_package<'a>(
        &'a self,
        tenant: &'a latent_core::TenantId,
        upload: crate::PackageAdmissionUpload,
        preflight: &'a mut (dyn FnMut(&crate::ArtifactCatalogEntry) -> Result<(), PlatformError>
                     + Send),
    ) -> BoxFuture<'a, Result<crate::ArtifactCatalogEntry, PlatformError>> {
        Box::pin(async move { self.admit_legacy(tenant, upload, preflight) })
    }
    fn owned_preparation_source(self: Arc<Self>) -> Option<OwnedArtifactPreparationSource> {
        Some(OwnedArtifactPreparationSource::new(self))
    }

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
                index.legacy_component(None, digest)?
            } else if let Some(reference) = &query.reference {
                index.legacy_reference(None, reference)?
            } else {
                None
            };
            let value = descriptor
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
                .cloned();
            drop(index);
            if let Some(descriptor) = &value {
                self.current_eligibility(&descriptor.release_digest)?;
            }
            Ok(value)
        })
    }

    fn fetch<'a>(
        &'a self,
        digest: &'a ReleaseDigest,
    ) -> BoxFuture<'a, Result<CapsuleArtifact, PlatformError>> {
        Box::pin(async move { self.fetch_with_limits(digest, self.repository_read_limits()) })
    }

    fn fetch_verified_metadata<'a>(
        &'a self,
        digest: &'a ReleaseDigest,
    ) -> BoxFuture<'a, Result<VerifiedArtifactMetadata, PlatformError>> {
        Box::pin(async move {
            self.current_eligibility(digest)?;
            add(&self.verification_statistics.metadata_fetch_attempts, 1);
            if !self
                .index
                .read()
                .map_err(lock_error)?
                .legacy_component(None, digest)?
                .is_some()
            {
                return Err(error(
                    PlatformErrorCode::NotFound,
                    "release digest not found",
                ));
            }
            let verified =
                self.load_complete_entry(&self.entry_path(digest)?, Retention::Metadata)?;
            self.verify_admission_index(digest, &verified)?;
            verified.metadata.verify_requested(digest)?;
            self.current_eligibility(digest)?;
            Ok(verified.metadata)
        })
    }

    fn publish<'a>(
        &'a self,
        artifact: CapsuleArtifact,
    ) -> BoxFuture<'a, Result<ArtifactDescriptor, PlatformError>> {
        Box::pin(async move { self.publish_legacy(artifact) })
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
            for (component, rows) in index
                .component_rows()
                .range((after.map_or(Unbounded, Excluded), Unbounded))
            {
                if rows.is_empty() {
                    continue;
                }
                let descriptor = index
                    .legacy_component(None, component)?
                    .expect("indexed component");
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
    if config.max_storage_bytes == 0
        || config.max_content_index_bytes == 0
        || config.max_content_blobs == 0
        || config.max_content_blobs > 1_000_000
        || config.max_publication_files == 0
        || config.max_publication_files > 1024
        || config.max_index_entries == 0
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
