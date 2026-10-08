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
    fail_at: AtomicUsize,
    report_currentness: AtomicBool,
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
        let renewal = self.renewals.fetch_add(1, Ordering::SeqCst) + 1;
        if self.unavailable.load(Ordering::SeqCst) || self.fail_at.load(Ordering::SeqCst) == renewal
        {
            let mut failure = unavailable();
            if self.report_currentness.load(Ordering::SeqCst) {
                failure.details.push(latent_core::ErrorDetail {
                    kind: "admission.currentness".into(),
                    fields: latent_core::Metadata::from([(
                        "reason".into(),
                        "admission-clock-lease-uncovered".into(),
                    )]),
                });
            }
            Err(failure)
        } else {
            Ok(())
        }
    }

    fn verify(&self, _: &TenantId, _: PackageAdmissionUpload) -> Result<VerifiedAdmission> {
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

#[test]
fn managed_preparation_renews_each_distinct_package_without_retry_or_partial_effect() {
    let root = TempRoot::new();
    let releases = Arc::new(Releases::default());
    let one = releases.add("control-window-one");
    let two = releases.add("control-window-two");
    let three = releases.add("control-window-three");
    let mut store = open(&root, &releases);
    for (state, id, release) in [
        (0, "blue", &one),
        (1, "green", &two),
        (2, "red", &three),
        (3, "clone", &one),
    ] {
        drop(execute(&store, apply(id, state, id, 0, release)));
    }
    let authority = Arc::new(Lease::default());
    store.admission = Some(authority.clone());
    let original = bytes(&root);
    let request = delete("remove-clone", 4, "clone", 4);
    let fetched = releases.fetches.load(Ordering::SeqCst);

    // Initial preparation renewal, first distinct package, then fail before
    // reading the second package. Neither that read nor any effect is retried.
    authority.fail_at.store(3, Ordering::SeqCst);
    assert_eq!(
        run(store.prepare_operation(request.clone()))
            .err()
            .unwrap()
            .message,
        "test-control-lease-unavailable"
    );
    assert_eq!(authority.renewals.load(Ordering::SeqCst), 3);
    assert_eq!(releases.fetches.load(Ordering::SeqCst), fetched + 1);
    assert_eq!(bytes(&root), original);
    assert!(matches!(
        lookup(&store, "remove-clone").value(),
        DeploymentOperationLookup::Unknown { .. }
    ));

    authority.fail_at.store(0, Ordering::SeqCst);
    let prepared = run(store.prepare_operation(request)).unwrap();
    assert_eq!(authority.renewals.load(Ordering::SeqCst), 7);
    assert_eq!(releases.fetches.load(Ordering::SeqCst), fetched + 4);
    assert_eq!(bytes(&root), original);
    drop(prepared); // Cancellation before commit has no deployment effect.
    assert_eq!(bytes(&root), original);
}

#[test]
fn preparation_lease_diagnostic_preserves_rejection_without_read_or_mutation_retry() {
    let root = TempRoot::new();
    let releases = Arc::new(Releases::default());
    let release = releases.add("closed-initial-lease");
    let mut store = open(&root, &releases);
    let authority = Arc::new(Lease::default());
    authority.unavailable.store(true, Ordering::SeqCst);
    authority.report_currentness.store(true, Ordering::SeqCst);
    store.admission = Some(authority.clone());
    let original = bytes(&root);
    let fetched = releases.fetches.load(Ordering::SeqCst);
    let failure = run(store.prepare_operation(apply("lease-rejected", 0, "blue", 0, &release)))
        .err()
        .unwrap();
    assert_eq!(failure.code, PlatformErrorCode::Unavailable);
    assert_eq!(failure.message, "test-control-lease-unavailable");
    assert!(failure.retryable);
    assert_eq!(
        failure.details[0].fields["reason"],
        "admission-clock-lease-uncovered"
    );
    assert_eq!(failure.details[1].kind, "admission.control-stage");
    assert_eq!(failure.details[1].fields["stage"], "prepare-lease");
    assert_eq!(authority.renewals.load(Ordering::SeqCst), 1);
    assert_eq!(releases.fetches.load(Ordering::SeqCst), fetched);
    assert_eq!(bytes(&root), original);
    assert!(matches!(
        lookup(&store, "lease-rejected").value(),
        DeploymentOperationLookup::Unknown { .. }
    ));
}

#[test]
fn package_lease_diagnostic_preserves_one_read_and_cancels_unpublished_catalog() {
    let root = TempRoot::new();
    let releases = Arc::new(Releases::default());
    let one = releases.add("closed-package-one");
    let two = releases.add("closed-package-two");
    let mut store = open(&root, &releases);
    drop(execute(&store, apply("create-one", 0, "blue", 0, &one)));
    drop(execute(&store, apply("create-two", 1, "green", 0, &two)));
    let authority = Arc::new(Lease::default());
    authority.fail_at.store(3, Ordering::SeqCst);
    authority.report_currentness.store(true, Ordering::SeqCst);
    store.admission = Some(authority.clone());
    let original = bytes(&root);
    let fetched = releases.fetches.load(Ordering::SeqCst);
    let failure = run(store.prepare_operation(apply("package-rejected", 2, "clone", 0, &one)))
        .err()
        .unwrap();
    assert_eq!(failure.code, PlatformErrorCode::Unavailable);
    assert_eq!(failure.message, "test-control-lease-unavailable");
    assert!(failure.retryable);
    assert_eq!(
        failure.details[0].fields["reason"],
        "admission-clock-lease-uncovered"
    );
    assert_eq!(failure.details[1].kind, "admission.control-stage");
    assert_eq!(failure.details[1].fields["stage"], "package-lease");
    assert_eq!(authority.renewals.load(Ordering::SeqCst), 3);
    assert_eq!(releases.fetches.load(Ordering::SeqCst), fetched + 1);
    assert_eq!(bytes(&root), original);
    assert!(matches!(
        lookup(&store, "package-rejected").value(),
        DeploymentOperationLookup::Unknown { .. }
    ));
}
