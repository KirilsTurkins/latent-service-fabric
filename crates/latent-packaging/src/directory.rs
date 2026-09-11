//! Explicit regular-file inputs and manifest-last output directories. Root paths
//! are caller-approved ambient authority; every descendant uses a capability
//! directory handle with symlink following disabled at each path segment.
mod io;
mod read;
mod write;

pub use read::{decode_package_source, read_package_directory, read_package_input};
pub use write::write_package_directory;

use cap_std::fs::Dir;
use latent_core::{PlatformError, PlatformErrorCode};
use std::path::Path;

fn open_root(root: &Path) -> Result<Dir, PlatformError> {
    Dir::open_ambient_dir(root, cap_std::ambient_authority()).map_err(io_error)
}

fn io_error(_: std::io::Error) -> PlatformError {
    // Filesystem paths and error messages may contain private local information.
    crate::error(
        PlatformErrorCode::CorruptArtifact,
        "package-file-access-failed",
    )
}
