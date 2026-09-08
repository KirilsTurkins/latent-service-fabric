//! One-pass component verification with fixed scratch and optional byte retention.

use std::fs::{self, File};
use std::io::{ErrorKind, Read};
use std::path::Path;

use latent_core::{PlatformError, ReleaseDigest};
use sha2::{Digest, Sha256};

use super::{corrupt, resource_exhausted};
use crate::content_hash::format_digest;
use crate::verification_statistics::{add, VerificationStatistics};

pub(super) const SCRATCH_BYTES: usize = 64 * 1024;

#[derive(Clone, Copy)]
pub(super) enum Retention {
    Metadata,
    Component,
}

pub(super) struct ComponentRead {
    pub(super) digest: ReleaseDigest,
    pub(super) size: u64,
    pub(super) bytes: Vec<u8>,
}

pub(super) fn read_component(
    path: &Path,
    limit: usize,
    retention: Retention,
    statistics: &VerificationStatistics,
) -> Result<ComponentRead, PlatformError> {
    add(&statistics.component_verification_attempts, 1);
    // Check before open so a misplaced FIFO is not treated as component input.
    let metadata = fs::metadata(path).map_err(|_| corrupt("completed release is missing data"))?;
    if !metadata.is_file() {
        return Err(corrupt("completed release data is not a regular file"));
    }
    let file = File::open(path).map_err(|_| corrupt("completed release is missing data"))?;
    let metadata = file
        .metadata()
        .map_err(|_| corrupt("completed release data metadata cannot be read"))?;
    if !metadata.is_file() {
        return Err(corrupt("completed release data is not a regular file"));
    }
    read_stream_counted(file, metadata.len(), limit, retention, Some(statistics))
}

#[cfg(test)]
fn read_stream(
    reader: impl Read,
    initial_length: u64,
    limit: usize,
    retention: Retention,
) -> Result<ComponentRead, PlatformError> {
    read_stream_counted(reader, initial_length, limit, retention, None)
}

fn read_stream_counted(
    reader: impl Read,
    initial_length: u64,
    limit: usize,
    retention: Retention,
    statistics: Option<&VerificationStatistics>,
) -> Result<ComponentRead, PlatformError> {
    let limit = u64::try_from(limit)
        .map_err(|_| resource_exhausted("configured file limit cannot fit in u64"))?;
    if initial_length > limit {
        return Err(too_large());
    }
    let mut reader = reader.take(limit.saturating_add(1));
    let mut bytes = Vec::new();
    if matches!(retention, Retention::Component) {
        let capacity = usize::try_from(initial_length)
            .map_err(|_| resource_exhausted("stored release file length cannot fit in memory"))?;
        bytes
            .try_reserve_exact(capacity)
            .map_err(|_| allocation_error())?;
    }
    let mut hasher = Sha256::new();
    let mut size = 0_u64;
    let mut scratch = [0_u8; SCRATCH_BYTES];
    loop {
        let count = match reader.read(&mut scratch) {
            Ok(0) => break,
            Ok(count) => count,
            Err(error) if error.kind() == ErrorKind::Interrupted => continue,
            Err(_) => return Err(corrupt("completed release data cannot be read")),
        };
        size = size.checked_add(count as u64).ok_or_else(too_large)?;
        if size > limit {
            return Err(too_large());
        }
        hasher.update(&scratch[..count]);
        if let Some(statistics) = statistics {
            add(&statistics.component_bytes_hashed, count as u64);
        }
        if matches!(retention, Retention::Component) {
            bytes
                .try_reserve_exact(count)
                .map_err(|_| allocation_error())?;
            bytes.extend_from_slice(&scratch[..count]);
        }
    }
    Ok(ComponentRead {
        digest: format_digest(hasher.finalize().into()),
        size,
        bytes,
    })
}

fn too_large() -> PlatformError {
    resource_exhausted("stored component artifact exceeds configured byte limit")
}

fn allocation_error() -> PlatformError {
    resource_exhausted("stored component allocation exceeds available capacity")
}

#[cfg(test)]
mod tests;
