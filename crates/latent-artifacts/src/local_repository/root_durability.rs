use std::fs;
use std::path::{Path, PathBuf};

use latent_core::{PlatformError, PlatformErrorCode};

use super::{io_error, sync_dir};

#[cfg(test)]
pub(super) mod faults;

/// Synchronize every link that makes the catalog reachable, leaf to filesystem root.
/// Existing paths need the same sequence: a failed or interrupted creation can
/// leave directory entries present without proving that they are durable.
pub(super) fn create_durable_root(root: &Path) -> Result<PathBuf, PlatformError> {
    // Anchor relative input once so later working-directory changes cannot
    // redirect creation, synchronization, ownership, or repository operations.
    let absolute = if root.is_absolute() {
        root.to_owned()
    } else {
        std::env::current_dir().map_err(io_error)?.join(root)
    };
    fs::create_dir_all(&absolute).map_err(io_error)?;
    let absolute = fs::canonicalize(absolute).map_err(io_error)?;
    for directory in absolute.ancestors() {
        #[cfg(test)]
        faults::checkpoint(directory).map_err(|_| uncertain_durability())?;
        sync_dir(directory).map_err(|_| uncertain_durability())?;
    }
    Ok(absolute)
}

fn uncertain_durability() -> PlatformError {
    PlatformError {
        code: PlatformErrorCode::Unavailable,
        message: "catalog-path-durability-uncertain".to_owned(),
        retryable: true,
        details: Vec::new(),
    }
}
