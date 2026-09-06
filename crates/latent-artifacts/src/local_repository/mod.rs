mod metadata;
mod sha256;

#[cfg(test)]
mod tests;

use std::collections::BTreeMap;
use std::fs::{self, File, OpenOptions};
use std::io::{Read, Write};
use std::path::{Path, PathBuf};
use std::sync::{Mutex, RwLock};
use std::time::{SystemTime, UNIX_EPOCH};

#[cfg(test)]
use std::sync::atomic::{AtomicBool, Ordering};

use latent_contracts::ContractDescriptor;
use latent_core::{
    ArtifactReference, BoxFuture, PlatformError, PlatformErrorCode, ReleaseDigest,
};
use latent_manifest::{
    __serde_json as serde_json, JsonManifestCodec, ManifestCodec, ManifestValidator,
    Phase1ManifestValidator,
};

use crate::{
    ArtifactDescriptor, ArtifactPage, ArtifactQuery, ArtifactRepository, CapsuleArtifact,
};
use metadata::{StoredArtifactDescriptor, StoredContractDescriptor, StoredMetadata};
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
const INDEX_ACCOUNTING_MULTIPLIER: usize = 4;
const INDEX_ACCOUNTING_FIXED_BYTES: usize = 1_024;

/// Explicit catalog resource bounds.
///
/// `max_index_bytes` bounds a conservative accounting value for all retained
/// descriptors and reference keys. `max_descriptor_bytes` and `max_page_bytes`
/// bound individual and aggregate list payload materialization. Persisted
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
    /// Separate startup scan bound. Incomplete directories do not consume the
    /// completed-release index quota.
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
struct CatalogIndex {
    by_digest: BTreeMap<ReleaseDigest, ArtifactDescriptor>,
    by_reference: BTreeMap<ArtifactReference, ReleaseDigest>,
    accounted_bytes: usize,
}

impl CatalogIndex {
    fn insert(
        &mut self,
        descriptor: ArtifactDescriptor,
        descriptor_bytes: usize,
        config: DirectoryArtifactRepositoryConfig,
    ) -> Result<(), PlatformError> {
        if let Some(existing) = self.by_digest.get(&descriptor.release_digest) {
            if existing == &descriptor {
                return Ok(());
            }
            return Err(corrupt("duplicate release digest has conflicting metadata"));
        }
        if let Some(existing_digest) = self.by_reference.get(&descriptor.reference) {
            if existing_digest != &descriptor.release_digest {
                return Err(corrupt(
                    "artifact reference maps to conflicting release digests",
                ));
            }
        }
        if self.by_digest.len() >= config.max_index_entries {
            return Err(resource_exhausted("catalog index entry limit reached"));
        }
        let accounted = index_accounted_bytes(descriptor_bytes)?;
        let next_bytes = self
            .accounted_bytes
            .checked_add(accounted)
            .ok_or_else(|| resource_exhausted("catalog index byte accounting overflow"))?;
        if next_bytes > config.max_index_bytes {
            return Err(resource_exhausted("catalog index byte limit reached"));
        }

        self.by_reference.insert(
            descriptor.reference.clone(),
            descriptor.release_digest.clone(),
        );
        self.by_digest
            .insert(descriptor.release_digest.clone(), descriptor);
        self.accounted_bytes = next_bytes;
        Ok(())
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
    publish_lock: Mutex<()>,
    _owner_lock: File,
    #[cfg(test)]
    fail_parent_sync_once: AtomicBool,
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
        fs::create_dir_all(&root).map_err(io_error)?;

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

        fs::create_dir_all(root.join(RELEASES_DIR)).map_err(io_error)?;
        fs::create_dir_all(root.join(TEMP_DIR)).map_err(io_error)?;
        cleanup_temporary_entries(&root)?;

        let repository = Self {
            root,
            config,
            codec: JsonManifestCodec::default(),
            validator: Phase1ManifestValidator::new(),
            index: RwLock::new(CatalogIndex::default()),
            publish_lock: Mutex::new(()),
            _owner_lock: owner_lock,
            #[cfg(test)]
            fail_parent_sync_once: AtomicBool::new(false),
        };
        repository.rebuild_index()?;
        Ok(repository)
    }

    #[must_use]
    pub fn root(&self) -> &Path {
        &self.root
    }

    fn rebuild_index(&self) -> Result<(), PlatformError> {
        let releases = self.root.join(RELEASES_DIR);
        let mut complete_entries = Vec::new();
        let mut scanned = 0_usize;
        for entry in fs::read_dir(releases).map_err(io_error)? {
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
            if !path.join(COMPLETE_FILE).is_file() {
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
            let artifact = self.load_complete_entry(&path)?;
            let descriptor_bytes = self.validate_descriptor_bounds(&artifact.descriptor)?;
            next.insert(artifact.descriptor, descriptor_bytes, self.config)?;
        }
        *self.index.write().map_err(lock_error)? = next;
        Ok(())
    }

    fn load_complete_entry(&self, path: &Path) -> Result<CapsuleArtifact, PlatformError> {
        if !path.join(COMPLETE_FILE).is_file() {
            return Err(corrupt("release entry is incomplete"));
        }
        let metadata_bytes = read_bounded_file(
            &path.join(METADATA_FILE),
            self.config.max_metadata_bytes,
            "catalog metadata",
        )?;
        let stored: StoredMetadata = serde_json::from_slice(&metadata_bytes)
            .map_err(|_| corrupt("invalid catalog metadata"))?;
        let descriptor = ArtifactDescriptor::from(stored.descriptor);
        self.validate_descriptor_bounds(&descriptor)?;
        if descriptor.size_bytes > self.config.max_component_bytes as u64 {
            return Err(resource_exhausted(
                "stored component exceeds configured component byte limit",
            ));
        }
        let contracts = stored
            .contracts
            .into_iter()
            .map(ContractDescriptor::from)
            .collect::<Vec<_>>();
        let manifest_bytes = read_bounded_file(
            &path.join(MANIFEST_FILE),
            self.codec.limits().max_document_bytes,
            "capsule manifest",
        )?;
        let component_bytes = read_bounded_file(
            &path.join(COMPONENT_FILE),
            self.config.max_component_bytes,
            "component artifact",
        )?;
        let manifest = self
            .codec
            .decode_capsule(&manifest_bytes)
            .map_err(|_| corrupt("stored capsule manifest is invalid"))?;
        self.validator
            .validate_capsule(&manifest)
            .map_err(|_| corrupt("stored capsule manifest violates Phase 1 rules"))?;
        verify_component_identity(&descriptor, &manifest.component_digest, &component_bytes)?;
        let expected_dir = digest_hex(&descriptor.release_digest)?;
        if path.file_name().and_then(|value| value.to_str()) != Some(expected_dir.as_str()) {
            return Err(corrupt("release directory does not match its digest"));
        }
        let canonical = self
            .codec
            .encode_capsule(&manifest)
            .map_err(|_| corrupt("stored capsule manifest cannot be canonicalized"))?;
        if canonical != manifest_bytes {
            return Err(corrupt("stored capsule manifest is not canonical"));
        }
        Ok(CapsuleArtifact {
            descriptor,
            manifest,
            contracts,
            component_bytes,
        })
    }

    fn entry_path(&self, digest: &ReleaseDigest) -> Result<PathBuf, PlatformError> {
        Ok(self.root.join(RELEASES_DIR).join(digest_hex(digest)?))
    }

    fn validate_descriptor_bounds(
        &self,
        descriptor: &ArtifactDescriptor,
    ) -> Result<usize, PlatformError> {
        let bytes = serde_json::to_vec(&StoredArtifactDescriptor::from(descriptor)).map_err(|_| {
            error(
                PlatformErrorCode::Internal,
                "failed to serialize artifact descriptor for bound accounting",
            )
        })?;
        if bytes.len() > self.config.max_descriptor_bytes {
            return Err(resource_exhausted(
                "artifact descriptor exceeds configured byte limit",
            ));
        }
        Ok(bytes.len())
    }

    fn finalize_adoption(
        &self,
        descriptor: ArtifactDescriptor,
    ) -> Result<ArtifactDescriptor, PlatformError> {
        let descriptor_bytes = self.validate_descriptor_bounds(&descriptor)?;
        let mut index = self.index.write().map_err(lock_error)?;
        index.insert(descriptor.clone(), descriptor_bytes, self.config)?;
        Ok(descriptor)
    }

    fn preflight_adoption(&self, descriptor: &ArtifactDescriptor) -> Result<(), PlatformError> {
        let descriptor_bytes = self.validate_descriptor_bounds(descriptor)?;
        let index = self.index.read().map_err(lock_error)?;
        if let Some(existing) = index.by_digest.get(&descriptor.release_digest) {
            if existing == descriptor {
                return Ok(());
            }
            return Err(error(
                PlatformErrorCode::AlreadyExists,
                "release digest already indexes different catalog metadata",
            ));
        }
        if let Some(existing_digest) = index.by_reference.get(&descriptor.reference) {
            if existing_digest != &descriptor.release_digest {
                return Err(error(
                    PlatformErrorCode::AlreadyExists,
                    "artifact reference already resolves to another release",
                ));
            }
        }
        if index.by_digest.len() >= self.config.max_index_entries {
            return Err(resource_exhausted("catalog index entry limit reached"));
        }
        let accounted = index_accounted_bytes(descriptor_bytes)?;
        if index.accounted_bytes.saturating_add(accounted) > self.config.max_index_bytes {
            return Err(resource_exhausted("catalog index byte limit reached"));
        }
        Ok(())
    }

    fn publish_sync(&self, artifact: CapsuleArtifact) -> Result<ArtifactDescriptor, PlatformError> {
        let _guard = self.publish_lock.lock().map_err(lock_error)?;
        self.validator
            .validate_capsule(&artifact.manifest)
            .map_err(|_| error(PlatformErrorCode::InvalidArgument, "capsule manifest validation failed"))?;
        let manifest_bytes = self.codec.encode_capsule(&artifact.manifest).map_err(|_| {
            error(
                PlatformErrorCode::InvalidArgument,
                "capsule manifest encoding failed",
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
        self.preflight_adoption(&artifact.descriptor)?;

        let stored = StoredMetadata {
            descriptor: StoredArtifactDescriptor::from(&artifact.descriptor),
            contracts: artifact
                .contracts
                .iter()
                .map(StoredContractDescriptor::from)
                .collect(),
        };
        let metadata_bytes = serde_json::to_vec(&stored).map_err(|_| {
            error(
                PlatformErrorCode::Internal,
                "failed to serialize catalog metadata",
            )
        })?;
        if metadata_bytes.len() > self.config.max_metadata_bytes {
            return Err(resource_exhausted(
                "catalog metadata exceeds configured byte limit",
            ));
        }

        let releases_dir = self.root.join(RELEASES_DIR);
        let destination = self.entry_path(&artifact.descriptor.release_digest)?;
        if destination.exists() {
            let existing = self.load_complete_entry(&destination)?;
            if existing != artifact {
                return Err(error(
                    PlatformErrorCode::AlreadyExists,
                    "release digest already contains different catalog content",
                ));
            }
            // An existing identical destination may be the residue of a prior
            // post-rename durability failure. Re-sync the parent before adoption.
            sync_dir(&releases_dir)?;
            return self.finalize_adoption(existing.descriptor);
        }

        let nonce = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .map_err(|_| error(PlatformErrorCode::Internal, "system clock is before Unix epoch"))?
            .as_nanos();
        let tmp_path = self.root.join(TEMP_DIR).join(format!(
            "{}-{}-{nonce}",
            std::process::id(),
            digest_hex(&artifact.descriptor.release_digest)?
        ));
        fs::create_dir(&tmp_path).map_err(io_error)?;

        let staged = (|| {
            write_synced(&tmp_path.join(METADATA_FILE), &metadata_bytes)?;
            write_synced(&tmp_path.join(MANIFEST_FILE), &manifest_bytes)?;
            write_synced(&tmp_path.join(COMPONENT_FILE), &artifact.component_bytes)?;
            write_synced(&tmp_path.join(COMPLETE_FILE), b"complete\n")?;
            sync_dir(&tmp_path)
        })();
        if let Err(failure) = staged {
            let _ = fs::remove_dir_all(&tmp_path);
            return Err(failure);
        }

        if let Err(rename_failure) = fs::rename(&tmp_path, &destination).map_err(io_error) {
            let _ = fs::remove_dir_all(&tmp_path);
            if destination.exists() {
                let existing = self.load_complete_entry(&destination)?;
                if existing == artifact {
                    sync_dir(&releases_dir)?;
                    return self.finalize_adoption(existing.descriptor);
                }
                return Err(error(
                    PlatformErrorCode::AlreadyExists,
                    "release digest was externally published with different content",
                ));
            }
            return Err(rename_failure);
        }

        #[cfg(test)]
        if self.fail_parent_sync_once.swap(false, Ordering::SeqCst) {
            return Err(error(
                PlatformErrorCode::Internal,
                "injected parent-directory sync failure after rename",
            ));
        }
        // A failure here is a failure. The completed directory is intentionally
        // left in place so a retry can re-sync and durably adopt it.
        sync_dir(&releases_dir)?;
        self.finalize_adoption(artifact.descriptor)
    }

    #[cfg(test)]
    fn inject_parent_sync_failure_once(&self) {
        self.fail_parent_sync_once.store(true, Ordering::SeqCst);
    }

    #[cfg(test)]
    fn register_durable_descriptor_for_acceptance(
        &self,
        descriptor: ArtifactDescriptor,
    ) -> Result<(), PlatformError> {
        self.preflight_adoption(&descriptor)?;
        self.finalize_adoption(descriptor).map(|_| ())
    }
}

impl ArtifactRepository for DirectoryArtifactRepository {
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
                .filter(|value| {
                    query.reference.as_ref().is_none_or(|reference| &value.reference == reference)
                        && query.media_type.as_ref().is_none_or(|media_type| &value.media_type == media_type)
                })
                .cloned())
        })
    }

    fn fetch<'a>(
        &'a self,
        digest: &'a ReleaseDigest,
    ) -> BoxFuture<'a, Result<CapsuleArtifact, PlatformError>> {
        Box::pin(async move {
            if !self.index.read().map_err(lock_error)?.by_digest.contains_key(digest) {
                return Err(error(PlatformErrorCode::NotFound, "release digest not found"));
            }
            self.load_complete_entry(&self.entry_path(digest)?)
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
            for (digest, descriptor) in index
                .by_digest
                .iter()
                .filter(|(digest, _)| after.is_none_or(|cursor| *digest > cursor))
            {
                if entries.len() >= entry_limit {
                    has_more = true;
                    break;
                }
                let descriptor_bytes = self.validate_descriptor_bounds(descriptor)?;
                if response_bytes.saturating_add(descriptor_bytes) > self.config.max_page_bytes {
                    has_more = true;
                    break;
                }
                response_bytes = response_bytes.saturating_add(descriptor_bytes);
                entries.push(descriptor.clone());
                let _ = digest;
            }
            let next_after = if has_more {
                entries.last().map(|value| value.release_digest.clone())
            } else {
                None
            };
            Ok(ArtifactPage { entries, next_after })
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
    Ok(())
}

fn index_accounted_bytes(descriptor_bytes: usize) -> Result<usize, PlatformError> {
    descriptor_bytes
        .checked_mul(INDEX_ACCOUNTING_MULTIPLIER)
        .and_then(|value| value.checked_add(INDEX_ACCOUNTING_FIXED_BYTES))
        .ok_or_else(|| resource_exhausted("catalog index byte accounting overflow"))
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
    if &actual != manifest_digest || &actual != &descriptor.release_digest {
        return Err(corrupt(
            "manifest, release, and component content digests must agree",
        ));
    }
    if descriptor.size_bytes != component_bytes.len() as u64 {
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

fn read_bounded_file(
    path: &Path,
    limit: usize,
    label: &str,
) -> Result<Vec<u8>, PlatformError> {
    let mut file = File::open(path).map_err(|_| corrupt("completed release is missing data"))?;
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
    let mut bytes = Vec::with_capacity(capacity);
    file.read_to_end(&mut bytes)
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
