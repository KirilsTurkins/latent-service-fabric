use std::collections::{BTreeMap, BTreeSet};

use cap_fs_ext::DirExt;
use cap_std::fs::Dir;
use latent_core::PlatformError;

pub(super) fn check(root: &Dir, expected: &BTreeMap<String, bool>) -> Result<(), PlatformError> {
    let mut seen = BTreeSet::new();
    scan(root, "", expected, &mut seen)?;
    if seen.len() != expected.len() {
        return Err(crate::invalid("package-directory-inventory-mismatch"));
    }
    Ok(())
}

fn scan(
    dir: &Dir,
    prefix: &str,
    expected: &BTreeMap<String, bool>,
    seen: &mut BTreeSet<String>,
) -> Result<(), PlatformError> {
    for entry in dir.entries().map_err(super::super::io_error)? {
        if seen.len() >= expected.len() {
            return Err(crate::invalid("package-directory-inventory-mismatch"));
        }
        let entry = entry.map_err(super::super::io_error)?;
        let name = entry
            .file_name()
            .into_string()
            .map_err(|_| crate::invalid("package-directory-inventory-mismatch"))?;
        let path = if prefix.is_empty() {
            name.clone()
        } else {
            format!("{prefix}/{name}")
        };
        let directory = expected
            .get(&path)
            .ok_or_else(|| crate::invalid("package-directory-inventory-mismatch"))?;
        let kind = entry.file_type().map_err(super::super::io_error)?;
        if (*directory && !kind.is_dir())
            || (!directory && !kind.is_file())
            || !seen.insert(path.clone())
        {
            return Err(crate::invalid("package-directory-inventory-mismatch"));
        }
        if *directory {
            let child = dir
                .open_dir_nofollow(&name)
                .map_err(super::super::io_error)?;
            scan(&child, &path, expected, seen)?;
        }
    }
    Ok(())
}
