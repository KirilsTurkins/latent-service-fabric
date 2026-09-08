//! Explicit bounded file and standard-input reads.

#[cfg(test)]
mod tests;

use std::fs::{self, File};
use std::io::{self, Read};
use std::path::Path;

use crate::error::Failure;

pub const MAXIMUM_MANIFEST_BYTES: usize = 1024 * 1024;
pub const MAXIMUM_CONTRACT_BYTES: usize = 1024 * 1024;

pub fn single_stdin(paths: &[&Path]) -> Result<(), Failure> {
    if paths.iter().filter(|path| **path == Path::new("-")).count() > 1 {
        return Err(Failure::local(
            "multiple-stdin-inputs",
            "Only one input may read standard input.",
        ));
    }
    Ok(())
}

pub fn read(path: &Path, maximum: usize, role: &'static str) -> Result<Vec<u8>, Failure> {
    if path == Path::new("-") {
        return read_bounded(io::stdin().lock(), maximum, role);
    }
    // Reject named pipes and devices before opening: opening a FIFO can block
    // before the command has reached its RPC deadline. Recheck the opened file
    // as well; the filesystem path can change between metadata and open.
    if !fs::metadata(path).map_err(|_| read_error(role))?.is_file() {
        return Err(read_error(role));
    }
    let file = File::open(path).map_err(|_| read_error(role))?;
    if !file.metadata().map_err(|_| read_error(role))?.is_file() {
        return Err(read_error(role));
    }
    read_bounded(file, maximum, role)
}

fn read_bounded(reader: impl Read, maximum: usize, role: &'static str) -> Result<Vec<u8>, Failure> {
    let limit = maximum
        .checked_add(1)
        .and_then(|value| u64::try_from(value).ok())
        .ok_or_else(|| Failure::local("invalid-input-limit", "Invalid input byte limit."))?;
    let mut bytes = Vec::new();
    reader
        .take(limit)
        .read_to_end(&mut bytes)
        .map_err(|_| read_error(role))?;
    if bytes.len() > maximum {
        return Err(Failure::local(
            "input-too-large",
            "Input exceeds its configured byte limit.",
        ));
    }
    Ok(bytes)
}

fn read_error(role: &'static str) -> Failure {
    let message = match role {
        "component" => "Could not read the component input.",
        "payload" => "Could not read the payload input.",
        "manifest" => "Could not read the manifest input.",
        "contracts" => "Could not read the contract metadata input.",
        "budget" => "Could not read the budget input.",
        "configuration" => "Could not read the credential configuration.",
        _ => "Could not read the requested input.",
    };
    Failure::local("input-read-failed", message)
}
