use std::path::Path;

use cap_fs_ext::DirExt;
use latent_artifacts::package::{validate_package_path, PackageLimits};
use latent_core::PlatformError;

use crate::PackageBundle;

/// Writes a new output directory, refusing to overwrite anything. The complete
/// manifest is renamed into place last; failed/interrupted output is not a
/// readable package. This client artifact export is not durable node admission.
pub fn write_package_directory(bundle: &PackageBundle, output: &Path) -> Result<(), PlatformError> {
    let name = output
        .file_name()
        .and_then(|name| name.to_str())
        .ok_or_else(|| crate::invalid("invalid-package-output-name"))?;
    validate_package_path(name, PackageLimits::default())?;
    let parent_path = output
        .parent()
        .filter(|path| !path.as_os_str().is_empty())
        .unwrap_or_else(|| Path::new("."));
    let parent = super::open_root(parent_path)?;
    parent.create_dir(name).map_err(super::io_error)?;
    let root = parent.open_dir_nofollow(name).map_err(super::io_error)?;
    let result = write_contents(bundle, &root);
    if result.is_err() {
        // Remove only the directory handle created and owned by this call.
        let _ = root.remove_open_dir_all();
    }
    result
}

fn write_contents(bundle: &PackageBundle, root: &cap_std::fs::Dir) -> Result<(), PlatformError> {
    let limits = PackageLimits::default();
    root.create_dir("layers").map_err(super::io_error)?;
    let layers = root.open_dir_nofollow("layers").map_err(super::io_error)?;
    for blob in bundle.layers() {
        super::io::write(&layers, blob.path(), blob.bytes(), limits)?;
    }
    super::io::write(root, "config.json", bundle.config_bytes(), limits)?;
    super::io::write(root, "manifest.pending", bundle.manifest_bytes(), limits)?;
    root.rename("manifest.pending", root, "manifest.json")
        .map_err(super::io_error)
}
