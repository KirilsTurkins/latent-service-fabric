use latent_core::PlatformError;
use std::{
    fs,
    path::{Component, Path, PathBuf},
};

pub(super) fn roots(
    blob: &Path,
    receipt: &Path,
    catalog: &Path,
) -> Result<(PathBuf, PathBuf), PlatformError> {
    let blob = future_path(blob)?;
    let receipt = future_path(receipt)?;
    let catalog = future_path(catalog)?;
    for (left, right) in [(&blob, &receipt), (&blob, &catalog), (&receipt, &catalog)] {
        if left.starts_with(right) || right.starts_with(left) {
            return Err(super::super::invalid());
        }
    }
    Ok((blob, receipt))
}

fn future_path(path: &Path) -> Result<PathBuf, PlatformError> {
    if !path.is_absolute()
        || path.as_os_str().len() > 4096
        || path
            .components()
            .any(|value| matches!(value, Component::ParentDir | Component::CurDir))
    {
        return Err(super::super::invalid());
    }
    let mut current = path;
    let mut missing = Vec::new();
    loop {
        match fs::symlink_metadata(current) {
            Ok(metadata) => {
                if !metadata.is_dir() || metadata.file_type().is_symlink() {
                    return Err(super::super::invalid());
                }
                let mut resolved = current
                    .canonicalize()
                    .map_err(|_| super::super::invalid())?;
                for name in missing.into_iter().rev() {
                    resolved.push(name);
                }
                if resolved.as_os_str().len() > 4096 {
                    return Err(super::super::invalid());
                }
                return Ok(resolved);
            }
            Err(error) if error.kind() == std::io::ErrorKind::NotFound && missing.len() < 64 => {
                missing.push(current.file_name().ok_or_else(super::super::invalid)?);
                current = current.parent().ok_or_else(super::super::invalid)?;
            }
            Err(_) => return Err(super::super::invalid()),
        }
    }
}

#[cfg(all(test, target_os = "linux", target_arch = "x86_64"))]
mod tests {
    use super::*;
    use std::sync::atomic::{AtomicU64, Ordering};

    struct Directory(PathBuf);
    impl Directory {
        fn new() -> Self {
            static NEXT: AtomicU64 = AtomicU64::new(0);
            let path = std::env::temp_dir().join(format!(
                "lsf-native-paths-{}-{}-{}",
                std::process::id(),
                std::time::SystemTime::now()
                    .duration_since(std::time::UNIX_EPOCH)
                    .unwrap()
                    .as_nanos(),
                NEXT.fetch_add(1, Ordering::Relaxed)
            ));
            fs::create_dir(&path).unwrap();
            Self(path)
        }
    }
    impl Drop for Directory {
        fn drop(&mut self) {
            fs::remove_dir_all(&self.0).unwrap();
        }
    }

    #[test]
    fn disjoint_future_roots_are_resolved_without_creating_storage() {
        let directory = Directory::new();
        let blob = directory.0.join("cache/blobs");
        let receipt = directory.0.join("cache/receipts");
        let catalog = directory.0.join("catalog");
        assert_eq!(
            roots(&blob, &receipt, &catalog).unwrap(),
            (blob.clone(), receipt)
        );
        assert!(!blob.parent().unwrap().exists());
        assert!(!catalog.exists());
    }

    #[test]
    fn equal_and_ancestor_roots_cannot_share_catalog_or_storage() {
        let directory = Directory::new();
        let blob = directory.0.join("blobs");
        let receipt = directory.0.join("receipts");
        let catalog = directory.0.join("catalog");
        for (left, right, source) in [
            (&blob, &blob, &catalog),
            (&blob, &receipt, &blob),
            (&directory.0, &receipt, &catalog),
            (&blob, &receipt, &directory.0),
        ] {
            assert!(roots(left, right, source).is_err());
        }
    }

    #[test]
    fn ancestor_alias_cannot_hide_overlap_with_catalog() {
        let directory = Directory::new();
        let catalog = directory.0.join("catalog");
        fs::create_dir(&catalog).unwrap();
        std::os::unix::fs::symlink(&catalog, directory.0.join("alias")).unwrap();
        assert!(roots(
            &directory.0.join("alias/new/blobs"),
            &directory.0.join("receipts"),
            &catalog
        )
        .is_err());
    }

    #[test]
    fn invalid_path_or_excessive_missing_depth_fails_before_mutation() {
        let directory = Directory::new();
        fs::write(directory.0.join("file"), b"owned").unwrap();
        let mut deep = directory.0.clone();
        for _ in 0..65 {
            deep.push("missing");
        }
        for path in [
            PathBuf::from("relative"),
            directory.0.join("../escape"),
            directory.0.join("file"),
            deep,
        ] {
            assert!(future_path(&path).is_err());
        }
        assert_eq!(fs::read(directory.0.join("file")).unwrap(), b"owned");
    }
}
