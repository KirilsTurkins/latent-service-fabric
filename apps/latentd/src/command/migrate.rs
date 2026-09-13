//! Offline control operation: no listener, guest engine, compiler or workers.
use super::{status, Failure};
use crate::config::NodeConfig;
use latent_artifacts::{
    AdmissionAuthority, AdmissionStorageLimits, CatalogMigrationLimits,
    DirectoryArtifactRepository, LifecycleLimits,
};
use latent_core::PlatformErrorCode;
use std::{io::Write, path::Path, sync::Arc};

pub(super) fn run(path: &Path, limits: CatalogMigrationLimits) -> Result<(), Failure> {
    let settings = NodeConfig::load(path)
        .and_then(|c| c.derive())
        .map_err(|e| Failure::new("configuration", e.code))?;
    let authority = settings
        .supply_chain
        .open(&settings.data_directory, settings.runtime_profile)
        .map_err(|e| Failure::new("supply-chain", e.code))?;
    let catalog = settings.data_directory.join("releases");
    let receipt = if let Some(authority) = authority {
        let authority: Arc<dyn AdmissionAuthority> = authority;
        DirectoryArtifactRepository::migrate_enforced_catalog(
            catalog,
            settings.artifacts,
            AdmissionStorageLimits::default(),
            authority,
            LifecycleLimits::default(),
            limits,
        )
    } else {
        DirectoryArtifactRepository::migrate_catalog(
            catalog,
            settings.artifacts,
            LifecycleLimits::default(),
            limits,
        )
    }
    .map_err(|e| {
        // Closed diagnostics retain the recovery reason without echoing paths,
        // credentials, package metadata or a third-party authority's message.
        let stage = [
            "catalog-migration-use-original-limits",
            "catalog-migration-source-or-configuration-changed",
            "catalog-migration-resource-limit",
            "catalog-legacy-history-required",
            "catalog-is-already-format-two",
        ]
        .into_iter()
        .find(|reason| e.message.starts_with(*reason))
        .unwrap_or("catalog-migration");
        Failure::new(stage, e.code)
    })?;
    let bytes =
        status::encode(&serde_json::json!({"event": "catalog-migrated", "receipt": receipt}))
            .map_err(|_| Failure::new("output", PlatformErrorCode::Internal))?;
    std::io::stdout()
        .lock()
        .write_all(&bytes)
        .map_err(|_| Failure::new("output", PlatformErrorCode::Unavailable))
}
