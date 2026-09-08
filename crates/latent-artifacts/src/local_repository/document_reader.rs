//! Bounded encoded-file retention, including growth after opening the file.

use std::fs::{self, File};
use std::io::{ErrorKind, Read};
use std::path::Path;

use latent_core::PlatformError;

use super::{component_reader::SCRATCH_BYTES, corrupt, resource_exhausted};

pub(super) fn read_bounded_file(
    path: &Path,
    limit: usize,
    label: &str,
) -> Result<Vec<u8>, PlatformError> {
    // Check before open so a misplaced FIFO cannot block a compiler worker.
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
    read_stream(file, metadata.len(), limit, label)
}

fn read_stream(
    reader: impl Read,
    initial_length: u64,
    limit: usize,
    label: &str,
) -> Result<Vec<u8>, PlatformError> {
    let oversized = || resource_exhausted(format!("stored {label} exceeds configured byte limit"));
    let allocation = || resource_exhausted("stored release allocation exceeds available capacity");
    let read_limit = u64::try_from(limit)
        .map_err(|_| resource_exhausted("configured file limit cannot fit in u64"))?;
    if initial_length > read_limit {
        return Err(oversized());
    }
    let capacity = usize::try_from(initial_length)
        .map_err(|_| resource_exhausted("stored release file length cannot fit in memory"))?;
    let mut bytes = Vec::new();
    bytes
        .try_reserve_exact(capacity)
        .map_err(|_| allocation())?;
    let mut reader = reader.take(read_limit.saturating_add(1));
    let mut scratch = [0_u8; SCRATCH_BYTES];
    loop {
        let count = match reader.read(&mut scratch) {
            Ok(0) => return Ok(bytes),
            Ok(count) => count,
            Err(error) if error.kind() == ErrorKind::Interrupted => continue,
            Err(_) => return Err(corrupt("completed release data cannot be read")),
        };
        // Keep the sentinel outside the retained document buffer. read_to_end
        // could grow that buffer beyond the admitted ceiling before checking.
        if count > limit - bytes.len() {
            return Err(oversized());
        }
        bytes.try_reserve_exact(count).map_err(|_| allocation())?;
        bytes.extend_from_slice(&scratch[..count]);
    }
}

#[cfg(test)]
mod tests;
