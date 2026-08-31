use std::fs::{self, File, OpenOptions};
use std::io::{Read, Write};
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicU64, Ordering};

use latent_core::{PlatformError, PlatformErrorCode, RouteGeneration};
use serde::{Deserialize, Serialize};

use super::model::PersistedCatalogState;
use super::{platform_error, stable_fields, EmbeddedCatalogOptions};

const FORMAT_VERSION: u32 = 1;
const GENERATIONS_DIR: &str = "generations";
const COMMITS_DIR: &str = "commits";
const STATE_SUFFIX: &str = ".json";
const COMMIT_SUFFIX: &str = ".commit";
static TEMP_COUNTER: AtomicU64 = AtomicU64::new(0);

#[derive(Debug, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
struct StateEnvelope {
    format_version: u32,
    generation: u64,
    state_checksum: String,
    state: PersistedCatalogState,
}

#[derive(Debug, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
struct CommitMarker {
    format_version: u32,
    generation: u64,
    state_file: String,
    state_checksum: String,
}

pub(crate) fn initialize(root: &Path) -> Result<(), PlatformError> {
    fs::create_dir_all(generations_dir(root))
        .map_err(|error| io_error("create-generations-dir", root, error))?;
    fs::create_dir_all(commits_dir(root))
        .map_err(|error| io_error("create-commits-dir", root, error))?;
    Ok(())
}

pub(crate) fn load_latest(
    root: &Path,
    options: &EmbeddedCatalogOptions,
) -> Result<Option<PersistedCatalogState>, PlatformError> {
    let generations = committed_generations(root)?;
    let latest = generations.last().copied();
    let state = latest
        .map(|generation| load_generation_required(root, generation, options))
        .transpose()?;
    cleanup_orphans(root)?;
    Ok(state)
}

pub(crate) fn load_generation(
    root: &Path,
    generation: RouteGeneration,
    options: &EmbeddedCatalogOptions,
) -> Result<Option<PersistedCatalogState>, PlatformError> {
    if !commit_path(root, generation.0).exists() {
        return Ok(None);
    }
    load_generation_required(root, generation.0, options).map(Some)
}

pub(crate) fn load_after(
    root: &Path,
    after: RouteGeneration,
    options: &EmbeddedCatalogOptions,
) -> Result<Vec<PersistedCatalogState>, PlatformError> {
    committed_generations(root)?
        .into_iter()
        .filter(|generation| *generation > after.0)
        .map(|generation| load_generation_required(root, generation, options))
        .collect()
}

pub(crate) fn commit(
    root: &Path,
    state: PersistedCatalogState,
    options: &EmbeddedCatalogOptions,
) -> Result<(), PlatformError> {
    let generation = state.generation();
    if generation == 0 {
        return Err(platform_error(
            PlatformErrorCode::StateConflict,
            "invalid-route-generation",
            "generation zero is the in-memory empty baseline and cannot be committed",
            stable_fields([("generation", generation.to_string())]),
        ));
    }

    let marker_path = commit_path(root, generation);
    if marker_path.exists() {
        return Err(platform_error(
            PlatformErrorCode::StateConflict,
            "route-generation-already-committed",
            "the requested route generation already has a complete commit marker",
            stable_fields([("generation", generation.to_string())]),
        ));
    }

    let state_bytes = serde_json::to_vec(&state).map_err(|error| {
        platform_error(
            PlatformErrorCode::Internal,
            "route-state-encoding-failed",
            "the complete deployment and route state could not be encoded",
            stable_fields([("reason", error.to_string())]),
        )
    })?;
    let checksum = checksum(&state_bytes);
    let envelope = StateEnvelope {
        format_version: FORMAT_VERSION,
        generation,
        state_checksum: checksum.clone(),
        state,
    };
    let envelope_bytes = serde_json::to_vec(&envelope).map_err(|error| {
        platform_error(
            PlatformErrorCode::Internal,
            "route-envelope-encoding-failed",
            "the route generation envelope could not be encoded",
            stable_fields([("reason", error.to_string())]),
        )
    })?;
    if envelope_bytes.len() as u64 > options.max_state_file_bytes {
        return Err(platform_error(
            PlatformErrorCode::ResourceExhausted,
            "route-state-size-limit",
            "the complete deployment and route generation exceeds its configured persistence bound",
            stable_fields([
                ("size_bytes", envelope_bytes.len().to_string()),
                ("limit_bytes", options.max_state_file_bytes.to_string()),
            ]),
        ));
    }

    let state_path = state_path(root, generation);
    if state_path.exists() {
        fs::remove_file(&state_path)
            .map_err(|error| io_error("remove-orphan-state", &state_path, error))?;
    }
    atomic_create(&state_path, &envelope_bytes)?;

    let marker = CommitMarker {
        format_version: FORMAT_VERSION,
        generation,
        state_file: state_file_name(generation),
        state_checksum: checksum,
    };
    let marker_bytes = serde_json::to_vec(&marker).map_err(|error| {
        platform_error(
            PlatformErrorCode::Internal,
            "route-marker-encoding-failed",
            "the route generation commit marker could not be encoded",
            stable_fields([("reason", error.to_string())]),
        )
    })?;
    publish_commit_marker(root, &marker_path, &marker_bytes)?;
    Ok(())
}

pub(crate) fn cleanup_retained(
    root: &Path,
    options: &EmbeddedCatalogOptions,
) -> Result<(), PlatformError> {
    let generations = committed_generations(root)?;
    let remove_count = generations
        .len()
        .saturating_sub(options.retained_generations);
    for generation in generations.into_iter().take(remove_count) {
        remove_if_exists(&commit_path(root, generation))?;
        remove_if_exists(&state_path(root, generation))?;
    }
    cleanup_orphans(root)?;
    Ok(())
}

fn load_generation_required(
    root: &Path,
    generation: u64,
    options: &EmbeddedCatalogOptions,
) -> Result<PersistedCatalogState, PlatformError> {
    let marker_path = commit_path(root, generation);
    let marker_bytes = read_limited(&marker_path, 64 * 1024)?;
    let marker: CommitMarker = serde_json::from_slice(&marker_bytes).map_err(|error| {
        corrupt(
            "invalid-route-commit-marker",
            "a retained route commit marker is not valid JSON",
            stable_fields([
                ("generation", generation.to_string()),
                ("reason", error.to_string()),
            ]),
        )
    })?;
    if marker.format_version != FORMAT_VERSION
        || marker.generation != generation
        || marker.state_file != state_file_name(generation)
    {
        return Err(corrupt(
            "route-commit-marker-mismatch",
            "a retained route commit marker does not identify its generation exactly",
            stable_fields([("generation", generation.to_string())]),
        ));
    }

    let state_path = generations_dir(root).join(&marker.state_file);
    let envelope_bytes = read_limited(&state_path, options.max_state_file_bytes)?;
    let envelope: StateEnvelope = serde_json::from_slice(&envelope_bytes).map_err(|error| {
        corrupt(
            "invalid-route-state-envelope",
            "a committed route generation is not valid JSON",
            stable_fields([
                ("generation", generation.to_string()),
                ("reason", error.to_string()),
            ]),
        )
    })?;
    if envelope.format_version != FORMAT_VERSION || envelope.generation != generation {
        return Err(corrupt(
            "route-state-generation-mismatch",
            "the committed route state envelope identifies a different generation",
            stable_fields([("generation", generation.to_string())]),
        ));
    }
    let state_bytes = serde_json::to_vec(&envelope.state).map_err(|error| {
        corrupt(
            "route-state-reencoding-failed",
            "the committed route state could not be re-encoded for checksum verification",
            stable_fields([
                ("generation", generation.to_string()),
                ("reason", error.to_string()),
            ]),
        )
    })?;
    let actual_checksum = checksum(&state_bytes);
    if envelope.state_checksum != actual_checksum || marker.state_checksum != actual_checksum {
        return Err(corrupt(
            "route-state-checksum-mismatch",
            "the committed deployment and route generation failed checksum verification",
            stable_fields([("generation", generation.to_string())]),
        ));
    }
    if envelope.state.generation() != generation {
        return Err(corrupt(
            "route-snapshot-generation-mismatch",
            "the route snapshot generation differs from its committed envelope",
            stable_fields([("generation", generation.to_string())]),
        ));
    }
    Ok(envelope.state)
}

fn atomic_create(path: &Path, bytes: &[u8]) -> Result<(), PlatformError> {
    let parent = path.parent().ok_or_else(|| {
        platform_error(
            PlatformErrorCode::Internal,
            "invalid-persistence-path",
            "the route persistence path has no parent directory",
            stable_fields([("path", path.display().to_string())]),
        )
    })?;
    let counter = TEMP_COUNTER.fetch_add(1, Ordering::Relaxed);
    let file_name = path
        .file_name()
        .and_then(|name| name.to_str())
        .unwrap_or("route-state");
    let temporary = parent.join(format!(".{file_name}.tmp-{}-{counter}", std::process::id()));

    let write_result = (|| -> Result<(), PlatformError> {
        let mut file = OpenOptions::new()
            .create_new(true)
            .write(true)
            .open(&temporary)
            .map_err(|error| io_error("create-temporary-route-state", &temporary, error))?;
        file.write_all(bytes)
            .map_err(|error| io_error("write-temporary-route-state", &temporary, error))?;
        file.sync_all()
            .map_err(|error| io_error("sync-temporary-route-state", &temporary, error))?;
        drop(file);
        fs::rename(&temporary, path)
            .map_err(|error| io_error("publish-route-state", path, error))?;
        sync_directory(parent)?;
        Ok(())
    })();

    if write_result.is_err() {
        let _ = fs::remove_file(&temporary);
    }
    write_result
}

fn publish_commit_marker(root: &Path, path: &Path, bytes: &[u8]) -> Result<(), PlatformError> {
    let parent = path.parent().ok_or_else(|| {
        platform_error(
            PlatformErrorCode::Internal,
            "invalid-persistence-path",
            "the route persistence path has no parent directory",
            stable_fields([("path", path.display().to_string())]),
        )
    })?;
    let counter = TEMP_COUNTER.fetch_add(1, Ordering::Relaxed);
    let file_name = path
        .file_name()
        .and_then(|name| name.to_str())
        .unwrap_or("route-commit");
    let temporary = parent.join(format!(".{file_name}.tmp-{}-{counter}", std::process::id()));

    let write_result = (|| -> Result<(), PlatformError> {
        let mut file = OpenOptions::new()
            .create_new(true)
            .write(true)
            .open(&temporary)
            .map_err(|error| io_error("create-temporary-route-marker", &temporary, error))?;
        file.write_all(bytes)
            .map_err(|error| io_error("write-temporary-route-marker", &temporary, error))?;
        file.sync_all()
            .map_err(|error| io_error("sync-temporary-route-marker", &temporary, error))?;
        drop(file);
        fs::rename(&temporary, path).map_err(|error| io_error("publish-route-marker", path, error))
    })();

    if let Err(error) = write_result {
        let _ = fs::remove_file(&temporary);
        return Err(error);
    }

    // The atomic marker rename above is the sole transaction commit point. Directory
    // synchronization improves crash durability but cannot turn an already committed
    // generation into a caller-visible transaction failure.
    let _ = sync_commit_directory_after_publication(root, parent);
    Ok(())
}

fn sync_commit_directory_after_publication(root: &Path, path: &Path) -> Result<(), PlatformError> {
    #[cfg(test)]
    if super::fault_injection::take(
        root,
        super::fault_injection::FaultPoint::CommitDirectorySyncAfterMarkerRename,
    ) {
        return Err(io_error(
            "sync-route-commit-directory",
            path,
            std::io::Error::new(
                std::io::ErrorKind::Other,
                "injected commit-directory synchronization failure",
            ),
        ));
    }

    sync_directory(path)
}

fn read_limited(path: &Path, limit: u64) -> Result<Vec<u8>, PlatformError> {
    let metadata = fs::symlink_metadata(path).map_err(|error| {
        corrupt(
            "missing-committed-route-state",
            "a committed route generation is missing one of its required files",
            stable_fields([
                ("path", path.display().to_string()),
                ("reason", error.to_string()),
            ]),
        )
    })?;
    if !metadata.file_type().is_file() {
        return Err(corrupt(
            "invalid-route-state-file-type",
            "a committed route state path is not a regular file",
            stable_fields([("path", path.display().to_string())]),
        ));
    }
    if metadata.len() > limit {
        return Err(corrupt(
            "route-state-file-too-large",
            "a committed route state file exceeds the configured read bound",
            stable_fields([
                ("path", path.display().to_string()),
                ("size_bytes", metadata.len().to_string()),
                ("limit_bytes", limit.to_string()),
            ]),
        ));
    }
    let file = File::open(path).map_err(|error| io_error("open-route-state", path, error))?;
    let capacity = usize::try_from(metadata.len()).unwrap_or(0);
    let mut bytes = Vec::with_capacity(capacity);
    file.take(limit.saturating_add(1))
        .read_to_end(&mut bytes)
        .map_err(|error| io_error("read-route-state", path, error))?;
    if bytes.len() as u64 > limit {
        return Err(corrupt(
            "route-state-file-too-large",
            "a committed route state file grew beyond the configured read bound",
            stable_fields([("path", path.display().to_string())]),
        ));
    }
    Ok(bytes)
}

fn committed_generations(root: &Path) -> Result<Vec<u64>, PlatformError> {
    let mut generations = Vec::new();
    let entries = fs::read_dir(commits_dir(root))
        .map_err(|error| io_error("read-route-commits", root, error))?;
    for entry in entries {
        let entry = entry.map_err(|error| io_error("read-route-commit-entry", root, error))?;
        let file_type = entry
            .file_type()
            .map_err(|error| io_error("read-route-commit-file-type", &entry.path(), error))?;
        if !file_type.is_file() {
            continue;
        }
        if let Some(generation) =
            parse_generation_name(&entry.file_name().to_string_lossy(), COMMIT_SUFFIX)
        {
            generations.push(generation);
        }
    }
    generations.sort_unstable();
    generations.dedup();
    Ok(generations)
}

fn cleanup_orphans(root: &Path) -> Result<(), PlatformError> {
    let generation_entries = fs::read_dir(generations_dir(root))
        .map_err(|error| io_error("read-route-generations", root, error))?;
    for entry in generation_entries {
        let entry = entry.map_err(|error| io_error("read-route-generation-entry", root, error))?;
        let file_type = entry
            .file_type()
            .map_err(|error| io_error("read-route-generation-file-type", &entry.path(), error))?;
        if !file_type.is_file() {
            continue;
        }

        let file_name = entry.file_name().to_string_lossy().into_owned();
        let Some(generation) = parse_generation_name(&file_name, STATE_SUFFIX) else {
            if file_name.contains(".tmp-") {
                remove_if_exists(&entry.path())?;
            }
            continue;
        };
        if !commit_path(root, generation).exists() {
            remove_if_exists(&entry.path())?;
        }
    }

    let commit_entries = fs::read_dir(commits_dir(root))
        .map_err(|error| io_error("read-route-commits", root, error))?;
    for entry in commit_entries {
        let entry = entry.map_err(|error| io_error("read-route-commit-entry", root, error))?;
        let file_type = entry
            .file_type()
            .map_err(|error| io_error("read-route-commit-file-type", &entry.path(), error))?;
        if file_type.is_file() && entry.file_name().to_string_lossy().contains(".tmp-") {
            remove_if_exists(&entry.path())?;
        }
    }
    Ok(())
}

fn remove_if_exists(path: &Path) -> Result<(), PlatformError> {
    match fs::remove_file(path) {
        Ok(()) => Ok(()),
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => Ok(()),
        Err(error) => Err(io_error("remove-retained-route-state", path, error)),
    }
}

#[cfg(unix)]
fn sync_directory(path: &Path) -> Result<(), PlatformError> {
    File::open(path)
        .and_then(|directory| directory.sync_all())
        .map_err(|error| io_error("sync-route-directory", path, error))
}

#[cfg(not(unix))]
fn sync_directory(_path: &Path) -> Result<(), PlatformError> {
    // Same-directory rename still supplies atomic visibility. Directory fsync is not
    // uniformly available through std on non-Unix targets.
    Ok(())
}

fn generations_dir(root: &Path) -> PathBuf {
    root.join(GENERATIONS_DIR)
}

fn commits_dir(root: &Path) -> PathBuf {
    root.join(COMMITS_DIR)
}

fn state_file_name(generation: u64) -> String {
    format!("{generation:020}{STATE_SUFFIX}")
}

fn state_path(root: &Path, generation: u64) -> PathBuf {
    generations_dir(root).join(state_file_name(generation))
}

fn commit_path(root: &Path, generation: u64) -> PathBuf {
    commits_dir(root).join(format!("{generation:020}{COMMIT_SUFFIX}"))
}

fn parse_generation_name(name: &str, suffix: &str) -> Option<u64> {
    let digits = name.strip_suffix(suffix)?;
    if digits.len() != 20 || !digits.bytes().all(|byte| byte.is_ascii_digit()) {
        return None;
    }
    digits.parse().ok()
}

fn checksum(bytes: &[u8]) -> String {
    format!("blake3:{}", blake3::hash(bytes).to_hex())
}

fn corrupt(kind: &str, message: &str, fields: latent_core::Metadata) -> PlatformError {
    platform_error(PlatformErrorCode::CorruptArtifact, kind, message, fields)
}

fn io_error(operation: &str, path: &Path, error: std::io::Error) -> PlatformError {
    platform_error(
        PlatformErrorCode::Internal,
        "route-persistence-io",
        "the embedded route catalog could not complete a persistence operation",
        stable_fields([
            ("operation", operation.to_owned()),
            ("path", path.display().to_string()),
            ("reason", error.to_string()),
        ]),
    )
}
