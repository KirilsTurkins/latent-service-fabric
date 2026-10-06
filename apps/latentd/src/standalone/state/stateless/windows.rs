use std::fs::{File, OpenOptions};
use std::os::windows::fs::{MetadataExt, OpenOptionsExt};
use std::path::{Component, Path, PathBuf};

use latent_core::{native_capacity::NativeReservation, PlatformError};

use super::{unavailable, MAXIMUM_COMPONENTS, STATE_DIRECTORY};

const FILE_SHARE_READ: u32 = 1;
const FILE_FLAG_BACKUP_SEMANTICS: u32 = 0x0200_0000;
const FILE_FLAG_OPEN_REPARSE_POINT: u32 = 0x0020_0000;
const FILE_ATTRIBUTE_REPARSE_POINT: u32 = 0x0400;

struct Anchor {
    file: File,
    path: PathBuf,
}

pub(super) fn observe(
    path: &Path,
    original: &NativeReservation,
    before_native_retirement: impl FnOnce(),
) -> Result<bool, PlatformError> {
    let mut anchors = Vec::with_capacity(MAXIMUM_COMPONENTS + 1);
    let mut prefix = PathBuf::new();
    let mut missing = None;
    for component in path.components() {
        prefix.push(component.as_os_str());
        if matches!(component, Component::Prefix(_)) {
            continue;
        }
        live(original)?;
        let file = match OpenOptions::new()
            .read(true)
            // Deny both writes and delete/rename/reparse replacement while
            // each actual ancestor is open. Do not rely on nightly file IDs.
            .share_mode(FILE_SHARE_READ)
            .custom_flags(FILE_FLAG_BACKUP_SEMANTICS | FILE_FLAG_OPEN_REPARSE_POINT)
            .open(&prefix)
        {
            Ok(file) => file,
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => {
                missing = Some(prefix.clone());
                break;
            }
            Err(_) => return Err(unavailable()),
        };
        check_file(&file)?;
        anchors.push(Anchor {
            file,
            path: prefix.clone(),
        });
    }
    if anchors.is_empty() {
        return Err(unavailable());
    }
    let lookup = missing.unwrap_or_else(|| {
        anchors
            .last()
            .expect("private locked ancestor")
            .path
            .join(STATE_DIRECTORY)
    });
    let present = exists(&lookup, original)?;
    before_native_retirement();
    for anchor in &anchors {
        live(original)?;
        check_file(&anchor.file)?;
    }
    let present = present || exists(&lookup, original)?;
    drop(anchors);
    Ok(present)
}

fn check_file(file: &File) -> Result<(), PlatformError> {
    let metadata = file.metadata().map_err(|_| unavailable())?;
    if !metadata.is_dir() || metadata.file_attributes() & FILE_ATTRIBUTE_REPARSE_POINT != 0 {
        return Err(unavailable());
    }
    Ok(())
}

fn exists(path: &Path, original: &NativeReservation) -> Result<bool, PlatformError> {
    live(original)?;
    match std::fs::symlink_metadata(path) {
        Ok(_) => Ok(true),
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => Ok(false),
        Err(_) => Err(unavailable()),
    }
}

fn live(original: &NativeReservation) -> Result<(), PlatformError> {
    original.with_live(|| ()).map_err(|_| unavailable())
}
