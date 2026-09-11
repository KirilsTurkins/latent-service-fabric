mod encoding;
mod hashing;
#[cfg(test)]
mod legacy;
mod projection;

use std::collections::BTreeMap;
use std::fs::{self, File, OpenOptions};
use std::io::{Read, Write};
use std::path::{Path, PathBuf};

use latent_core::{DeploymentId, PlatformError, PlatformErrorCode};
use latent_manifest::{
    __serde::{Deserialize, Serialize},
    __serde_json as json, DeploymentManifest, JsonManifestCodec, ManifestCodec,
};

use super::compiler::CompiledCatalog;
use super::observation::{count, maximum, Work};
use super::{error, DirectoryDeploymentRepositoryConfig, OwnerLock};

#[cfg(test)]
pub(super) mod faults;

pub(super) const STATE_FILE: &str = "catalog.json";
const PENDING_FILE: &str = ".catalog.pending";
const OWNER_FILE: &str = ".catalog.lock";
const INITIALIZED_FILE: &str = "INITIALIZED";
const INITIALIZED_PENDING_FILE: &str = ".INITIALIZED.pending";
const INITIALIZED_CONTENT: &[u8] = b"lsf-deployment-catalog-v1\n";

#[derive(Serialize, Deserialize)]
#[serde(crate = "latent_manifest::__serde", deny_unknown_fields)]
pub(super) struct Payload {
    pub generation: u64,
    pub generated_at_unix_millis: u64,
    deployments: Vec<json::Value>,
    pub snapshot: json::Value,
    // Omission preserves the exact v1 typed payload serialization used by its checksum.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    object_generations: Option<Vec<StoredObjectGeneration>>,
}

#[derive(Serialize, Deserialize)]
#[serde(crate = "latent_manifest::__serde", deny_unknown_fields)]
struct StoredObjectGeneration {
    id: String,
    generation: u64,
}

#[derive(Serialize, Deserialize)]
#[serde(crate = "latent_manifest::__serde", deny_unknown_fields)]
pub(super) struct Record {
    format_version: u32,
    pub checksum: String,
    pub payload: Payload,
}

impl Record {
    pub(super) fn object_generations(
        &self,
        deployments: &BTreeMap<DeploymentId, DeploymentManifest>,
    ) -> Result<BTreeMap<DeploymentId, u64>, PlatformError> {
        match (self.format_version, &self.payload.object_generations) {
            (1, None) => Ok(deployments
                .keys()
                .map(|id| (id.clone(), self.payload.generation))
                .collect()),
            (2, Some(stored)) if stored.len() == deployments.len() => {
                let mut versions = BTreeMap::new();
                for entry in stored {
                    let id = DeploymentId(entry.id.clone());
                    if entry.generation == 0
                        || entry.generation > self.payload.generation
                        || !deployments.contains_key(&id)
                        || versions.insert(id, entry.generation).is_some()
                    {
                        return Err(corrupt());
                    }
                }
                Ok(versions)
            }
            _ => Err(corrupt()),
        }
    }

    pub(super) fn deployments(
        &self,
        config: DirectoryDeploymentRepositoryConfig,
    ) -> Result<BTreeMap<DeploymentId, DeploymentManifest>, PlatformError> {
        if self.payload.deployments.len() > config.max_deployments {
            return Err(error(
                PlatformErrorCode::ResourceExhausted,
                "deployment-count-limit",
            ));
        }
        let codec = JsonManifestCodec::default();
        let mut deployments = BTreeMap::new();
        for value in &self.payload.deployments {
            let bytes = json::to_vec(value).map_err(|_| corrupt())?;
            let deployment = codec.decode_deployment(&bytes).map_err(|_| corrupt())?;
            if deployments
                .insert(deployment.id.clone(), deployment)
                .is_some()
            {
                return Err(error(
                    PlatformErrorCode::CorruptArtifact,
                    "duplicate-persisted-deployment-id",
                ));
            }
        }
        if self.payload.generation == 0 && !deployments.is_empty() {
            return Err(corrupt());
        }
        Ok(deployments)
    }
}

pub(super) fn own_root(root: &Path) -> Result<(PathBuf, OwnerLock), PlatformError> {
    let root = create_durable_root(root)?;
    regular_or_absent(&root.join(OWNER_FILE))?;
    let owner = OpenOptions::new()
        .create(true)
        .truncate(false)
        .read(true)
        .write(true)
        .open(root.join(OWNER_FILE))
        .map_err(io_error)?;
    owner
        .try_lock()
        .map_err(|_| error(PlatformErrorCode::Unavailable, "catalog-root-already-owned"))?;
    let owner = OwnerLock(owner);
    regular_or_absent(&root.join(STATE_FILE))?;
    regular_or_absent(&root.join(PENDING_FILE))?;
    regular_or_absent(&root.join(INITIALIZED_FILE))?;
    regular_or_absent(&root.join(INITIALIZED_PENDING_FILE))?;
    if root.join(INITIALIZED_FILE).exists() {
        let mut marker = Vec::new();
        File::open(root.join(INITIALIZED_FILE))
            .map_err(io_error)?
            .take(INITIALIZED_CONTENT.len() as u64 + 1)
            .read_to_end(&mut marker)
            .map_err(io_error)?;
        if marker != INITIALIZED_CONTENT {
            return Err(corrupt());
        }
        if !root.join(STATE_FILE).exists() {
            return Err(error(
                PlatformErrorCode::CorruptArtifact,
                "initialized-catalog-state-missing",
            ));
        }
    }
    // Cleanup is only allowed after acquiring the exclusive root lock. A staging
    // marker, including an empty or truncated one, is never authoritative state.
    remove_pending(&root)?;
    remove_if_present(&root.join(INITIALIZED_PENDING_FILE))?;
    Ok((root, owner))
}

/// Synchronize every link that makes the catalog reachable, leaf to filesystem root.
/// Repeating this on existing paths repairs an earlier failed/interrupted creation:
/// existence alone does not prove that an ancestor's directory entry is durable.
fn create_durable_root(root: &Path) -> Result<PathBuf, PlatformError> {
    // Anchor relative input once before filesystem work or asynchronous suspension.
    let absolute = if root.is_absolute() {
        root.to_owned()
    } else {
        std::env::current_dir().map_err(io_error)?.join(root)
    };
    fs::create_dir_all(&absolute).map_err(io_error)?;
    let absolute = fs::canonicalize(absolute).map_err(io_error)?;
    for directory in absolute.ancestors() {
        sync_directory(directory, IoStep::PathDirectorySync).map_err(|_| {
            error(
                PlatformErrorCode::Unavailable,
                "catalog-path-durability-uncertain",
            )
        })?;
    }
    Ok(absolute)
}

pub(super) fn load(
    root: &Path,
    config: DirectoryDeploymentRepositoryConfig,
    work: &mut Work,
) -> Result<Option<Record>, PlatformError> {
    let file = match File::open(root.join(STATE_FILE)) {
        Ok(file) => file,
        Err(failure) if failure.kind() == std::io::ErrorKind::NotFound => return Ok(None),
        Err(failure) => return Err(io_error(failure)),
    };
    if file.metadata().map_err(io_error)?.len() > config.max_state_bytes as u64 {
        return Err(byte_limit());
    }
    let mut bytes = Vec::new();
    file.take(config.max_state_bytes as u64 + 1)
        .read_to_end(&mut bytes)
        .map_err(io_error)?;
    if bytes.len() > config.max_state_bytes {
        return Err(byte_limit());
    }
    let record: Record = json::from_slice(&bytes).map_err(|_| corrupt())?;
    let checksum = payload_checksum(&record.payload, config.max_state_bytes, work)?;
    if !matches!(record.format_version, 1 | 2)
        || record.checksum.as_bytes().strip_prefix(b"sha256:") != Some(checksum.as_slice())
    {
        return Err(corrupt());
    }
    Ok(Some(record))
}

/// The only pairing of a fully validated catalog with its exact durable bytes.
/// No clone, mutable catalog access, or independently supplied byte constructor exists.
pub(super) struct EncodedCatalog {
    catalog: CompiledCatalog,
    bytes: Vec<u8>,
}

impl EncodedCatalog {
    pub(super) fn catalog(&self) -> &CompiledCatalog {
        &self.catalog
    }

    pub(super) fn into_catalog(self) -> CompiledCatalog {
        self.catalog
    }

    pub(super) fn into_parts(self) -> (CompiledCatalog, Vec<u8>) {
        (self.catalog, self.bytes)
    }

    #[cfg(test)]
    pub(super) fn bytes(&self) -> &[u8] {
        &self.bytes
    }
}

pub(super) fn encode(
    catalog: CompiledCatalog,
    config: DirectoryDeploymentRepositoryConfig,
    work: &mut Work,
) -> Result<EncodedCatalog, PlatformError> {
    count!(work, encoder_calls, 1);
    let result = encode_bytes(&catalog, config.max_state_bytes, work);
    if result.is_ok() {
        count!(work, encoder_completed, 1);
    } else {
        count!(work, encoder_failed, 1);
    }
    result.map(|bytes| EncodedCatalog { catalog, bytes })
}

fn encode_bytes(
    catalog: &CompiledCatalog,
    limit: usize,
    work: &mut Work,
) -> Result<Vec<u8>, PlatformError> {
    let mut output = LimitedBytes {
        bytes: Vec::new(),
        limit,
    };
    count!(work, envelope_serializations, 1);
    let result = encoding::write(&mut output, catalog, work);
    count!(work, encoded_buffer_bytes, output.bytes.len());
    maximum!(work, encoded_capacity_max, output.bytes.capacity());
    result.map_err(|_| byte_limit())?;
    Ok(output.bytes)
}

fn payload_checksum(
    payload: &Payload,
    limit: usize,
    work: &mut Work,
) -> Result<[u8; 64], PlatformError> {
    // Same typed canonical traversal and byte bound, with no payload-sized buffer.
    let mut output = hashing::Hashing::new(std::io::sink(), limit);
    count!(work, load_payload_serializations, 1);
    json::to_writer(&mut output, payload).map_err(|_| byte_limit())?;
    Ok(output.finish())
}

struct LimitedBytes {
    bytes: Vec<u8>,
    limit: usize,
}

impl Write for LimitedBytes {
    fn write(&mut self, input: &[u8]) -> std::io::Result<usize> {
        let needed = self
            .bytes
            .len()
            .checked_add(input.len())
            .filter(|size| *size <= self.limit)
            .ok_or_else(|| std::io::Error::other("catalog-state-byte-limit"))?;
        if needed > self.bytes.capacity() {
            let capacity = needed
                .max(self.bytes.capacity().saturating_mul(2))
                .min(self.limit);
            self.bytes
                .try_reserve_exact(capacity - self.bytes.len())
                .map_err(std::io::Error::other)?;
        }
        self.bytes.extend_from_slice(input);
        Ok(input.len())
    }

    fn flush(&mut self) -> std::io::Result<()> {
        Ok(())
    }
}

/// Direct canonical traversal avoids a second owned public route snapshot.
pub(super) fn catalog_snapshot_value(catalog: &CompiledCatalog) -> json::Value {
    let services = catalog
        .route_views()
        .map(|route| {
            let revisions = route
                .revisions()
                .map(|record| {
                    json::json!({
                        "revision": record.revision.0,
                        "release": record.deployment.release.0,
                        "weight": record.deployment.route_weight,
                        "attributes": record.attributes,
                    })
                })
                .collect::<Vec<_>>();
            json::json!({
                "route": route.id(),
                "tenant": route.tenant().0,
                "service": route.service().0,
                "revisions": revisions,
            })
        })
        .collect::<Vec<_>>();
    json::json!({
        "generation": catalog.generation.0,
        "generated_at_unix_millis": catalog.generated_at_unix_millis,
        "services": services,
        "bindings": [],
        "policy_digests": [],
    })
}

pub(super) fn stage(root: &Path, bytes: &[u8], work: &mut Work) -> Result<(), PlatformError> {
    count!(work, stage_calls, 1);
    count!(work, stage_requested_bytes, bytes.len());
    remove_pending(root)?;
    let mut pending = OpenOptions::new()
        .create_new(true)
        .write(true)
        .open(root.join(PENDING_FILE))
        .map_err(io_error)?;
    write_stage(&mut pending, bytes, work)?;
    if let Err(failure) = pending.sync_all() {
        count!(work, stage_sync_failures, 1);
        return Err(io_error(failure));
    }
    count!(work, stage_completed, 1);
    count!(work, stage_synced_bytes, bytes.len());
    Ok(())
}

fn write_stage(
    writer: &mut impl Write,
    bytes: &[u8],
    work: &mut Work,
) -> Result<(), PlatformError> {
    if let Err(failure) = writer.write_all(bytes) {
        count!(work, stage_write_failures, 1);
        work.written(None);
        return Err(io_error(failure));
    }
    work.written(Some(bytes.len()));
    Ok(())
}

pub(super) fn replace(root: &Path) -> Result<(), PlatformError> {
    fs::rename(root.join(PENDING_FILE), root.join(STATE_FILE)).map_err(io_error)
}

pub(super) fn sync_root(root: &Path) -> Result<(), PlatformError> {
    sync_directory(root, IoStep::StateDirectorySync).map_err(|_| {
        error(
            PlatformErrorCode::Unavailable,
            "commit-durability-uncertain",
        )
    })?;
    // Publish the fixed node-owned marker using the same durability protocol as
    // catalog.json. Never expose an empty/partial marker under its completed name.
    if !root.join(INITIALIZED_FILE).exists() {
        let path = root.join(INITIALIZED_PENDING_FILE);
        regular_or_absent(&path)?;
        remove_if_present(&path)?;
        let mut marker = OpenOptions::new()
            .create_new(true)
            .write(true)
            .open(&path)
            .map_err(io_error)?;
        checkpoint(IoStep::MarkerCreated, &path).map_err(io_error)?;
        let middle = INITIALIZED_CONTENT.len() / 2;
        marker
            .write_all(&INITIALIZED_CONTENT[..middle])
            .map_err(io_error)?;
        checkpoint(IoStep::MarkerPartialWrite, &path).map_err(io_error)?;
        marker
            .write_all(&INITIALIZED_CONTENT[middle..])
            .map_err(io_error)?;
        checkpoint(IoStep::MarkerFileSync, &path).map_err(io_error)?;
        marker.sync_all().map_err(io_error)?;
        checkpoint(IoStep::MarkerRename, &path).map_err(io_error)?;
        fs::rename(&path, root.join(INITIALIZED_FILE)).map_err(io_error)?;
        sync_directory(root, IoStep::MarkerDirectorySync).map_err(io_error)?;
    }
    Ok(())
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(super) enum IoStep {
    PathDirectorySync,
    StateDirectorySync,
    MarkerCreated,
    MarkerPartialWrite,
    MarkerFileSync,
    MarkerRename,
    MarkerDirectorySync,
}

fn sync_directory(path: &Path, step: IoStep) -> std::io::Result<()> {
    checkpoint(step, path)?;
    File::open(path)?.sync_all()
}

fn checkpoint(step: IoStep, path: &Path) -> std::io::Result<()> {
    #[cfg(test)]
    faults::checkpoint(step, path)?;
    let _ = (step, path);
    Ok(())
}

fn remove_pending(root: &Path) -> Result<(), PlatformError> {
    remove_if_present(&root.join(PENDING_FILE))
}

fn remove_if_present(path: &Path) -> Result<(), PlatformError> {
    match fs::remove_file(path) {
        Ok(()) => Ok(()),
        Err(failure) if failure.kind() == std::io::ErrorKind::NotFound => Ok(()),
        Err(failure) => Err(io_error(failure)),
    }
}

fn regular_or_absent(path: &Path) -> Result<(), PlatformError> {
    match fs::symlink_metadata(path) {
        Ok(metadata) if metadata.file_type().is_file() => Ok(()),
        Ok(_) => Err(error(
            PlatformErrorCode::CorruptArtifact,
            "non-regular-catalog-file",
        )),
        Err(failure) if failure.kind() == std::io::ErrorKind::NotFound => Ok(()),
        Err(failure) => Err(io_error(failure)),
    }
}

fn io_error(_failure: std::io::Error) -> PlatformError {
    error(PlatformErrorCode::Unavailable, "catalog-io-failure")
}

fn byte_limit() -> PlatformError {
    error(
        PlatformErrorCode::ResourceExhausted,
        "catalog-state-byte-limit",
    )
}

fn corrupt() -> PlatformError {
    error(
        PlatformErrorCode::CorruptArtifact,
        "invalid-persisted-catalog",
    )
}

#[cfg(all(test, feature = "catalog-observation"))]
#[path = "tests/observation_io.rs"]
mod observation_tests;

#[cfg(test)]
mod tests;
