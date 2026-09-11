use std::future::Future;
use std::pin::Pin;
use std::sync::atomic::{AtomicBool, AtomicUsize, Ordering};
use std::sync::Arc;
use std::task::{Context, Poll, Waker};

use latent_artifacts::{
    ArtifactDescriptor, ArtifactPage, ArtifactQuery, ArtifactRepository, CapsuleArtifact,
    VerifiedArtifactMetadata,
};
use latent_core::{BoxFuture, PlatformError, ReleaseDigest, RouteGeneration};
use latent_routing::RouteResolver;

use super::super::fixtures::*;
use super::{observed, receipt, Operation, Outcome};
use crate::{CatalogWorkObserver, DeploymentStore};

struct WaitingRepository {
    releases: Releases,
    observer: CatalogWorkObserver,
    dropped: AtomicUsize,
    panic_on_poll: AtomicBool,
}

struct PendingMetadata<'a>(&'a WaitingRepository);
impl Future for PendingMetadata<'_> {
    type Output = Result<VerifiedArtifactMetadata, PlatformError>;
    fn poll(self: Pin<&mut Self>, _: &mut Context<'_>) -> Poll<Self::Output> {
        assert!(
            !self.0.panic_on_poll.load(Ordering::Relaxed),
            "injected fetch panic"
        );
        Poll::Pending
    }
}
impl Drop for PendingMetadata<'_> {
    fn drop(&mut self) {
        // The active operation cannot be retired before its actual metadata future.
        let state = self.0.observer.snapshot();
        assert_eq!(state.active, 1);
        assert_eq!(state.finished + 1, state.started);
        self.0.dropped.fetch_add(1, Ordering::Relaxed);
    }
}

impl ArtifactRepository for WaitingRepository {
    fn resolve<'a>(
        &'a self,
        query: &'a ArtifactQuery,
    ) -> BoxFuture<'a, Result<Option<ArtifactDescriptor>, PlatformError>> {
        self.releases.resolve(query)
    }
    fn fetch<'a>(
        &'a self,
        digest: &'a ReleaseDigest,
    ) -> BoxFuture<'a, Result<CapsuleArtifact, PlatformError>> {
        self.releases.fetch(digest)
    }
    fn fetch_verified_metadata<'a>(
        &'a self,
        _: &'a ReleaseDigest,
    ) -> BoxFuture<'a, Result<VerifiedArtifactMetadata, PlatformError>> {
        Box::pin(PendingMetadata(self))
    }
    fn publish(
        &self,
        artifact: CapsuleArtifact,
    ) -> BoxFuture<'_, Result<ArtifactDescriptor, PlatformError>> {
        self.releases.publish(artifact)
    }
    fn list<'a>(
        &'a self,
        after: Option<&'a ReleaseDigest>,
        limit: usize,
    ) -> BoxFuture<'a, Result<ArtifactPage, PlatformError>> {
        self.releases.list(after, limit)
    }
}

fn waiting(observer: &CatalogWorkObserver) -> Arc<WaitingRepository> {
    Arc::new(WaitingRepository {
        releases: Releases::default(),
        observer: observer.clone(),
        dropped: AtomicUsize::new(0),
        panic_on_poll: AtomicBool::new(false),
    })
}

#[test]
fn dropped_and_unwound_metadata_future_retires_after_owned_cleanup_without_publication() {
    let root = TempRoot::new();
    let observer = CatalogWorkObserver::new();
    let releases = waiting(&observer);
    let digest = releases.releases.add("pending-observed");
    let store = run(Store::open_observed(
        root.0.clone(),
        releases.clone(),
        Limits::default(),
        observer.clone(),
    ))
    .unwrap();
    let mut future = Box::pin(store.apply_many(vec![deployment("blue", "alice", &digest)]));
    assert!(future
        .as_mut()
        .poll(&mut Context::from_waker(Waker::noop()))
        .is_pending());
    assert_eq!(observer.snapshot().active, 1);
    drop(future);
    let dropped = receipt(&observer, 2, Operation::ApplyMany, Outcome::OwnerDropped);
    assert_eq!(dropped.compiled_generation, Some(1));
    assert_eq!(dropped.counts.compiler_calls, 1);
    assert_eq!(dropped.counts.compiler_deployment_encodes, 1);
    assert_eq!(
        dropped.counts.compiler_completed + dropped.counts.compiler_failed,
        0
    );
    assert_eq!(dropped.counts.stage_calls, 0);
    assert_eq!(releases.dropped.load(Ordering::Relaxed), 1);
    assert_eq!(store.generation(), RouteGeneration(0));
    releases.panic_on_poll.store(true, Ordering::Relaxed);
    let unwind = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
        let mut future = Box::pin(store.apply_many(vec![deployment("blue", "alice", &digest)]));
        let _ = future
            .as_mut()
            .poll(&mut Context::from_waker(Waker::noop()));
    }));
    assert!(unwind.is_err());
    receipt(&observer, 3, Operation::ApplyMany, Outcome::OwnerDropped);
    assert_eq!(releases.dropped.load(Ordering::Relaxed), 2);
    assert!(store.writer.try_lock().is_ok());
    assert_eq!(store.generation(), RouteGeneration(0));
}

#[test]
fn dropped_reopen_releases_root_and_artifact_owners_before_returning_drop_receipt() {
    let root = TempRoot::new();
    let original = Arc::new(Releases::default());
    let digest = original.add("pending-reopen");
    let store = run(Store::open(
        root.0.clone(),
        original.clone(),
        Limits::default(),
    ))
    .unwrap();
    run(store.apply_many(vec![deployment("blue", "alice", &digest)])).unwrap();
    drop(store);
    let observer = CatalogWorkObserver::new();
    let releases = waiting(&observer);
    let weak = Arc::downgrade(&releases);
    let mut future = Box::pin(Store::open_observed(
        root.0.clone(),
        releases.clone(),
        Limits::default(),
        observer.clone(),
    ));
    assert!(future
        .as_mut()
        .poll(&mut Context::from_waker(Waker::noop()))
        .is_pending());
    drop(releases);
    drop(future);
    let dropped = receipt(&observer, 1, Operation::Open, Outcome::OwnerDropped);
    assert_eq!(dropped.counts.load_payload_serializations, 1);
    assert_eq!(dropped.counts.compiler_calls, 1);
    assert_eq!(dropped.counts.stage_calls, 0);
    assert!(weak.upgrade().is_none());
    drop(run(Store::open(root.0.clone(), original, Limits::default())).unwrap());
}

#[test]
fn failed_metadata_and_failed_open_are_errors_and_unrelated_unobserved_work_is_not_counted() {
    let root = TempRoot::new();
    let plain_root = TempRoot::new();
    let releases = Arc::new(Releases::default());
    let digest = releases.add("unobserved");
    let observer = CatalogWorkObserver::new();
    let store = observed(&root, &releases, &observer);
    let missing = latent_artifacts::content_digest(b"missing");
    let error = run(store.apply_many(vec![deployment("blue", "alice", &missing)])).unwrap_err();
    assert_eq!(error.code, Code::NotFound);
    let failed = receipt(&observer, 2, Operation::ApplyMany, Outcome::ReturnedError);
    assert_eq!(
        (failed.counts.compiler_calls, failed.counts.compiler_failed),
        (1, 1)
    );
    assert_eq!(
        (
            failed.counts.compiler_deployment_encodes,
            failed.counts.revision_identity_encodes
        ),
        (1, 0)
    );
    assert_eq!(failed.counts.encoder_calls, 0);
    let locked = run(Store::open_observed(
        root.0.clone(),
        releases.clone(),
        Limits::default(),
        observer.clone(),
    ));
    assert_eq!(locked.err().unwrap().message, "catalog-root-already-owned");
    let failed_open = receipt(&observer, 3, Operation::Open, Outcome::ReturnedError);
    assert_eq!(failed_open.counts, crate::CatalogWorkCounts::default());
    let before = observer.snapshot();
    let plain = run(Store::open(
        plain_root.0.clone(),
        releases,
        Limits::default(),
    ))
    .unwrap();
    run(plain.apply(deployment("green", "alice", &digest))).unwrap();
    drop(plain);
    assert_eq!(observer.snapshot(), before);
    assert_eq!(store.generation(), RouteGeneration(0));
}
