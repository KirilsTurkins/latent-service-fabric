use std::sync::atomic::Ordering;

use latent_activation::ActivationOutcome;
use latent_core::PlatformErrorCode;

use super::model::request;
use super::support::{finish, Harness};

#[tokio::test]
async fn repository_preparation_keeps_optional_imports_and_binds_each_activation() {
    let harness = Harness::standard();
    for id in ["imports-a", "imports-c"] {
        let receipt = finish(harness.manager.start(request(id)).expect("start")).await;
        assert!(matches!(receipt.outcome, ActivationOutcome::Succeeded(_)));
    }
    let requests = harness.backend.requests.lock().expect("requests");
    assert_eq!(requests.len(), 2);
    assert_eq!(requests[0].prepared.key, requests[1].prepared.key);
    for observed in requests.iter() {
        assert_eq!(
            observed
                .imports
                .iter()
                .map(|import| import.contract.as_str())
                .collect::<Vec<_>>(),
            ["latent:context/context@0.1.0", "latent:log/log@0.1.0"]
        );
        for import in &observed.imports {
            assert_eq!(import.capability.0, import.contract);
            assert_eq!(import.opaque_handle, observed.activation.activation_id.0);
        }
    }
    assert_ne!(
        requests[0].imports[0].opaque_handle,
        requests[1].imports[0].opaque_handle
    );
    assert_eq!(harness.artifacts.entered.load(Ordering::Relaxed), 2);
    assert_eq!(harness.backend.preparation_calls.load(Ordering::Relaxed), 2);
    drop(requests);
    harness.assert_idle();
}

#[tokio::test]
async fn untrusted_repository_mismatches_never_reach_backend_preparation() {
    for fault in 3..=6 {
        let harness = Harness::standard();
        harness.artifacts.fail.store(fault, Ordering::Release);
        let receipt = finish(harness.manager.start(request("corrupt")).expect("start")).await;
        let ActivationOutcome::Failed { error, .. } = receipt.outcome else {
            panic!("corrupt artifact must fail");
        };
        assert_eq!(error.code, PlatformErrorCode::CorruptArtifact);
        assert_eq!(harness.artifacts.entered.load(Ordering::Relaxed), 1);
        assert_eq!(harness.backend.preparation_calls.load(Ordering::Relaxed), 0);
        assert_eq!(harness.backend.entered.load(Ordering::Relaxed), 0);
        harness.assert_idle();
    }
}

#[tokio::test]
async fn mismatched_preparation_releases_affine_owner_before_invocation() {
    for fault in [1, 2] {
        let harness = Harness::standard();
        harness
            .backend
            .preparation_fault
            .store(fault, Ordering::Release);
        let receipt = finish(
            harness
                .manager
                .start(request("foreign-prepared"))
                .expect("start"),
        )
        .await;
        let ActivationOutcome::Failed { error, .. } = receipt.outcome else {
            panic!("foreign prepared owner must fail");
        };
        assert_eq!(error.code, PlatformErrorCode::IncompatibleContract);
        assert_eq!(harness.backend.preparation_calls.load(Ordering::Relaxed), 1);
        assert_eq!(harness.backend.entered.load(Ordering::Relaxed), 0);
        harness.assert_idle();
    }
}
