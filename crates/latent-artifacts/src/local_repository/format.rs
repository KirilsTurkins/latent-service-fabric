//! Admit only the current catalog before cleanup, indexing or authority recovery.

use std::{fs, path::Path};

use latent_core::{PlatformError, PlatformErrorCode};

use super::{corrupt, error, io_error, read_bounded_file};

const LIFECYCLE_MARKER: &[u8] = b"lsf-release-lifecycle-v1\n";

pub(super) fn check_current_format(root: &Path) -> Result<(), PlatformError> {
    for name in ["releases", ".publication-migration"] {
        match fs::symlink_metadata(root.join(name)) {
            Ok(_) => return Err(unsupported()),
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => {}
            Err(error) => return Err(io_error(error)),
        }
    }
    let marker = optional(&root.join("LIFECYCLE_MODE"), 16 * 1024)?;
    if marker
        .as_deref()
        .is_some_and(|value| value != LIFECYCLE_MARKER)
    {
        return Err(unsupported());
    }
    if let Some(mode) = optional(&root.join("lifecycle/MODE"), 4096)? {
        let value: serde_json::Value =
            serde_json::from_slice(&mode).map_err(|_| corrupt("catalog-format-marker"))?;
        if value
            .get("formatVersion")
            .and_then(serde_json::Value::as_u64)
            != Some(2)
        {
            return Err(unsupported());
        }
    } else if marker.is_some()
        || root.join("lifecycle/INITIALIZED").exists()
        || root.join("lifecycle/HEAD").exists()
    {
        return Err(corrupt("catalog-lifecycle-history-missing"));
    }
    Ok(())
}

fn optional(path: &Path, maximum: usize) -> Result<Option<Vec<u8>>, PlatformError> {
    match fs::symlink_metadata(path) {
        Ok(_) => read_bounded_file(path, maximum, "catalog format record").map(Some),
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => Ok(None),
        Err(error) => Err(io_error(error)),
    }
}

fn unsupported() -> PlatformError {
    error(
        PlatformErrorCode::Unavailable,
        "catalog-format-unsupported; preserve the stopped data directory and provision fresh state",
    )
}
