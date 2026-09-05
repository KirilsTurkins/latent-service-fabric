use std::collections::BTreeMap;
use std::fmt::Write as _;
use std::fs::{self, File, OpenOptions};
use std::io::{Read, Write};
use std::path::{Path, PathBuf};
use std::sync::{Mutex, RwLock};
use std::time::{SystemTime, UNIX_EPOCH};

use latent_contracts::{
    ContractDescriptor, FieldDescriptor, FunctionDescriptor, InterfaceDescriptor, ValueType,
};
use latent_core::{
    ArtifactReference, BoxFuture, ContractId, FunctionId, InterfaceId, Metadata, PlatformError,
    PlatformErrorCode, PublisherId, ReleaseDigest,
};
use latent_manifest::__serde::{Deserialize, Serialize};
use latent_manifest::{
    __serde_json as serde_json, JsonManifestCodec, ManifestCodec, ManifestValidator,
    Phase1ManifestValidator,
};

use crate::{
    ArtifactDescriptor, ArtifactLayer, ArtifactPage, ArtifactQuery, ArtifactRepository,
    CapsuleArtifact,
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
#[serde(crate = "latent_manifest::__serde")]
struct StoredMetadata {
    descriptor: StoredArtifactDescriptor,
    contracts: Vec<StoredContractDescriptor>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(crate = "latent_manifest::__serde")]
struct StoredArtifactDescriptor {
    reference: String,
    release_digest: String,
    media_type: String,
    size_bytes: u64,
    publisher: Option<String>,
    layers: Vec<StoredArtifactLayer>,
    annotations: Metadata,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(crate = "latent_manifest::__serde")]
struct StoredArtifactLayer {
    media_type: String,
    digest: String,
    size_bytes: u64,
    annotations: Metadata,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(crate = "latent_manifest::__serde")]
struct StoredContractDescriptor {
    id: String,
    package_name: String,
    semantic_version: String,
    interfaces: Vec<StoredInterfaceDescriptor>,
    dependencies: Vec<String>,
    digest: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(crate = "latent_manifest::__serde")]
struct StoredInterfaceDescriptor {
    id: String,
    functions: Vec<StoredFunctionDescriptor>,
    documentation: Option<String>,
    digest: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(crate = "latent_manifest::__serde")]
struct StoredFunctionDescriptor {
    id: String,
    name: String,
    asynchronous: bool,
    parameters: Vec<StoredFieldDescriptor>,
    results: Vec<StoredFieldDescriptor>,
    documentation: Option<String>,
    attributes: Metadata,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(crate = "latent_manifest::__serde")]
struct StoredFieldDescriptor {
    name: String,
    value_type: StoredValueType,
    documentation: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(crate = "latent_manifest::__serde")]
enum StoredValueType {
    Bool,
    U8,
    U16,
    U32,
    U64,
    S8,
    S16,
    S32,
    S64,
    F32,
    F64,
    Char,
    String,
    Bytes,
    List(Box<StoredValueType>),
    Option(Box<StoredValueType>),
    Result {
        ok: Option<Box<StoredValueType>>,
        error: Option<Box<StoredValueType>>,
    },
    Tuple(Vec<StoredValueType>),
    Record(String),
    Variant(String),
    Resource(String),
    Future(Box<StoredValueType>),
    Stream(Box<StoredValueType>),
}

impl From<&ArtifactDescriptor> for StoredArtifactDescriptor {
    fn from(value: &ArtifactDescriptor) -> Self {
        Self {
            reference: value.reference.0.clone(),
            release_digest: value.release_digest.0.clone(),
            media_type: value.media_type.clone(),
            size_bytes: value.size_bytes,
            publisher: value.publisher.as_ref().map(|publisher| publisher.0.clone()),
            layers: value.layers.iter().map(StoredArtifactLayer::from).collect(),
            annotations: value.annotations.clone(),
        }
    }
}

impl From<StoredArtifactDescriptor> for ArtifactDescriptor {
    fn from(value: StoredArtifactDescriptor) -> Self {
        Self {
            reference: ArtifactReference(value.reference),
            release_digest: ReleaseDigest(value.release_digest),
            media_type: value.media_type,
            size_bytes: value.size_bytes,
            publisher: value.publisher.map(PublisherId),
            layers: value.layers.into_iter().map(ArtifactLayer::from).collect(),
            annotations: value.annotations,
        }
    }
}

impl From<&ArtifactLayer> for StoredArtifactLayer {
    fn from(value: &ArtifactLayer) -> Self {
        Self {
            media_type: value.media_type.clone(),
            digest: value.digest.clone(),
            size_bytes: value.size_bytes,
            annotations: value.annotations.clone(),
        }
    }
}

impl From<StoredArtifactLayer> for ArtifactLayer {
    fn from(value: StoredArtifactLayer) -> Self {
        Self {
            media_type: value.media_type,
            digest: value.digest,
            size_bytes: value.size_bytes,
            annotations: value.annotations,
        }
    }
}

impl From<&ContractDescriptor> for StoredContractDescriptor {
    fn from(value: &ContractDescriptor) -> Self {
        Self {
            id: value.id.0.clone(),
            package_name: value.package_name.clone(),
            semantic_version: value.semantic_version.clone(),
            interfaces: value
                .interfaces
                .iter()
                .map(StoredInterfaceDescriptor::from)
                .collect(),
            dependencies: value
                .dependencies
                .iter()
                .map(|dependency| dependency.0.clone())
                .collect(),
            digest: value.digest.clone(),
        }
    }
}

impl From<StoredContractDescriptor> for ContractDescriptor {
    fn from(value: StoredContractDescriptor) -> Self {
        Self {
            id: ContractId(value.id),
            package_name: value.package_name,
            semantic_version: value.semantic_version,
            interfaces: value
                .interfaces
                .into_iter()
                .map(InterfaceDescriptor::from)
                .collect(),
            dependencies: value.dependencies.into_iter().map(ContractId).collect(),
            digest: value.digest,
        }
    }
}

impl From<&InterfaceDescriptor> for StoredInterfaceDescriptor {
    fn from(value: &InterfaceDescriptor) -> Self {
        Self {
            id: value.id.0.clone(),
            functions: value
                .functions
                .iter()
                .map(StoredFunctionDescriptor::from)
                .collect(),
            documentation: value.documentation.clone(),
            digest: value.digest.clone(),
        }
    }
}

impl From<StoredInterfaceDescriptor> for InterfaceDescriptor {
    fn from(value: StoredInterfaceDescriptor) -> Self {
        Self {
            id: InterfaceId(value.id),
            functions: value
                .functions
                .into_iter()
                .map(FunctionDescriptor::from)
                .collect(),
            documentation: value.documentation,
            digest: value.digest,
        }
    }
}

impl From<&FunctionDescriptor> for StoredFunctionDescriptor {
    fn from(value: &FunctionDescriptor) -> Self {
        Self {
            id: value.id.0.clone(),
            name: value.name.clone(),
            asynchronous: value.asynchronous,
            parameters: value
                .parameters
                .iter()
                .map(StoredFieldDescriptor::from)
                .collect(),
            results: value
                .results
                .iter()
                .map(StoredFieldDescriptor::from)
                .collect(),
            documentation: value.documentation.clone(),
            attributes: value.attributes.clone(),
        }
    }
}

impl From<StoredFunctionDescriptor> for FunctionDescriptor {
    fn from(value: StoredFunctionDescriptor) -> Self {
        Self {
            id: FunctionId(value.id),
            name: value.name,
            asynchronous: value.asynchronous,
            parameters: value
                .parameters
                .into_iter()
                .map(FieldDescriptor::from)
                .collect(),
            results: value
                .results
                .into_iter()
                .map(FieldDescriptor::from)
                .collect(),
            documentation: value.documentation,
            attributes: value.attributes,
        }
    }
}

impl From<&FieldDescriptor> for StoredFieldDescriptor {
    fn from(value: &FieldDescriptor) -> Self {
        Self {
            name: value.name.clone(),
            value_type: StoredValueType::from(&value.value_type),
            documentation: value.documentation.clone(),
        }
    }
}

impl From<StoredFieldDescriptor> for FieldDescriptor {
    fn from(value: StoredFieldDescriptor) -> Self {
        Self {
            name: value.name,
            value_type: ValueType::from(value.value_type),
            documentation: value.documentation,
        }
    }
}

impl From<&ValueType> for StoredValueType {
    fn from(value: &ValueType) -> Self {
        match value {
            ValueType::Bool => Self::Bool,
            ValueType::U8 => Self::U8,
            ValueType::U16 => Self::U16,
            ValueType::U32 => Self::U32,
            ValueType::U64 => Self::U64,
            ValueType::S8 => Self::S8,
            ValueType::S16 => Self::S16,
            ValueType::S32 => Self::S32,
            ValueType::S64 => Self::S64,
            ValueType::F32 => Self::F32,
            ValueType::F64 => Self::F64,
            ValueType::Char => Self::Char,
            ValueType::String => Self::String,
            ValueType::Bytes => Self::Bytes,
            ValueType::List(inner) => Self::List(Box::new(Self::from(inner.as_ref()))),
            ValueType::Option(inner) => Self::Option(Box::new(Self::from(inner.as_ref()))),
            ValueType::Result { ok, error } => Self::Result {
                ok: ok
                    .as_ref()
                    .map(|inner| Box::new(Self::from(inner.as_ref()))),
                error: error
                    .as_ref()
                    .map(|inner| Box::new(Self::from(inner.as_ref()))),
            },
            ValueType::Tuple(values) => Self::Tuple(values.iter().map(Self::from).collect()),
            ValueType::Record(name) => Self::Record(name.clone()),
            ValueType::Variant(name) => Self::Variant(name.clone()),
            ValueType::Resource(name) => Self::Resource(name.clone()),
            ValueType::Future(inner) => Self::Future(Box::new(Self::from(inner.as_ref()))),
            ValueType::Stream(inner) => Self::Stream(Box::new(Self::from(inner.as_ref()))),
        }
    }
}

impl From<StoredValueType> for ValueType {
    fn from(value: StoredValueType) -> Self {
        match value {
            StoredValueType::Bool => Self::Bool,
            StoredValueType::U8 => Self::U8,
            StoredValueType::U16 => Self::U16,
            StoredValueType::U32 => Self::U32,
            StoredValueType::U64 => Self::U64,
            StoredValueType::S8 => Self::S8,
            StoredValueType::S16 => Self::S16,
            StoredValueType::S32 => Self::S32,
            StoredValueType::S64 => Self::S64,
            StoredValueType::F32 => Self::F32,
            StoredValueType::F64 => Self::F64,
            StoredValueType::Char => Self::Char,
            StoredValueType::String => Self::String,
            StoredValueType::Bytes => Self::Bytes,
            StoredValueType::List(inner) => Self::List(Box::new(Self::from(*inner))),
            StoredValueType::Option(inner) => Self::Option(Box::new(Self::from(*inner))),
            StoredValueType::Result { ok, error } => Self::Result {
                ok: ok.map(|inner| Box::new(Self::from(*inner))),
                error: error.map(|inner| Box::new(Self::from(*inner))),
            },
            StoredValueType::Tuple(values) => {
                Self::Tuple(values.into_iter().map(Self::from).collect())
            }
            StoredValueType::Record(name) => Self::Record(name),
            StoredValueType::Variant(name) => Self::Variant(name),
            StoredValueType::Resource(name) => Self::Resource(name),
            StoredValueType::Future(inner) => Self::Future(Box::new(Self::from(*inner))),
            StoredValueType::Stream(inner) => Self::Stream(Box::new(Self::from(*inner))),
        }
    }
}

#[derive(Debug, Default)]
struct CatalogIndex {
    by_digest: BTreeMap<ReleaseDigest, ArtifactDescriptor>,
    by_reference: BTreeMap<ArtifactReference, ReleaseDigest>,
}

impl CatalogIndex {
    fn insert(&mut self, descriptor: ArtifactDescriptor) -> Result<(), PlatformError> {
        if let Some(existing) = self.by_digest.get(&descriptor.release_digest) {
            if existing == &descriptor {
                return Ok(());
            }
            return Err(corrupt("duplicate release digest has conflicting metadata"));
        }
        if let Some(existing_digest) = self.by_reference.get(&descriptor.reference) {
            if existing_digest != &descriptor.release_digest {
                return Err(corrupt("artifact reference maps to conflicting release digests"));
            }
        }
        self.by_reference.insert(
            descriptor.reference.clone(),
            descriptor.release_digest.clone(),
        );
        self.by_digest
            .insert(descriptor.release_digest.clone(), descriptor);
        Ok(())
    }
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
                "catalog contains more release directories than the configured index bound",
            ));
        }

        let mut next = CatalogIndex::default();
        for path in entries {
            if !path.join(COMPLETE_FILE).is_file() {
                continue;
            }
            if next.by_digest.len() >= self.config.max_index_entries {
                return Err(error(
                    PlatformErrorCode::ResourceExhausted,
                    "catalog contains more complete releases than the configured index bound",
                ));
            }
            let artifact = self.load_complete_entry(&path)?;
            next.insert(artifact.descriptor)?;
        }
        *self.index.write().map_err(lock_error)? = next;
        Ok(())
    }

    fn load_complete_entry(&self, path: &Path) -> Result<CapsuleArtifact, PlatformError> {
        if !path.join(COMPLETE_FILE).is_file() {
            return Err(corrupt("release entry is incomplete"));
        }
        let metadata_bytes = read_entry_file(&path.join(METADATA_FILE))?;
        let stored: StoredMetadata = serde_json::from_slice(&metadata_bytes)
            .map_err(|_| corrupt("invalid catalog metadata"))?;
        let descriptor = ArtifactDescriptor::from(stored.descriptor);
        let contracts = stored
            .contracts
            .into_iter()
            .map(ContractDescriptor::from)
            .collect::<Vec<_>>();
        let manifest_bytes = read_entry_file(&path.join(MANIFEST_FILE))?;
        let component_bytes = read_entry_file(&path.join(COMPONENT_FILE))?;
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

    fn publish_sync(&self, artifact: CapsuleArtifact) -> Result<ArtifactDescriptor, PlatformError> {
        let _guard = self.publish_lock.lock().map_err(lock_error)?;
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
            digest_hex(&artifact.descriptor.release_digest)?
        ));
        fs::create_dir(&tmp_path).map_err(io_error)?;

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
                return Err(error(
                    PlatformErrorCode::AlreadyExists,
                    "release digest was concurrently published with different content",
                ));
            }
            return Err(failure);
        }

        let mut index = self.index.write().map_err(lock_error)?;
        index.insert(artifact.descriptor.clone())?;
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
            let limit = limit.min(self.config.max_page_size);
            let index = self.index.read().map_err(lock_error)?;
            let mut values = index
                .by_digest
                .iter()
                .filter(|(digest, _)| after.is_none_or(|cursor| *digest > cursor))
                .take(limit.saturating_add(1))
                .map(|(_, descriptor)| descriptor.clone())
                .collect::<Vec<_>>();
            let has_more = values.len() > limit;
            if has_more {
                values.pop();
            }
            let next_after = if has_more {
                values.last().map(|value| value.release_digest.clone())
            } else {
                None
            };
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

fn release_digest(bytes: &[u8]) -> ReleaseDigest {
    let hash = sha256(bytes);
    let mut value = String::with_capacity(71);
    value.push_str("sha256:");
    for byte in hash {
        write!(&mut value, "{byte:02x}").expect("writing to String cannot fail");
    }
    ReleaseDigest(value)
}

fn sha256(bytes: &[u8]) -> [u8; 32] {
    const INITIAL: [u32; 8] = [
        0x6a09_e667,
        0xbb67_ae85,
        0x3c6e_f372,
        0xa54f_f53a,
        0x510e_527f,
        0x9b05_688c,
        0x1f83_d9ab,
        0x5be0_cd19,
    ];
    const ROUND: [u32; 64] = [
        0x428a_2f98,
        0x7137_4491,
        0xb5c0_fbcf,
        0xe9b5_dba5,
        0x3956_c25b,
        0x59f1_11f1,
        0x923f_82a4,
        0xab1c_5ed5,
        0xd807_aa98,
        0x1283_5b01,
        0x2431_85be,
        0x550c_7dc3,
        0x72be_5d74,
        0x80de_b1fe,
        0x9bdc_06a7,
        0xc19b_f174,
        0xe49b_69c1,
        0xefbe_4786,
        0x0fc1_9dc6,
        0x240c_a1cc,
        0x2de9_2c6f,
        0x4a74_84aa,
        0x5cb0_a9dc,
        0x76f9_88da,
        0x983e_5152,
        0xa831_c66d,
        0xb003_27c8,
        0xbf59_7fc7,
        0xc6e0_0bf3,
        0xd5a7_9147,
        0x06ca_6351,
        0x1429_2967,
        0x27b7_0a85,
        0x2e1b_2138,
        0x4d2c_6dfc,
        0x5338_0d13,
        0x650a_7354,
        0x766a_0abb,
        0x81c2_c92e,
        0x9272_2c85,
        0xa2bf_e8a1,
        0xa81a_664b,
        0xc24b_8b70,
        0xc76c_51a3,
        0xd192_e819,
        0xd699_0624,
        0xf40e_3585,
        0x106a_a070,
        0x19a4_c116,
        0x1e37_6c08,
        0x2748_774c,
        0x34b0_bcb5,
        0x391c_0cb3,
        0x4ed8_aa4a,
        0x5b9c_ca4f,
        0x682e_6ff3,
        0x748f_82ee,
        0x78a5_636f,
        0x84c8_7814,
        0x8cc7_0208,
        0x90be_fffa,
        0xa450_6ceb,
        0xbef9_a3f7,
        0xc671_78f2,
    ];

    let bit_len = (bytes.len() as u64).wrapping_mul(8);
    let mut padded = Vec::with_capacity(bytes.len().saturating_add(72));
    padded.extend_from_slice(bytes);
    padded.push(0x80);
    while padded.len() % 64 != 56 {
        padded.push(0);
    }
    padded.extend_from_slice(&bit_len.to_be_bytes());

    let mut state = INITIAL;
    for chunk in padded.chunks_exact(64) {
        let mut words = [0_u32; 64];
        for (index, word) in words.iter_mut().take(16).enumerate() {
            let offset = index * 4;
            *word = u32::from_be_bytes([
                chunk[offset],
                chunk[offset + 1],
                chunk[offset + 2],
                chunk[offset + 3],
            ]);
        }
        for index in 16..64 {
            let s0 = words[index - 15].rotate_right(7)
                ^ words[index - 15].rotate_right(18)
                ^ (words[index - 15] >> 3);
            let s1 = words[index - 2].rotate_right(17)
                ^ words[index - 2].rotate_right(19)
                ^ (words[index - 2] >> 10);
            words[index] = words[index - 16]
                .wrapping_add(s0)
                .wrapping_add(words[index - 7])
                .wrapping_add(s1);
        }

        let mut a = state[0];
        let mut b = state[1];
        let mut c = state[2];
        let mut d = state[3];
        let mut e = state[4];
        let mut f = state[5];
        let mut g = state[6];
        let mut h = state[7];

        for index in 0..64 {
            let sum1 = e.rotate_right(6) ^ e.rotate_right(11) ^ e.rotate_right(25);
            let choose = (e & f) ^ ((!e) & g);
            let temp1 = h
                .wrapping_add(sum1)
                .wrapping_add(choose)
                .wrapping_add(ROUND[index])
                .wrapping_add(words[index]);
            let sum0 = a.rotate_right(2) ^ a.rotate_right(13) ^ a.rotate_right(22);
            let majority = (a & b) ^ (a & c) ^ (b & c);
            let temp2 = sum0.wrapping_add(majority);

            h = g;
            g = f;
            f = e;
            e = d.wrapping_add(temp1);
            d = c;
            c = b;
            b = a;
            a = temp1.wrapping_add(temp2);
        }

        state[0] = state[0].wrapping_add(a);
        state[1] = state[1].wrapping_add(b);
        state[2] = state[2].wrapping_add(c);
        state[3] = state[3].wrapping_add(d);
        state[4] = state[4].wrapping_add(e);
        state[5] = state[5].wrapping_add(f);
        state[6] = state[6].wrapping_add(g);
        state[7] = state[7].wrapping_add(h);
    }

    let mut output = [0_u8; 32];
    for (index, word) in state.into_iter().enumerate() {
        output[index * 4..index * 4 + 4].copy_from_slice(&word.to_be_bytes());
    }
    output
}

fn read_entry_file(path: &Path) -> Result<Vec<u8>, PlatformError> {
    let mut file = File::open(path).map_err(|_| corrupt("completed release is missing data"))?;
    let mut bytes = Vec::new();
    file.read_to_end(&mut bytes)
        .map_err(|_| corrupt("completed release data cannot be read"))?;
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

fn error(code: PlatformErrorCode, message: impl Into<String>) -> PlatformError {
    PlatformError {
        code,
        message: message.into(),
        retryable: false,
        details: Vec::new(),
    }
}

#[cfg(test)]
mod tests;
