use std::collections::BTreeMap;
use std::fs::{self, File, OpenOptions};
use std::io::{Read, Write};
use std::path::{Path, PathBuf};
use std::sync::{Mutex, RwLock};
use std::time::{SystemTime, UNIX_EPOCH};

use latent_contracts::ContractDescriptor;
use latent_core::{
    ArtifactReference, BoxFuture, PlatformError, PlatformErrorCode, ReleaseDigest,
};
use latent_manifest::{
    JsonManifestCodec, ManifestCodec, ManifestValidator, Phase1ManifestValidator,
};
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};

use crate::{
    ArtifactDescriptor, ArtifactPage, ArtifactQuery, ArtifactRepository, CapsuleArtifact,
};

const RELEASES_DIR: &str = "releases";
const TEMP_DIR: &str = ".tmp";
const METADATA_FILE: &str = "metadata.json";
const MANIFEST_FILE: &str = "manifest.json";
const COMPONENT_FILE: &str = "component.wasm";
const COMPLETE_FILE: &str = "COMPLETE";
const DEFAULT_MAX_INDEX_ENTRIES: usize = 250_000;
const DEFAULT_MAX_PAGE_SIZE: usize = 1_000;

/// Directory repository limits. The in-memory index never exceeds
/// `max_index_entries`; callers cannot request more than `max_page_size` rows.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct DirectoryArtifactRepositoryConfig {
    pub max_index_entries: usize,
    pub max_page_size: usize,
}

impl Default for DirectoryArtifactRepositoryConfig {
    fn default() -> Self {
        Self {
            max_index_entries: DEFAULT_MAX_INDEX_ENTRIES,
            max_page_size: DEFAULT_MAX_PAGE_SIZE,
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
struct StoredMetadata {
    descriptor: ArtifactDescriptor,
    contracts: Vec<ContractDescriptor>,
}

#[derive(Debug, Default)]
struct CatalogIndex {
    by_digest: BTreeMap<ReleaseDigest, ArtifactDescriptor>,
    by_reference: BTreeMap<ArtifactReference, ReleaseDigest>,
}

/// Crash-safe local trusted release catalog for standalone `latentd`.
///
/// Phase 1 trust is intentionally local: this repository verifies content
/// digests and validated manifests, but does not verify signatures,
/// provenance, SBOMs, or registry identities.
pub struct DirectoryArtifactRepository {
    root: PathBuf,
    config: DirectoryArtifactRepositoryConfig,
    codec: JsonManifestCodec,
    validator: Phase1ManifestValidator,
    index: RwLock<CatalogIndex>,
    publish_lock: Mutex<()>,
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
        if config.max_index_entries == 0 || config.max_page_size == 0 {
            return Err(error(
                PlatformErrorCode::InvalidArgument,
                "catalog bounds must be greater than zero",
            ));
        }

        let root = root.into();
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
        let mut entries = Vec::new();
        for entry in fs::read_dir(releases).map_err(io_error)? {
            let entry = entry.map_err(io_error)?;
            if entry.file_type().map_err(io_error)?.is_dir() {
                entries.push(entry.path());
            }
        }
        entries.sort();
        if entries.len() > self.config.max_index_entries {
            return Err(error(
                PlatformErrorCode::ResourceExhausted,
                "catalog contains more releases than the configured index bound",
            ));
        }

        let mut next = CatalogIndex::default();
        for path in entries {
            if !path.join(COMPLETE_FILE).is_file() {
                continue;
            }
            let artifact = self.load_complete_entry(&path)?;
            if next
                .by_digest
                .insert(
                    artifact.descriptor.release_digest.clone(),
                    artifact.descriptor.clone(),
                )
                .is_some()
            {
                return Err(corrupt("duplicate release digest while rebuilding catalog"));
            }
            next.by_reference.insert(
                artifact.descriptor.reference.clone(),
                artifact.descriptor.release_digest.clone(),
            );
        }
        *self.index.write().map_err(lock_error)? = next;
        Ok(())
    }

    fn load_complete_entry(&self, path: &Path) -> Result<CapsuleArtifact, PlatformError> {
        if !path.join(COMPLETE_FILE).is_file() {
            return Err(corrupt("release entry is incomplete"));
        }
        let metadata_bytes = read_file(&path.join(METADATA_FILE))?;
        let stored: StoredMetadata =
            serde_json::from_slice(&metadata_bytes).map_err(|_| corrupt("invalid catalog metadata"))?;
        let manifest_bytes = read_file(&path.join(MANIFEST_FILE))?;
        let component_bytes = read_file(&path.join(COMPONENT_FILE))?;
        let manifest = self
            .codec
            .decode_capsule(&manifest_bytes)
            .map_err(|_| corrupt("stored capsule manifest is invalid"))?;
        self.validator
            .validate_capsule(&manifest)
            .map_err(|_| corrupt("stored capsule manifest violates Phase 1 rules"))?;
        verify_component_identity(&stored.descriptor, &manifest.component_digest, &component_bytes)?;
        let expected_dir = digest_hex(&stored.descriptor.release_digest)?;
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
            descriptor: stored.descriptor,
            manifest,
            contracts: stored.contracts,
            component_bytes,
        })
    }

    fn entry_path(&self, digest: &ReleaseDigest) -> Result<PathBuf, PlatformError> {
        Ok(self.root.join(RELEASES_DIR).join(digest_hex(digest)?))
    }

    fn publish_sync(&self, artifact: CapsuleArtifact) -> Result<ArtifactDescriptor, PlatformError> {
        let _guard = self.publish_lock.lock().map_err(lock_error)?;
        self.validator
            .validate_capsule(&artifact.manifest)
            .map_err(|_| error(PlatformErrorCode::InvalidArgument, "capsule manifest validation failed"))?;
        let manifest_bytes = self
            .codec
            .encode_capsule(&artifact.manifest)
            .map_err(|_| error(PlatformErrorCode::InvalidArgument, "capsule manifest encoding failed"))?;
        verify_component_identity(
            &artifact.descriptor,
            &artifact.manifest.component_digest,
            &artifact.component_bytes,
        )?;

        let existing_path = self.entry_path(&artifact.descriptor.release_digest)?;
        if existing_path.exists() {
            let existing = self.load_complete_entry(&existing_path)?;
            if existing == artifact {
                return Ok(existing.descriptor);
            }
            return Err(error(
                PlatformErrorCode::AlreadyExists,
                "release digest already contains different catalog content",
            ));
        }

        {
            let index = self.index.read().map_err(lock_error)?;
            if index.by_digest.len() >= self.config.max_index_entries {
                return Err(error(
                    PlatformErrorCode::ResourceExhausted,
                    "catalog index limit reached",
                ));
            }
            if let Some(existing_digest) = index.by_reference.get(&artifact.descriptor.reference) {
                if existing_digest != &artifact.descriptor.release_digest {
                    return Err(error(
                        PlatformErrorCode::AlreadyExists,
                        "artifact reference already resolves to another release",
                    ));
                }
            }
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

        let stored = StoredMetadata {
            descriptor: artifact.descriptor.clone(),
            contracts: artifact.contracts.clone(),
        };
        let metadata_bytes = serde_json::to_vec(&stored)
            .map_err(|_| error(PlatformErrorCode::Internal, "failed to serialize catalog metadata"))?;

        let write_result = (|| {
            write_synced(&tmp_path.join(METADATA_FILE), &metadata_bytes)?;
            write_synced(&tmp_path.join(MANIFEST_FILE), &manifest_bytes)?;
            write_synced(&tmp_path.join(COMPONENT_FILE), &artifact.component_bytes)?;
            write_synced(&tmp_path.join(COMPLETE_FILE), b"complete\n")?;
            sync_dir(&tmp_path)?;
            fs::rename(&tmp_path, &existing_path).map_err(io_error)?;
            sync_dir(&self.root.join(RELEASES_DIR))?;
            Ok::<(), PlatformError>(())
        })();
        if let Err(failure) = write_result {
            let _ = fs::remove_dir_all(&tmp_path);
            if existing_path.exists() {
                let existing = self.load_complete_entry(&existing_path)?;
                if existing == artifact {
                    return Ok(existing.descriptor);
                }
            }
            return Err(failure);
        }

        let mut index = self.index.write().map_err(lock_error)?;
        index.by_reference.insert(
            artifact.descriptor.reference.clone(),
            artifact.descriptor.release_digest.clone(),
        );
        index.by_digest.insert(
            artifact.descriptor.release_digest.clone(),
            artifact.descriptor.clone(),
        );
        Ok(artifact.descriptor)
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
                    query
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
                return Err(error(PlatformErrorCode::InvalidArgument, "list limit must be greater than zero"));
            }
            let limit = limit.min(self.config.max_page_size);
            let index = self.index.read().map_err(lock_error)?;
            let mut values = index
                .by_digest
                .iter()
                .filter(|(digest, _)| after.is_none_or(|cursor| *digest > cursor))
                .take(limit + 1)
                .map(|(_, descriptor)| descriptor.clone())
                .collect::<Vec<_>>();
            let has_more = values.len() > limit;
            if has_more {
                values.pop();
            }
            let next_after = has_more
                .then(|| values.last().map(|value| value.release_digest.clone()))
                .flatten();
            Ok(ArtifactPage {
                entries: values,
                next_after,
            })
        })
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
    let actual = ReleaseDigest(format!("sha256:{}", hex_digest(component_bytes)));
    if &actual != manifest_digest || &actual != &descriptor.release_digest {
        return Err(corrupt(
            "manifest, release, and component content digests must agree",
        ));
    }
    if descriptor.size_bytes != component_bytes.len() as u64 {
        return Err(corrupt("artifact descriptor size does not match component bytes"));
    }
    Ok(())
}

fn digest_hex(digest: &ReleaseDigest) -> Result<String, PlatformError> {
    let Some(hex) = digest.0.strip_prefix("sha256:") else {
        return Err(corrupt("release digest must use sha256"));
    };
    if hex.len() != 64 || !hex.bytes().all(|byte| byte.is_ascii_hexdigit()) {
        return Err(corrupt("release digest must contain 64 hexadecimal characters"));
    }
    Ok(hex.to_ascii_lowercase())
}

fn hex_digest(bytes: &[u8]) -> String {
    let digest = Sha256::digest(bytes);
    digest.iter().map(|byte| format!("{byte:02x}")).collect()
}

fn read_file(path: &Path) -> Result<Vec<u8>, PlatformError> {
    let mut file = File::open(path).map_err(io_error)?;
    let mut bytes = Vec::new();
    file.read_to_end(&mut bytes).map_err(io_error)?;
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
    File::open(path).and_then(|file| file.sync_all()).map_err(io_error)
}

fn io_error(error_value: std::io::Error) -> PlatformError {
    error(
        PlatformErrorCode::Internal,
        format!("catalog filesystem operation failed: {error_value}"),
    )
}

fn lock_error<T>(_: std::sync::PoisonError<T>) -> PlatformError {
    error(PlatformErrorCode::Internal, "catalog synchronization primitive was poisoned")
}

fn corrupt(message: impl Into<String>) -> PlatformError {
    error(PlatformErrorCode::CorruptArtifact, message)
}

fn error(code: PlatformErrorCode, message: impl Into<String>) -> PlatformError {
    PlatformError {
        code,
        message: message.into(),
        retryable: false,
        details: Vec::new(),
    }
}
