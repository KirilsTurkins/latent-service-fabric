use std::sync::atomic::Ordering;

use latent_activation::ActivationOutcome;
use latent_core::PlatformErrorCode;

use super::model::request;
use super::support::{finish, Harness};

#[tokio::test]
async fn budget_bridge_delegates_repository_acquisition_without_materializing_again() {
    use super::support::LiveGuard;
    use latent_artifacts::{ArtifactRepository, CapsuleArtifact};
    use latent_core::{BoxFuture, ContractId, PlatformError};
    use latent_executor::{
        ExecutionBackend, ExecutionCancellation, ExecutionRequest, GuestOutcome, PreparationKey,
        PreparedActivation, PreparedComponent, PreparedUse,
    };
    use latent_node::{ActivationBudgetRegistry, BudgetedExecutionBackend};
    use std::sync::Arc;

    struct RepositoryBackend(Arc<std::sync::atomic::AtomicUsize>);
    impl ExecutionBackend for RepositoryBackend {
        fn backend_id(&self) -> &str {
            "repository-fixture"
        }
        fn prepare_from_repository<'a>(
            &'a self,
            _: &'a dyn ArtifactRepository,
            key: &'a PreparationKey,
        ) -> BoxFuture<'a, Result<PreparedActivation, PlatformError>> {
            Box::pin(async move {
                Ok(PreparedActivation {
                    prepared: PreparedUse::new(
                        PreparedComponent {
                            key: key.clone(),
                            backend: self.backend_id().to_owned(),
                            opaque_handle: "affine-repository-fixture".to_owned(),
                            metadata: Default::default(),
                        },
                        LiveGuard::new(&self.0),
                    ),
                    imports: vec![ContractId("optional-contract".to_owned())],
                })
            })
        }
        fn prepare<'a>(
            &'a self,
            _: &'a CapsuleArtifact,
            _: &'a PreparationKey,
        ) -> BoxFuture<'a, Result<PreparedComponent, PlatformError>> {
            Box::pin(async { panic!("repository override must receive preparation") })
        }
        fn invoke<'a>(
            &'a self,
            _: ExecutionRequest,
            _: &'a dyn ExecutionCancellation,
        ) -> BoxFuture<'a, Result<GuestOutcome, PlatformError>> {
            Box::pin(async { panic!("test only acquires a preparation") })
        }
        fn release(&self, _: PreparedComponent) -> BoxFuture<'_, Result<(), PlatformError>> {
            Box::pin(async { panic!("affine pin must clean up through Drop") })
        }
    }
    let repository = super::catalog::Artifacts::default();
    repository.fail.store(2, Ordering::Release);
    let active = Arc::default();
    let inner = Arc::new(RepositoryBackend(Arc::clone(&active)));
    let bridge = BudgetedExecutionBackend::new(inner, ActivationBudgetRegistry::default());
    let key = super::backend::Backend::default()
        .preparation_key(&super::model::artifact(1, 0).descriptor.release_digest)
        .unwrap();
    let prepared = bridge
        .prepare_from_repository(&repository, &key)
        .await
        .unwrap();
    assert_eq!(prepared.prepared.descriptor().key, key);
    assert_eq!(
        prepared.imports,
        [ContractId("optional-contract".to_owned())]
    );
    assert_eq!(repository.entered.load(Ordering::Relaxed), 0);
    assert_eq!(active.load(Ordering::Relaxed), 1);
    drop(prepared);
    assert_eq!(active.load(Ordering::Relaxed), 0);
}

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
