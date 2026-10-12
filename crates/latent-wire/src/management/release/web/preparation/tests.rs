use super::prepare_ready;
use crate::management::ManagementLimits;
use latent_artifacts::{
    ArtifactDescriptor, ArtifactPage, ArtifactQuery, ArtifactRepository, CapsuleArtifact,
};
use latent_core::{BoxFuture, PlatformError, PlatformErrorCode, ReleaseDigest};
use latent_executor::{
    ExecutionBackend, ExecutionCancellation, ExecutionRequest, GuestOutcome, PreparationKey,
    PreparationReadWait, PreparedComponent, PreparedReadiness,
};
use std::sync::{
    atomic::{AtomicUsize, Ordering},
    Arc,
};
use std::time::{Duration, Instant};

struct Source;

impl ArtifactRepository for Source {
    fn resolve<'a>(
        &'a self,
        _query: &'a ArtifactQuery,
    ) -> BoxFuture<'a, Result<Option<ArtifactDescriptor>, PlatformError>> {
        panic!("web readiness handoff must not resolve another source")
    }

    fn fetch<'a>(
        &'a self,
        _digest: &'a ReleaseDigest,
    ) -> BoxFuture<'a, Result<CapsuleArtifact, PlatformError>> {
        panic!("only the backend may consume its retained source")
    }

    fn publish<'a>(
        &'a self,
        _artifact: CapsuleArtifact,
    ) -> BoxFuture<'a, Result<ArtifactDescriptor, PlatformError>> {
        panic!("preparation cannot publish")
    }

    fn list<'a>(
        &'a self,
        _after: Option<&'a ReleaseDigest>,
        _limit: usize,
    ) -> BoxFuture<'a, Result<ArtifactPage, PlatformError>> {
        panic!("preparation cannot enumerate another source")
    }
}

struct Counts {
    calls: AtomicUsize,
    live: AtomicUsize,
    retired: AtomicUsize,
}

struct Owner(Arc<Counts>, Arc<dyn ArtifactRepository>);

impl Drop for Owner {
    fn drop(&mut self) {
        // Keep the original source until this affine readiness owner retires.
        let _source = &self.1;
        self.0.live.fetch_sub(1, Ordering::SeqCst);
        self.0.retired.fetch_add(1, Ordering::SeqCst);
    }
}

struct Backend {
    source: Arc<dyn ArtifactRepository>,
    key: PreparationKey,
    counts: Arc<Counts>,
    deny: bool,
}

impl ExecutionBackend for Backend {
    fn backend_id(&self) -> &str {
        "timer-handoff"
    }

    fn prepare_ready_from_repository_with_wait<'a>(
        &'a self,
        source: Arc<dyn ArtifactRepository>,
        key: PreparationKey,
        wait: &'a dyn PreparationReadWait,
    ) -> BoxFuture<'a, Result<PreparedReadiness, PlatformError>> {
        assert!(Arc::ptr_eq(&source, &self.source));
        assert_eq!(key, self.key);
        self.counts.calls.fetch_add(1, Ordering::SeqCst);
        Box::pin(async move {
            self.counts.live.fetch_add(1, Ordering::SeqCst);
            let owner = Owner(Arc::clone(&self.counts), source);
            if self.deny {
                return Err(PlatformError {
                    code: PlatformErrorCode::PermissionDenied,
                    message: "private denial must remain redacted".into(),
                    retryable: false,
                    details: Vec::new(),
                });
            }
            let until = wait.now() + Duration::from_millis(10);
            wait.wait_until(until).await;
            assert!(wait.now() >= until);
            Ok(PreparedReadiness::new(
                PreparedComponent {
                    key,
                    backend: self.backend_id().into(),
                    opaque_handle: "same-owned-readiness".into(),
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
        panic!("the RPC cannot bypass owned readiness")
    }

    fn invoke<'a>(
        &'a self,
        _request: ExecutionRequest,
        _cancel: &'a dyn ExecutionCancellation,
    ) -> BoxFuture<'a, Result<GuestOutcome, PlatformError>> {
        panic!("preparation cannot invoke a guest")
    }

    fn release<'a>(
        &'a self,
        _prepared: PreparedComponent,
    ) -> BoxFuture<'a, Result<(), PlatformError>> {
        panic!("the original readiness owner handles retirement")
    }
}

fn backend(deny: bool) -> Backend {
    Backend {
        source: Arc::new(Source),
        key: PreparationKey {
            release: ReleaseDigest(format!("sha256:{}", "a".repeat(64))),
            publication: Some(
                format!("publication:sha256:{}", "b".repeat(64))
                    .parse()
                    .unwrap(),
            ),
            engine_version: "original-engine".into(),
            engine_configuration_digest: "original-profile".into(),
            target_triple: "original-target".into(),
            cpu_feature_set: "original-features".into(),
        },
        counts: Arc::new(Counts {
            calls: AtomicUsize::new(0),
            live: AtomicUsize::new(0),
            retired: AtomicUsize::new(0),
        }),
        deny,
    }
}

#[tokio::test(start_paused = true)]
async fn web_preparation_retains_same_source_and_readiness_pin_with_timer() {
    let backend = backend(false);
    let source_owners = Arc::strong_count(&backend.source);
    let ready = prepare_ready(
        &backend,
        Arc::clone(&backend.source),
        backend.key.clone(),
        Instant::now() + Duration::from_secs(1),
        &ManagementLimits::default(),
    )
    .await
    .unwrap();
    assert_eq!(ready.descriptor().key, backend.key);
    assert_eq!(backend.counts.calls.load(Ordering::SeqCst), 1);
    assert_eq!(backend.counts.live.load(Ordering::SeqCst), 1);
    assert_eq!(backend.counts.retired.load(Ordering::SeqCst), 0);
    assert_eq!(Arc::strong_count(&backend.source), source_owners + 1);
    drop(ready);
    assert_eq!(backend.counts.live.load(Ordering::SeqCst), 0);
    assert_eq!(backend.counts.retired.load(Ordering::SeqCst), 1);
    assert_eq!(Arc::strong_count(&backend.source), source_owners);
}

#[tokio::test(start_paused = true)]
async fn web_preparation_original_deadline_retires_waiting_owner_without_replay() {
    let backend = backend(false);
    let error = prepare_ready(
        &backend,
        Arc::clone(&backend.source),
        backend.key.clone(),
        Instant::now() + Duration::from_millis(3),
        &ManagementLimits::default(),
    )
    .await
    .unwrap_err();
    assert_eq!(error.code(), tonic::Code::DeadlineExceeded);
    assert_eq!(backend.counts.calls.load(Ordering::SeqCst), 1);
    assert_eq!(backend.counts.live.load(Ordering::SeqCst), 0);
    assert_eq!(backend.counts.retired.load(Ordering::SeqCst), 1);
    tokio::time::advance(Duration::from_secs(1)).await;
    assert_eq!(backend.counts.calls.load(Ordering::SeqCst), 1);
}

#[tokio::test(start_paused = true)]
async fn expired_web_preparation_starts_no_backend_or_owner() {
    let backend = backend(false);
    let error = prepare_ready(
        &backend,
        Arc::clone(&backend.source),
        backend.key.clone(),
        Instant::now() - Duration::from_millis(1),
        &ManagementLimits::default(),
    )
    .await
    .unwrap_err();
    assert_eq!(error.code(), tonic::Code::DeadlineExceeded);
    assert_eq!(backend.counts.calls.load(Ordering::SeqCst), 0);
    assert_eq!(backend.counts.live.load(Ordering::SeqCst), 0);
    assert_eq!(backend.counts.retired.load(Ordering::SeqCst), 0);
}

#[tokio::test(start_paused = true)]
async fn web_preparation_hard_denial_is_not_retried_or_relabelled() {
    let backend = backend(true);
    let error = prepare_ready(
        &backend,
        Arc::clone(&backend.source),
        backend.key.clone(),
        Instant::now() + Duration::from_secs(1),
        &ManagementLimits::default(),
    )
    .await
    .unwrap_err();
    assert_eq!(error.code(), tonic::Code::PermissionDenied);
    assert!(!error.message().contains("private denial"));
    assert_eq!(backend.counts.calls.load(Ordering::SeqCst), 1);
    assert_eq!(backend.counts.live.load(Ordering::SeqCst), 0);
    assert_eq!(backend.counts.retired.load(Ordering::SeqCst), 1);
}
