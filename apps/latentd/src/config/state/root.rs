//! A deliberate protected-root selection is operator data, never authority.
use latent_core::PlatformError;
use serde::Deserialize;
use std::path::{Component, Path, PathBuf};

pub(super) fn present<'de, D: serde::Deserializer<'de>>(
    source: D,
) -> Result<Option<PathBuf>, D::Error> {
    PathBuf::deserialize(source).map(Some)
}

pub(super) fn derive(value: Option<&Path>) -> Result<Option<PathBuf>, PlatformError> {
    let Some(path) = value else {
        return Ok(None);
    };
    if !path.is_absolute()
        || path.as_os_str().len() > 4096
        || path
            .components()
            .any(|part| matches!(part, Component::ParentDir))
        || path
            .to_str()
            .is_none_or(|text| text.chars().any(char::is_control))
    {
        return Err(super::super::invalid("state.stateRoot"));
    }
    // Actual root anchors, permissions, links, locks, engine format and live
    // replacement checks remain exclusively owned by ProtectedStoreOwner.
    Ok(Some(path.to_path_buf()))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn default_and_explicit_roots_preserve_original_constraints_without_creating_files() {
        let root = tempfile::tempdir().unwrap();
        let data = root.path().join("data");
        let input = super::super::tests::input();
        let config = serde_json::from_value(input.clone()).unwrap();
        let defaults = super::super::derive(&config).unwrap();
        assert_eq!(defaults.protected_root(&data), data.join("state"));
        let selected = root.path().join("restored-state");
        let mut input = input;
        input["stateRoot"] = serde_json::to_value(&selected).unwrap();
        let config = serde_json::from_value(input).unwrap();
        let settings = super::super::derive(&config).unwrap();
        assert_eq!(settings.protected_root(&data), selected);
        assert!(!settings.create_if_missing);
        assert_eq!(settings.clock_checkpoint, defaults.clock_checkpoint);
        assert_eq!(settings.configuration_epoch, defaults.configuration_epoch);
        assert_eq!(
            settings.tenant_quotas[0].limits,
            defaults.tenant_quotas[0].limits
        );
        assert_eq!(
            settings.operations[0].policies,
            defaults.operations[0].policies
        );
        assert!(!data.exists());
        assert!(!selected.exists());
    }

    #[test]
    fn null_relative_traversal_control_and_oversized_root_inputs_refuse() {
        let mut input = super::super::tests::input();
        input["stateRoot"] = serde_json::Value::Null;
        assert!(serde_json::from_value::<super::super::StateConfig>(input).is_err());
        let root = std::env::temp_dir();
        for path in [
            PathBuf::from("relative-root"),
            root.join("before/../after"),
            root.join("unsafe\nroot"),
            root.join("a".repeat(4097)),
        ] {
            assert!(derive(Some(&path)).is_err());
        }
    }

    #[cfg(all(target_os = "linux", target_arch = "x86_64"))]
    mod native {
        use super::*;
        use latent_core::test_support::coordination::WATCHDOG;
        use latent_state::{
            embedded::StoreError,
            protected_store::{ProtectedStoreConfig, ProtectedStoreError, ProtectedStoreOwner},
        };
        use std::{fs, os::unix::fs::PermissionsExt, time::Instant};

        fn selected(root: &Path, data: &Path) -> ProtectedStoreConfig {
            let mut input = super::super::super::tests::input();
            input["stateRoot"] = serde_json::to_value(root).unwrap();
            let config = serde_json::from_value(input).unwrap();
            let settings = super::super::super::derive(&config).unwrap();
            ProtectedStoreConfig::bounded_linux(settings.protected_root(data))
        }

        async fn finish(owner: &ProtectedStoreOwner) {
            let retired = tokio::time::timeout(
                WATCHDOG,
                owner
                    .drain_async(Instant::now() + WATCHDOG, std::future::pending())
                    .unwrap(),
            )
            .await
            .unwrap();
            assert!(retired.clean && retired.snapshot.physically_retired());
            owner.reap_retired_threads().unwrap();
        }

        async fn refusal(config: ProtectedStoreConfig) -> ProtectedStoreError {
            let mut startup = ProtectedStoreOwner::start(config).unwrap();
            let error = tokio::time::timeout(WATCHDOG, &mut startup)
                .await
                .unwrap()
                .err()
                .unwrap();
            let retired = tokio::time::timeout(
                WATCHDOG,
                startup
                    .drain_async(Instant::now() + WATCHDOG, std::future::pending())
                    .unwrap(),
            )
            .await
            .unwrap();
            assert!(retired.snapshot.physically_retired());
            startup.reap_retired_threads().unwrap();
            error
        }

        #[tokio::test]
        async fn selected_native_owner_reopens_exact_root_and_refuses_links_and_malformed_existing_store(
        ) {
            let directory = std::env::var_os("LATENT_STATE_TEST_ROOT")
                .map_or_else(std::env::temp_dir, PathBuf::from);
            let temporary = tempfile::tempdir_in(directory).unwrap();
            let data = temporary.path().join("unchanged-catalog-data");
            let root = temporary.path().join("selected-state");
            fs::create_dir(&root).unwrap();
            fs::set_permissions(&root, fs::Permissions::from_mode(0o700)).unwrap();
            let mut config = selected(&root, &data);
            config.create_if_missing = true;
            let owner = tokio::time::timeout(
                WATCHDOG,
                ProtectedStoreOwner::start(config.clone()).unwrap(),
            )
            .await
            .unwrap()
            .unwrap();
            assert!(root.join(&config.file_name).is_file());
            assert!(!data.exists(), "no fallback root or catalog is created");
            finish(&owner).await;
            config.create_if_missing = false;
            let owner = tokio::time::timeout(WATCHDOG, ProtectedStoreOwner::start(config).unwrap())
                .await
                .unwrap()
                .unwrap();
            finish(&owner).await;
            let alias = temporary.path().join("linked-state");
            std::os::unix::fs::symlink(&root, &alias).unwrap();
            assert_eq!(
                refusal(selected(&alias, &data)).await,
                ProtectedStoreError::UnsafeRoot
            );
            let malformed = temporary.path().join("invalid-state");
            fs::create_dir(&malformed).unwrap();
            fs::set_permissions(&malformed, fs::Permissions::from_mode(0o700)).unwrap();
            let config = selected(&malformed, &data);
            let path = malformed.join(&config.file_name);
            fs::write(&path, b"malformed-existing-store").unwrap();
            fs::set_permissions(&path, fs::Permissions::from_mode(0o600)).unwrap();
            assert_eq!(
                refusal(config).await,
                ProtectedStoreError::Store(StoreError::Corrupt)
            );
            assert_eq!(fs::read(path).unwrap(), b"malformed-existing-store");
            assert!(!data.exists());
        }
    }
}
