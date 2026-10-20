//! Real scoped RPC/catalog selection with an affine code-readiness backend.
use super::*;
use crate::support::publish_variant;
use latent_artifacts::ArtifactRepository;
use latent_core::{BoxFuture, PlatformError, PlatformErrorCode, ReleaseDigest};
use latent_executor::{
    ExecutionBackend, ExecutionCancellation, ExecutionRequest, GuestOutcome, PreparationKey,
    PreparationReadWait, PreparedComponent, PreparedReadiness,
};
use std::sync::{
    atomic::{AtomicUsize, Ordering},
    Arc, Mutex,
};
use tokio::sync::Notify;
use tonic::Code;

#[derive(Default)]
struct State {
    mode: AtomicUsize,
    calls: AtomicUsize,
    live: AtomicUsize,
    retired: AtomicUsize,
    keys: Mutex<Vec<PreparationKey>>,
    entered: Notify,
    proceed: Notify,
}
struct Backend(Arc<State>);
struct Owner(Arc<State>, Arc<dyn ArtifactRepository>);
impl Drop for Owner {
    fn drop(&mut self) {
        let _retained_source = &self.1;
        self.0.live.fetch_sub(1, Ordering::SeqCst);
        self.0.retired.fetch_add(1, Ordering::SeqCst);
    }
}
impl ExecutionBackend for Backend {
    fn backend_id(&self) -> &str {
        "owned-setup-test"
    }
    fn preparation_key(&self, release: &ReleaseDigest) -> Result<PreparationKey, PlatformError> {
        Ok(PreparationKey {
            release: release.clone(),
            publication: None,
            engine_version: "original-engine".into(),
            engine_configuration_digest: "original-config".into(),
            target_triple: "original-target".into(),
            cpu_feature_set: "original-cpu".into(),
        })
    }
    fn prepare_ready_from_repository_with_wait<'a>(
        &'a self,
        source: Arc<dyn ArtifactRepository>,
        mut key: PreparationKey,
        _wait: &'a dyn PreparationReadWait,
    ) -> BoxFuture<'a, Result<PreparedReadiness, PlatformError>> {
        self.0.calls.fetch_add(1, Ordering::SeqCst);
        self.0.keys.lock().unwrap().push(key.clone());
        Box::pin(async move {
            self.0.live.fetch_add(1, Ordering::SeqCst);
            let owner = Owner(self.0.clone(), source);
            let mode = self.0.mode.load(Ordering::SeqCst);
            self.0.entered.notify_one();
            if mode == 1 {
                self.0.proceed.notified().await;
            }
            if mode == 2 {
                return Err(PlatformError {
                    code: PlatformErrorCode::PermissionDenied,
                    message: "private source details must not be returned".into(),
                    retryable: false,
                    details: Vec::new(),
                });
            }
            if mode == 3 {
                key.publication = Some(
                    format!("publication:sha256:{}", "f".repeat(64))
                        .parse()
                        .unwrap(),
                );
            }
            Ok(PreparedReadiness::new(
                PreparedComponent {
                    key,
                    backend: self.backend_id().into(),
                    opaque_handle: "private-cache-pin".into(),
                    metadata: Default::default(),
                },
                Vec::new(),
                owner,
            ))
        })
    }
    fn prepare<'a>(
        &'a self,
        _artifact: &'a CapsuleArtifact,
        _key: &'a PreparationKey,
    ) -> BoxFuture<'a, Result<PreparedComponent, PlatformError>> {
        panic!("no legacy preparation fallback")
    }
    fn invoke<'a>(
        &'a self,
        _request: ExecutionRequest,
        _cancel: &'a dyn ExecutionCancellation,
    ) -> BoxFuture<'a, Result<GuestOutcome, PlatformError>> {
        panic!("setup cannot execute a guest")
    }
    fn release<'a>(
        &'a self,
        _prepared: PreparedComponent,
    ) -> BoxFuture<'a, Result<(), PlatformError>> {
        panic!("readiness Drop owns retirement")
    }
}
fn query(publication: proto::PublicationRef) -> proto::PrepareReleaseRequest {
    proto::PrepareReleaseRequest {
        publication: Some(publication),
        lifecycle_generation: 1,
        maximum_wait_millis: 1000,
    }
}
async fn harness(mode: usize) -> (Harness, Arc<State>) {
    let state = Arc::new(State::default());
    state.mode.store(mode, Ordering::SeqCst);
    (
        Harness::with_preparation(
            ManagementLimits::default(),
            Arc::new(Backend(state.clone())),
        )
        .await,
        state,
    )
}
fn retired(state: &State, calls: usize) {
    assert_eq!(state.calls.load(Ordering::SeqCst), calls);
    assert_eq!(state.live.load(Ordering::SeqCst), 0);
    assert_eq!(state.retired.load(Ordering::SeqCst), calls);
}

#[tokio::test]
async fn exact_publications_prepare_without_guest_execution_or_component_cache_alias() {
    let (harness, state) = harness(0).await;
    let (first, release) = publish_variant(&harness, "acme", "1.0.0").await;
    let (second, same_release) = publish_variant(&harness, "acme", "2.0.0").await;
    assert_eq!(release, same_release);
    assert_ne!(first, second);
    for selected in [first.clone(), second.clone()] {
        let result = harness
            .releases_client()
            .prepare_release(request("alice", query(selected.clone())))
            .await
            .unwrap()
            .into_inner();
        assert!(result.prepared);
        assert_eq!(result.publication, Some(selected));
        assert_eq!(result.lifecycle_generation, 1);
        assert_eq!(result.component_digest, release.0);
    }
    let keys = state.keys.lock().unwrap().clone();
    assert_eq!(keys.len(), 2);
    assert_eq!(keys[0].release, keys[1].release);
    assert_eq!(keys[0].publication.as_ref().unwrap().as_str(), first.id);
    assert_eq!(keys[1].publication.as_ref().unwrap().as_str(), second.id);
    assert_ne!(keys[0], keys[1]);
    retired(&state, 2);
    harness.shutdown().await;
}

#[tokio::test]
async fn preparation_denies_unauthenticated_foreign_and_stale_selectors_before_backend() {
    let (harness, state) = harness(0).await;
    let (selected, _) = publish_variant(&harness, "acme", "1.0.0").await;
    let mut client = harness.releases_client();
    assert_eq!(
        client
            .prepare_release(tonic::Request::new(query(selected.clone())))
            .await
            .unwrap_err()
            .code(),
        Code::Unauthenticated
    );
    assert_eq!(
        client
            .prepare_release(request("caller", query(selected.clone())))
            .await
            .unwrap_err()
            .code(),
        Code::PermissionDenied
    );
    assert_eq!(
        client
            .prepare_release(request("bob", query(selected.clone())))
            .await
            .unwrap_err()
            .code(),
        Code::InvalidArgument
    );
    let mut hidden = selected.clone();
    hidden.tenant = "other".into();
    assert_eq!(
        client
            .prepare_release(request("bob", query(hidden)))
            .await
            .unwrap_err()
            .code(),
        Code::NotFound
    );
    for (generation, wait) in [(0, 1000), (1, 0), (1, 300_001), (2, 1000)] {
        let mut input = query(selected.clone());
        input.lifecycle_generation = generation;
        input.maximum_wait_millis = wait;
        let expected = if generation == 2 {
            Code::FailedPrecondition
        } else {
            Code::InvalidArgument
        };
        assert_eq!(
            client
                .prepare_release(request("alice", input))
                .await
                .unwrap_err()
                .code(),
            expected
        );
    }
    assert_eq!(state.calls.load(Ordering::SeqCst), 0);
    assert_eq!(state.live.load(Ordering::SeqCst), 0);
    harness.shutdown().await;
}

#[tokio::test]
async fn original_preparation_deadline_drops_waiting_owner_without_retry_or_activation() {
    let (harness, state) = harness(1).await;
    let (selected, _) = publish_variant(&harness, "acme", "1.0.0").await;
    let mut input = query(selected);
    input.maximum_wait_millis = 1000;
    assert_eq!(
        harness
            .releases_client()
            .prepare_release(request("alice", input))
            .await
            .unwrap_err()
            .code(),
        Code::DeadlineExceeded
    );
    retired(&state, 1);
    harness.shutdown().await;
}

#[tokio::test]
async fn revocation_during_owned_preparation_refuses_success_and_retires_pin() {
    let (harness, state) = harness(1).await;
    let (selected, _) = publish_variant(&harness, "acme", "1.0.0").await;
    let mut client = harness.releases_client();
    let input = query(selected.clone());
    let waiting =
        tokio::spawn(async move { client.prepare_release(request("alice", input)).await });
    tokio::time::timeout(std::time::Duration::from_secs(1), state.entered.notified())
        .await
        .unwrap();
    let result = harness
        .releases_client()
        .change_release_lifecycle(request(
            "alice",
            proto::ChangeReleaseLifecycleRequest {
                publication: Some(selected),
                action: proto::ReleaseLifecycleAction::Revoke as i32,
                operation: Some(proto::ReleaseOperationPrecondition {
                    operation_id: "prepare-revocation".into(),
                    expected_generation: Some(1),
                }),
                reason: proto::ReleaseLifecycleReason::OperatorRevocation as i32,
            },
        ))
        .await
        .unwrap()
        .into_inner();
    assert_eq!(
        result.operation.unwrap().disposition,
        proto::ReleaseOperationDisposition::Committed as i32
    );
    state.proceed.notify_one();
    assert_eq!(
        waiting.await.unwrap().unwrap_err().code(),
        Code::PermissionDenied
    );
    retired(&state, 1);
    harness.shutdown().await;
}

#[tokio::test]
async fn readiness_identity_mismatch_and_hard_denial_are_not_relabelled_or_retried() {
    for mode in [2, 3] {
        let (harness, state) = harness(mode).await;
        let (selected, _) = publish_variant(&harness, "acme", "1.0.0").await;
        let error = harness
            .releases_client()
            .prepare_release(request("alice", query(selected)))
            .await
            .unwrap_err();
        assert_eq!(
            error.code(),
            if mode == 2 {
                Code::PermissionDenied
            } else {
                Code::Internal
            }
        );
        assert!(!error.message().contains("private"));
        retired(&state, 1);
        harness.shutdown().await;
    }
}

#[tokio::test]
async fn unconfigured_preparation_refuses_setup_without_installing_a_backend() {
    let harness = Harness::new(ManagementLimits::default()).await;
    let (selected, _) = publish_variant(&harness, "acme", "1.0.0").await;
    assert_eq!(
        harness
            .releases_client()
            .prepare_release(request("alice", query(selected)))
            .await
            .unwrap_err()
            .code(),
        Code::Unimplemented
    );
    harness.shutdown().await;
}
