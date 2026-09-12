use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::Arc;
use std::time::Duration;

use latent_admission::NodeLoadSource;
use latent_artifacts::package::artifact_blob_digest;
use latent_core::PlatformError;
use latent_policy::supply_chain::{SupplyChainAuthority, SupplyChainClock, SupplyChainPolicy};
use serde_json::{json, Value};
use tempfile::TempDir;

use super::super::control::StartupControl;

struct Clock {
    now: AtomicU64,
    samples: AtomicU64,
}
impl SupplyChainClock for Clock {
    fn now(&self) -> Result<u64, PlatformError> {
        self.samples.fetch_add(1, Ordering::SeqCst);
        Ok(self.now.load(Ordering::SeqCst))
    }
}

// Deny-all policies need no signing fixtures. These are the documented exact
// canonical policy bytes, so the independent snapshots bind their real digests.
fn policy() -> SupplyChainPolicy {
    let publisher = r#"{"formatVersion":1,"scope":"startup","generation":1,"validFrom":1,"validUntil":10000,"maxSignatureLifetimeSeconds":2000,"maxProofAgeSeconds":60,"keys":[]}"#;
    let builder = r#"{"formatVersion":1,"scope":"startup","generation":1,"validFrom":1,"validUntil":10000,"maxSignatureLifetimeSeconds":2000,"maxProofAgeSeconds":60,"keys":[],"requirements":[]}"#;
    let snapshot = |digest: String, revoked: &str| {
        let mut value = json!({"formatVersion":1,"scope":"startup","policyDigest":digest,
            "generation":1,"validFrom":1,"validUntil":10000,"revokedKeys":[]});
        value[revoked] = json!([]);
        value
    };
    SupplyChainPolicy::from_json(&serde_json::to_vec(&json!({
        "formatVersion":1,"generation":1,"scope":"startup","validFrom":1,"validUntil":10000,
        "tenants":[],"publisher":serde_json::from_str::<Value>(publisher).unwrap(),
        "builder":serde_json::from_str::<Value>(builder).unwrap(),
        "publisherRevocations":snapshot(artifact_blob_digest(publisher.as_bytes()).to_string(),"revokedPublishers"),
        "builderRevocations":snapshot(artifact_blob_digest(builder.as_bytes()).to_string(),"revokedBuilders"),
        "sbom":{"formatVersion":1,"embedded":"required","detached":"optional","requireSource":[],"requireLicense":[]}
    })).unwrap()).unwrap()
}

fn authority(root: &TempDir) -> (Arc<SupplyChainAuthority>, Arc<Clock>) {
    let clock = Arc::new(Clock {
        now: AtomicU64::new(1000),
        samples: AtomicU64::new(0),
    });
    let authority =
        Arc::new(SupplyChainAuthority::open(root.path(), policy(), clock.clone(), 5).unwrap());
    (authority, clock)
}

#[tokio::test(start_paused = true)]
async fn early_owner_renews_past_initial_lease_and_transfers_without_retiring() {
    let root = TempDir::new().unwrap();
    let (authority, clock) = authority(&root);
    let owner = StartupControl::start(
        authority.clone(),
        Duration::from_millis(250),
        &tokio::runtime::Handle::current(),
    );
    let load = owner.load();
    // A startup that lasts longer than the initial lease has the same existing
    // control task ticking while admission is still closed.
    for now in 1001..=1007 {
        clock.now.store(now, Ordering::SeqCst);
        tokio::time::advance(Duration::from_millis(250)).await;
        tokio::task::yield_now().await;
    }
    assert!(!load.snapshot().is_ok_and(|sample| sample.accepting));
    let floor: Value =
        serde_json::from_slice(&std::fs::read(root.path().join("floor.json")).unwrap()).unwrap();
    assert!(floor["restartNotBefore"].as_u64().unwrap() > 1007);
    let sampler = owner.transfer();
    authority.replace_policy(policy()).unwrap();
    authority.retire();
    sampler.shutdown(Duration::from_secs(1)).await.unwrap();
    let observed = clock.samples.load(Ordering::SeqCst);
    tokio::time::advance(Duration::from_secs(1)).await;
    assert_eq!(clock.samples.load(Ordering::SeqCst), observed);
}

#[tokio::test(start_paused = true)]
async fn failed_startup_shutdown_joins_and_cancellation_retires_the_owner() {
    for joined in [true, false] {
        let root = TempDir::new().unwrap();
        let (authority, clock) = authority(&root);
        let owner = StartupControl::start(
            authority.clone(),
            Duration::from_millis(250),
            &tokio::runtime::Handle::current(),
        );
        if joined {
            owner.shutdown(Duration::from_secs(1)).await.unwrap();
        } else {
            drop(owner);
            tokio::task::yield_now().await;
        }
        assert_eq!(
            authority.renew_clock_lease().unwrap_err().message,
            "admission-owner-retired"
        );
        let samples = clock.samples.load(Ordering::SeqCst);
        tokio::time::advance(Duration::from_secs(1)).await;
        assert_eq!(clock.samples.load(Ordering::SeqCst), samples);
    }
}
