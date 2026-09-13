use std::sync::Arc;

use latent_core::{PlatformErrorCode, SystemActivationClock};
use tempfile::TempDir;

use super::Catalogs;
use crate::config::{NodeConfig, NodeSettings, SupplyChainSettings};

#[cfg(all(target_os = "linux", target_arch = "x86_64"))]
mod aot;
#[cfg(target_os = "linux")]
mod audit;
#[cfg(target_os = "linux")]
mod control;
#[cfg(target_os = "linux")]
mod deployment_operations;
#[cfg(target_os = "linux")]
mod rollouts;
#[cfg(all(target_os = "linux", target_arch = "x86_64"))]
mod trust_currentness;

fn settings(directory: &TempDir) -> NodeSettings {
    let config: NodeConfig = serde_json::from_value(serde_json::json!({
        "formatVersion":1, "dataDirectory":directory.path().join("node"),
        "nodeId":"startup-test", "bind":"127.0.0.1:0",
        "credentials":[{"token":"test-token-000000000000000000000000000000",
            "subject":"operator", "tenant":"tests", "role":"operator"}]
    }))
    .unwrap();
    config.derive().unwrap()
}

fn enforce(settings: &mut NodeSettings) {
    // The mode gate must run before this intentionally unusable policy can be
    // opened or any catalog/runtime can be created.
    settings.supply_chain = SupplyChainSettings::Enforced {
        policy: Box::from(&b"{}"[..]),
        lease_seconds: 5,
    };
}

#[tokio::test]
async fn local_and_observed_open_reject_enforced_mode_before_creating_storage() {
    let directory = TempDir::new().unwrap();
    let mut settings = settings(&directory);
    enforce(&mut settings);
    assert_eq!(
        Catalogs::open(&settings).await.err().unwrap().code,
        PlatformErrorCode::PermissionDenied
    );
    assert_eq!(
        Catalogs::open_observed(
            &settings,
            latent_control_store::CatalogWorkObserver::default(),
        )
        .await
        .err()
        .unwrap()
        .code,
        PlatformErrorCode::PermissionDenied
    );
    assert!(!settings.data_directory.exists());
}

#[tokio::test]
async fn compose_rejects_local_catalogs_under_enforced_settings() {
    let directory = TempDir::new().unwrap();
    let mut settings = settings(&directory);
    let catalogs = Catalogs::open(&settings).await.unwrap();
    enforce(&mut settings);
    assert_eq!(
        super::StandaloneNode::compose(&mut settings, &catalogs, Arc::new(SystemActivationClock))
            .err()
            .unwrap()
            .code,
        PlatformErrorCode::PermissionDenied
    );
}

#[tokio::test]
async fn compose_rejects_mixed_local_catalog_owners_before_starting_services() {
    let directories = [TempDir::new().unwrap(), TempDir::new().unwrap()];
    let mut settings = settings(&directories[0]);
    let mut catalogs = Catalogs::open(&settings).await.unwrap();
    assert!(catalogs
        .deployments
        .is_bound_to_catalog(&catalogs.artifacts.lifecycle_authority()));
    let other_settings = super::tests::settings(&directories[1]);
    let other = Catalogs::open(&other_settings).await.unwrap();
    catalogs.deployments = other.deployments;
    assert_eq!(
        super::StandaloneNode::compose(&mut settings, &catalogs, Arc::new(SystemActivationClock))
            .err()
            .unwrap()
            .code,
        PlatformErrorCode::PermissionDenied
    );
}
