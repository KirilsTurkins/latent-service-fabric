//! Control lease renewal is distinct from an attempted deployment mutation.
use super::*;
use latent_artifacts::{
    AdmissionAuthority, AdmissionBinding, PackageAdmissionUpload, VerifiedAdmission,
};
use latent_core::{PlatformError, PlatformErrorCode};
use std::sync::atomic::{AtomicBool, AtomicUsize};

#[derive(Default)]
struct Lease {
    renewals: AtomicUsize,
    unavailable: AtomicBool,
}

fn unavailable() -> PlatformError {
    PlatformError {
        code: PlatformErrorCode::Unavailable,
        message: "test-control-lease-unavailable".into(),
        retryable: true,
        details: Vec::new(),
    }
}

impl AdmissionAuthority for Lease {
    fn renew_control_lease(&self) -> Result<()> {
        self.renewals.fetch_add(1, Ordering::SeqCst);
        if self.unavailable.load(Ordering::SeqCst) {
            Err(unavailable())
        } else {
            Ok(())
        }
    }

    fn verify(
        &self,
        _: &TenantId,
        _: PackageAdmissionUpload,
    ) -> Result<VerifiedAdmission> {
        Err(unavailable())
    }

    fn recover(
        &self,
        _: &AdmissionBinding,
        _: PackageAdmissionUpload,
    ) -> Result<VerifiedAdmission> {
        Err(unavailable())
    }
}

#[test]
fn managed_lease_failure_never_mutates_or_renews_a_historical_replay() {
    let root = TempRoot::new();
    let releases = Arc::new(Releases::default());
    let release = releases.add("control-lease");
    let mut store = open(&root, &releases);
    let created = execute(&store, apply("create", 0, "blue", 0, &release));
    let generation = created.value().receipt.object_generation;
    drop(created);
    let authority = Arc::new(Lease::default());
    store.admission = Some(authority.clone());
    let original = bytes(&root);
    let request = delete("delete", 1, "blue", generation);

    authority.unavailable.store(true, Ordering::SeqCst);
    assert_eq!(
        run(store.prepare_operation(request.clone()))
            .err()
            .unwrap()
            .message,
        "test-control-lease-unavailable"
    );
    assert_eq!(bytes(&root), original);
    assert_eq!(authority.renewals.load(Ordering::SeqCst), 1);

    authority.unavailable.store(false, Ordering::SeqCst);
    let prepared = run(store.prepare_operation(request.clone())).unwrap();
    assert_eq!(authority.renewals.load(Ordering::SeqCst), 2);
    authority.unavailable.store(true, Ordering::SeqCst);
    assert_eq!(
        store.commit_operation(prepared).err().unwrap().message,
        "test-control-lease-unavailable"
    );
    assert_eq!(bytes(&root), original);
    assert_eq!(authority.renewals.load(Ordering::SeqCst), 3);
    assert!(matches!(
        lookup(&store, "delete").value(),
        DeploymentOperationLookup::Unknown { .. }
    ));

    // An explicit new attempt is successful after restoring the test authority;
    // neither failing API call above internally repeated a prepare or commit.
    authority.unavailable.store(false, Ordering::SeqCst);
    let committed = execute(&store, request.clone());
    let receipt = committed.value().receipt.clone();
    assert_eq!(authority.renewals.load(Ordering::SeqCst), 5);
    drop(committed);
    let committed_bytes = bytes(&root);
    authority.unavailable.store(true, Ordering::SeqCst);
    let replay = execute(&store, request);
    assert!(replay.value().replayed);
    assert_eq!(replay.value().receipt, receipt);
    assert_eq!(bytes(&root), committed_bytes);
    assert_eq!(authority.renewals.load(Ordering::SeqCst), 5);
}
