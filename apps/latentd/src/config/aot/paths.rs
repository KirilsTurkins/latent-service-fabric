use super::{invalid, IsolatedAotConfig};
use latent_core::PlatformError;
use std::path::{Component, Path, PathBuf};

pub(super) struct Roots {
    pub key: PathBuf,
    pub blobs: PathBuf,
    pub receipts: PathBuf,
}
impl Roots {
    pub fn check(config: &IsolatedAotConfig, data: &Path) -> Result<Self, PlatformError> {
        let data = prospective(data)?;
        let blobs = prospective(&config.blob_root)?;
        let receipts = prospective(&config.receipt_root)?;
        check(&config.key_file, true)?;
        let parent = config
            .key_file
            .parent()
            .ok_or_else(failure)?
            .canonicalize()
            .map_err(|_| failure())?;
        let key = parent.join(config.key_file.file_name().ok_or_else(failure)?);
        check(&key, true)?;
        for (left, right) in [
            (&data, &blobs),
            (&data, &receipts),
            (&blobs, &receipts),
            (&key, &data),
            (&key, &blobs),
            (&key, &receipts),
        ] {
            if left.starts_with(right) || right.starts_with(left) {
                return Err(failure());
            }
        }
        Ok(Self {
            key,
            blobs,
            receipts,
        })
    }
}

pub(super) fn check(path: &Path, absolute: bool) -> Result<(), PlatformError> {
    if (absolute && !path.is_absolute())
        || path.as_os_str().is_empty()
        || path
            .to_str()
            .is_none_or(|text| text.len() > 4096 || text.chars().any(char::is_control))
        || path.components().count() > 256
        || path
            .components()
            .any(|part| matches!(part, Component::ParentDir))
    {
        return Err(failure());
    }
    Ok(())
}

/// Canonicalize the existing ancestor without creating the future cache root.
fn prospective(path: &Path) -> Result<PathBuf, PlatformError> {
    check(path, true)?;
    let mut cursor = path;
    let mut suffix = Vec::new();
    loop {
        match std::fs::symlink_metadata(cursor) {
            Ok(_) => {
                let mut resolved = cursor.canonicalize().map_err(|_| failure())?;
                if !resolved.is_dir() {
                    return Err(failure());
                }
                for name in suffix.into_iter().rev() {
                    resolved.push(name);
                }
                check(&resolved, true)?;
                return Ok(resolved);
            }
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => {
                suffix.push(cursor.file_name().ok_or_else(failure)?);
                cursor = cursor.parent().ok_or_else(failure)?;
            }
            Err(_) => return Err(failure()),
        }
    }
}

fn failure() -> PlatformError {
    invalid("isolatedAot.paths")
}
