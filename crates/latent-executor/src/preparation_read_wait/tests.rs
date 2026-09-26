use std::future::poll_fn;
use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::Arc;
use std::task::{Context, Poll, Waker};

use latent_artifacts::{ArtifactDescriptor, ArtifactPage, ArtifactQuery, ArtifactRepository};
use latent_core::{PlatformError, PlatformErrorCode, PublicationId, ReleaseDigest};

use super::*;
use crate::{
    CapsuleArtifact, ExecutionBackend, ExecutionCancellation, ExecutionRequest, GuestOutcome,
    PreparationKey, PreparedActivation, PreparedComponent, PreparedReadiness,
};

struct NeverWait;
impl PreparationReadWait for NeverWait {
    fn now(&self) -> Instant {
        panic!("legacy preparation must not consult a clock");
    }
    fn wait_until(&self, _: Instant) -> BoxFuture<'_, ()> {
        panic!("legacy preparation must not arm a timer");
    }
}

struct UnusedRepository;
impl ArtifactRepository for UnusedRepository {
    fn resolve<'a>(
        &'a self,
        _: &'a ArtifactQuery,
    ) -> BoxFuture<'a, Result<Option<ArtifactDescriptor>, PlatformError>> {
        panic!("the adapter must not resolve the source");
    }
    fn fetch<'a>(
        &'a self,
        _: &'a ReleaseDigest,
    ) -> BoxFuture<'a, Result<CapsuleArtifact, PlatformError>> {
        panic!("the adapter must not fetch the source");
    }
    fn publish(
        &self,
        _: CapsuleArtifact,
    ) -> BoxFuture<'_, Result<ArtifactDescriptor, PlatformError>> {
        panic!("preparation cannot publish");
    }
    fn list<'a>(
        &'a self,
        _: Option<&'a ReleaseDigest>,
        _: usize,
    ) -> BoxFuture<'a, Result<ArtifactPage, PlatformError>> {
        panic!("preparation cannot list the source");
    }
}

struct Owner(Arc<AtomicUsize>);
impl Drop for Owner {
    fn drop(&mut self) {
        self.0.fetch_add(1, Ordering::Relaxed);
    }
}

struct Legacy {
    source: Arc<dyn ArtifactRepository>,
    key: PreparationKey,
    calls: AtomicUsize,
    polls: AtomicUsize,
    drops: Arc<AtomicUsize>,
}

impl Legacy {
    fn new() -> Self {
        Self {
            source: Arc::new(UnusedRepository),
            key: PreparationKey {
                release: ReleaseDigest("exact-release".into()),
                publication: Some(
                    format!("publication:sha256:{}", "7".repeat(64))
                        .parse::<PublicationId>()
                        .unwrap(),
                ),
                engine_version: "version".into(),
                engine_configuration_digest: "configuration".into(),
                target_triple: "target".into(),
                cpu_feature_set: "features".into(),
            },
            calls: AtomicUsize::new(0),
            polls: AtomicUsize::new(0),
            drops: Arc::new(AtomicUsize::new(0)),
        }
    }
}

fn original_error() -> PlatformError {
    PlatformError {
        code: PlatformErrorCode::Unavailable,
        message: "unchanged legacy failure".into(),
        retryable: true,
        details: vec![],
    }
}

impl ExecutionBackend for Legacy {
    fn backend_id(&self) -> &'static str {
        "legacy"
    }
    fn prepare_ready_from_repository(
        &self,
        source: Arc<dyn ArtifactRepository>,
        key: PreparationKey,
    ) -> BoxFuture<'_, Result<PreparedReadiness, PlatformError>> {
        assert!(Arc::ptr_eq(&source, &self.source));
        assert_eq!(key, self.key);
        self.calls.fetch_add(1, Ordering::Relaxed);
        let owner = Owner(self.drops.clone());
        Box::pin(async move {
            let _owner = owner;
            poll_fn(|_| {
                if self.polls.fetch_add(1, Ordering::Relaxed) == 0 {
                    Poll::Pending
                } else {
                    Poll::Ready(Err(original_error()))
                }
            })
            .await
        })
    }
    fn materialize_ready(
        &self,
        ready: PreparedReadiness,
    ) -> Result<PreparedActivation, PlatformError> {
        self.calls.fetch_add(1, Ordering::Relaxed);
        let (descriptor, imports, _owner) = ready.into_parts::<Owner>().unwrap();
        assert_eq!(descriptor.key, self.key);
        assert!(imports.is_empty());
        Err(original_error())
    }
    fn prepare<'a>(
        &'a self,
        _: &'a CapsuleArtifact,
        _: &'a PreparationKey,
    ) -> BoxFuture<'a, Result<PreparedComponent, PlatformError>> {
        panic!("default must delegate to original readiness method");
    }
    fn invoke<'a>(
        &'a self,
        _: ExecutionRequest,
        _: &'a dyn ExecutionCancellation,
    ) -> BoxFuture<'a, Result<GuestOutcome, PlatformError>> {
        panic!("readiness cannot invoke");
    }
    fn release(&self, _: PreparedComponent) -> BoxFuture<'_, Result<(), PlatformError>> {
        panic!("adapter cannot release a foreign owner");
    }
}

#[test]
fn default_wait_api_delegates_once_without_consulting_timer_or_replaying_failure() {
    let backend = Legacy::new();
    let mut future = backend.prepare_ready_from_repository_with_wait(
        backend.source.clone(),
        backend.key.clone(),
        &NeverWait,
    );
    assert_eq!(backend.calls.load(Ordering::Relaxed), 1);
    assert_eq!(backend.polls.load(Ordering::Relaxed), 0);
    let mut context = Context::from_waker(Waker::noop());
    assert!(future.as_mut().poll(&mut context).is_pending());
    let Poll::Ready(result) = future.as_mut().poll(&mut context) else {
        panic!("the original future must return its original failure");
    };
    assert_eq!(result.unwrap_err(), original_error());
    assert_eq!(backend.calls.load(Ordering::Relaxed), 1);
    assert_eq!(backend.polls.load(Ordering::Relaxed), 2);
    assert_eq!(backend.drops.load(Ordering::Relaxed), 1);
    drop(future);
    assert_eq!(backend.drops.load(Ordering::Relaxed), 1);
}

#[test]
fn default_wait_api_preserves_unpolled_and_pending_future_ownership() {
    for poll_once in [false, true] {
        let backend = Legacy::new();
        let mut future = backend.prepare_ready_from_repository_with_wait(
            backend.source.clone(),
            backend.key.clone(),
            &NeverWait,
        );
        if poll_once {
            assert!(future
                .as_mut()
                .poll(&mut Context::from_waker(Waker::noop()))
                .is_pending());
        }
        assert_eq!(backend.drops.load(Ordering::Relaxed), 0);
        drop(future);
        assert_eq!(backend.calls.load(Ordering::Relaxed), 1);
        assert_eq!(
            backend.polls.load(Ordering::Relaxed),
            usize::from(poll_once)
        );
        assert_eq!(backend.drops.load(Ordering::Relaxed), 1);
    }
}

#[test]
fn default_materialization_wait_delegates_once_without_timer_or_replaying_failure() {
    for poll_once in [false, true] {
        let backend = Legacy::new();
        let descriptor = PreparedComponent {
            key: backend.key.clone(),
            backend: "legacy".into(),
            opaque_handle: "original".into(),
            metadata: Default::default(),
        };
        let ready = PreparedReadiness::new(descriptor, vec![], Owner(backend.drops.clone()));
        let mut future = backend.materialize_ready_with_wait(ready, &NeverWait);
        assert_eq!(backend.calls.load(Ordering::Relaxed), 0);
        assert_eq!(backend.drops.load(Ordering::Relaxed), 0);
        if poll_once {
            let Poll::Ready(result) = future
                .as_mut()
                .poll(&mut Context::from_waker(Waker::noop()))
            else {
                panic!("the default materialization must not wait");
            };
            assert_eq!(result.unwrap_err(), original_error());
        }
        drop(future);
        assert_eq!(
            backend.calls.load(Ordering::Relaxed),
            usize::from(poll_once)
        );
        assert_eq!(backend.drops.load(Ordering::Relaxed), 1);
    }
}
