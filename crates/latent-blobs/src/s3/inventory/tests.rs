use super::{Phase, Record};
use crate::s3::*;
use latent_artifacts::{DirectoryArtifactRepository, DirectoryArtifactRepositoryConfig};
use latent_capabilities::broker::{
    io::{IoLimits, IoRuntime},
    pools::{ProviderPoolLimits, ProviderPools},
    ActivationCapabilityBroker, CapabilityBrokerLimits,
};
use latent_core::{ActivationClock, ClockSample};
use latent_http::{
    HttpAddressPolicy, HttpDestination, HttpLimits, HttpProviderConfig, HttpResolution,
};
use latent_policy::capability::{HttpOrigin, PolicyStore, PolicyStoreLimits};
use std::{
    path::Path,
    sync::Arc,
    time::{Duration, Instant},
};

struct Clock;
impl ActivationClock for Clock {
    fn monotonic_now(&self) -> Instant {
        Instant::now()
    }
    fn sample(&self) -> ClockSample {
        ClockSample::system_now()
    }
}
fn pools(path: &Path) -> ProviderPools {
    let catalog = DirectoryArtifactRepository::open(
        path.join("catalog"),
        DirectoryArtifactRepositoryConfig::default(),
    )
    .unwrap();
    let policies = Arc::new(
        PolicyStore::open(
            &path.join("policies"),
            PolicyStoreLimits::default(),
            catalog.lifecycle_authority(),
        )
        .unwrap(),
    );
    let broker = Arc::new(
        ActivationCapabilityBroker::new(
            catalog.lifecycle_authority(),
            policies,
            Arc::new(Clock),
            CapabilityBrokerLimits::default(),
        )
        .unwrap(),
    );
    ProviderPools::new(
        broker,
        Arc::new(IoRuntime::new(IoLimits::default()).unwrap()),
        tokio::runtime::Handle::current(),
        ProviderPoolLimits::default(),
    )
    .unwrap()
}
fn config() -> S3Config {
    S3Config {
        format_version: 1,
        namespace: "private".into(),
        region: "us-east-1".into(),
        bucket: "lsf-test-bucket".into(),
        prefix: "tests/".into(),
        limits: S3Limits {
            maximum_records: 2,
            maximum_object_bytes: 4,
            maximum_stages: 1,
            maximum_staging_bytes: 4,
            maximum_remote_bytes: 4,
            maximum_handles: 1,
        },
        transport: HttpProviderConfig {
            format_version: 1,
            public_roots: true,
            extra_roots: vec![],
            limits: HttpLimits::default(),
            destinations: vec![HttpDestination {
                origin: HttpOrigin {
                    scheme: "https".into(),
                    host: "127.0.0.1".into(),
                    port: 443,
                },
                addresses: HttpAddressPolicy {
                    networks: vec!["127.0.0.0/8".parse().unwrap()],
                    special_addresses: vec!["127.0.0.1".parse().unwrap()],
                },
                resolution: HttpResolution::Static {
                    addresses: vec!["127.0.0.1".parse().unwrap()],
                },
                allowed_request_headers: vec![],
                redirect_destinations: vec![],
            }],
        },
    }
}
fn record(tenant: &str) -> Record {
    Record {
        format: 1,
        namespace: "private".into(),
        tenant: tenant.into(),
        digest: format!("sha256:{}", sha(b"data")),
        size: 4,
        media_type: "text/plain".into(),
        nonce: "0".repeat(32),
        parts: vec![sha(b"data")],
        phase: Phase::Ready,
        upload_id: None,
        version: None,
        quiescent: true,
    }
}
async fn clean(pools: &ProviderPools) {
    assert!(pools
        .shutdown(Instant::now() + Duration::from_secs(1))
        .await
        .unwrap()
        .is_clean());
}
#[tokio::test]
async fn uncertain_inventory_survives_restart_and_refuses_duplicate_upload() {
    let root = tempfile::TempDir::new().unwrap();
    let pools = pools(root.path());
    let path = root.path().join("inventory");
    let inventory = S3Inventory::open(&path, &pools, config()).unwrap();
    let (mut entry, active) = inventory.insert(record("a")).unwrap();
    entry.phase = Phase::Uploading;
    entry.upload_id = Some("owned-upload".into());
    entry.quiescent = false;
    inventory.update(&entry, &active).unwrap();
    assert!(inventory.acquire(&entry.key()).is_err());
    assert_eq!(inventory.snapshot().unwrap().active_uploads, 1);
    drop((active, inventory));
    let inventory = S3Inventory::open(&path, &pools, config()).unwrap();
    assert_eq!(inventory.snapshot().unwrap().remote_reserved_bytes, 4);
    assert_eq!(inventory.snapshot().unwrap().unresolved_uploads, 1);
    assert_eq!(inventory.snapshot().unwrap().active_uploads, 0);
    assert!(matches!(
        inventory.insert(record("a")),
        Err(BlobError::Uncertain)
    ));
    assert!(matches!(
        inventory.insert(record("b")),
        Err(BlobError::BudgetExhausted)
    ));
    let (entry, active) = inventory.acquire(&entry.key()).unwrap();
    assert!(!entry.quiescent);
    assert_eq!(
        inventory.remove_aborted(&entry, &active),
        Err(BlobError::Uncertain)
    );
    drop((active, inventory));
    clean(&pools).await;
}
#[tokio::test]
async fn sealed_receipts_are_tenant_scoped_and_pinned_to_exact_versions() {
    let root = tempfile::TempDir::new().unwrap();
    let pools = pools(root.path());
    let path = root.path().join("inventory");
    let mut config = config();
    config.limits.maximum_remote_bytes = 8;
    let inventory = S3Inventory::open(&path, &pools, config.clone()).unwrap();
    for (tenant, version) in [("a", "v1"), ("b", "v2")] {
        let (mut entry, active) = inventory.insert(record(tenant)).unwrap();
        entry.phase = Phase::Sealed;
        entry.version = Some(version.into());
        inventory.update(&entry, &active).unwrap();
    }
    let reference = record("a").reference();
    assert_eq!(
        inventory
            .lookup("a", &reference)
            .unwrap()
            .version
            .as_deref(),
        Some("v1")
    );
    assert_eq!(
        inventory
            .lookup("b", &reference)
            .unwrap()
            .version
            .as_deref(),
        Some("v2")
    );
    assert!(matches!(
        inventory.lookup("c", &reference),
        Err(BlobError::NotFound)
    ));
    drop(inventory);
    let reopened = S3Inventory::open(&path, &pools, config.clone()).unwrap();
    assert_eq!(reopened.snapshot().unwrap().sealed_objects, 2);
    drop(reopened);
    config.namespace = "other".into();
    assert!(matches!(
        S3Inventory::open(&path, &pools, config),
        Err(BlobError::PermissionDenied)
    ));
    clean(&pools).await;
}
#[tokio::test]
async fn crash_sidecars_recover_without_replaying_a_remote_mutation() {
    let root = tempfile::TempDir::new().unwrap();
    let pools = pools(root.path());
    let path = root.path().join("inventory");
    let inventory = S3Inventory::open(&path, &pools, config()).unwrap();
    let (mut entry, active) = inventory.insert(record("a")).unwrap();
    let pending = format!("{}.pending", entry.key());
    entry.phase = Phase::Creating;
    entry.quiescent = false;
    inventory
        .directory
        .write_new(&pending, &serde_json::to_vec(&entry).unwrap())
        .unwrap();
    drop((active, inventory));
    let inventory = S3Inventory::open(&path, &pools, config()).unwrap();
    let (recovered, active) = inventory.acquire(&entry.key()).unwrap();
    assert!(recovered.phase == Phase::Creating && !recovered.quiescent);
    inventory
        .directory
        .write_new(&pending, b"{\"format\":")
        .unwrap();
    drop((active, inventory));
    let inventory = S3Inventory::open(&path, &pools, config()).unwrap();
    let (recovered, active) = inventory.acquire(&entry.key()).unwrap();
    assert!(recovered.phase == Phase::Creating && !recovered.quiescent);
    assert!(!inventory.directory.present(&pending).unwrap());
    drop((active, inventory));
    clean(&pools).await;
}
#[tokio::test]
async fn stage_and_handle_drop_do_not_wait_for_inventory_io() {
    let root = tempfile::TempDir::new().unwrap();
    let pools = pools(root.path());
    let inventory = S3Inventory::open(&root.path().join("inventory"), &pools, config()).unwrap();
    let stage = inventory.stage(Some(4)).unwrap();
    let handle = inventory.handle().unwrap();
    assert!(matches!(
        inventory.stage(Some(0)),
        Err(BlobError::BudgetExhausted)
    ));
    assert!(matches!(
        inventory.handle(),
        Err(BlobError::BudgetExhausted)
    ));
    let locked = inventory.state.lock().unwrap();
    drop((stage, handle)); // Would deadlock if Drop attempted this held I/O lock.
    drop(locked);
    let snapshot = inventory.snapshot().unwrap();
    assert_eq!(
        (
            snapshot.stages,
            snapshot.handles,
            snapshot.reserved_staging_bytes
        ),
        (0, 0, 0)
    );
    drop(inventory);
    clean(&pools).await;
}
#[tokio::test]
async fn unsafe_inventory_files_fail_closed_without_deleting_unknown_entries() {
    use std::os::unix::fs::{symlink, PermissionsExt};
    let root = tempfile::TempDir::new().unwrap();
    let pools = pools(root.path());
    let path = root.path().join("inventory");
    let inventory = S3Inventory::open(&path, &pools, config()).unwrap();
    let (entry, active) = inventory.insert(record("a")).unwrap();
    drop((active, inventory));
    let file = path.join("records").join(format!("{}.json", entry.key()));
    std::fs::set_permissions(&file, std::fs::Permissions::from_mode(0o644)).unwrap();
    assert!(S3Inventory::open(&path, &pools, config()).is_err());
    std::fs::set_permissions(&file, std::fs::Permissions::from_mode(0o600)).unwrap();
    let outside = root.path().join("must-retain");
    std::fs::rename(&file, &outside).unwrap();
    symlink(&outside, &file).unwrap();
    assert!(S3Inventory::open(&path, &pools, config()).is_err());
    assert!(outside.exists());
    clean(&pools).await;
}
