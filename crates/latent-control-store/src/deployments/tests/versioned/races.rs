use std::future::poll_fn;
use std::sync::atomic::AtomicBool;
use std::task::{Context, Poll, Waker};

use latent_artifacts::{
    ArtifactDescriptor, ArtifactPage, ArtifactQuery, ArtifactRepository, CapsuleArtifact,
};
use latent_core::{BoxFuture, ReleaseDigest};

use super::super::super::mutations::faults::AfterCommitGuard;
use super::*;

struct PausingReleases {
    inner: Arc<Releases>,
    pause_next: AtomicBool,
}

impl PausingReleases {
    fn arm(&self) {
        assert!(!self.pause_next.swap(true, Ordering::SeqCst));
    }
}

impl ArtifactRepository for PausingReleases {
    fn resolve<'a>(
        &'a self,
        query: &'a ArtifactQuery,
    ) -> BoxFuture<'a, Result<Option<ArtifactDescriptor>, PlatformError>> {
        self.inner.resolve(query)
    }

    fn fetch<'a>(
        &'a self,
        digest: &'a ReleaseDigest,
    ) -> BoxFuture<'a, Result<CapsuleArtifact, PlatformError>> {
        Box::pin(async move {
            if self.pause_next.swap(false, Ordering::SeqCst) {
                let mut yielded = false;
                poll_fn(|context| {
                    if yielded {
                        Poll::Ready(())
                    } else {
                        yielded = true;
                        context.waker().wake_by_ref();
                        Poll::Pending
                    }
                })
                .await;
            }
            self.inner.fetch(digest).await
        })
    }

    fn publish(
        &self,
        artifact: CapsuleArtifact,
    ) -> BoxFuture<'_, Result<ArtifactDescriptor, PlatformError>> {
        self.inner.publish(artifact)
    }

    fn list<'a>(
        &'a self,
        after: Option<&'a ReleaseDigest>,
        limit: usize,
    ) -> BoxFuture<'a, Result<ArtifactPage, PlatformError>> {
        self.inner.list(after, limit)
    }
}

struct Fixture {
    store: Arc<Store>,
    gate: Arc<PausingReleases>,
    one: ReleaseDigest,
    two: ReleaseDigest,
    _root: TempRoot,
}

impl Fixture {
    fn new() -> Self {
        let root = TempRoot::new();
        let releases = Arc::new(Releases::default());
        let one = releases.add("one");
        let two = releases.add("two");
        let gate = Arc::new(PausingReleases {
            inner: releases,
            pause_next: AtomicBool::new(false),
        });
        let store =
            Arc::new(run(Store::open(root.0.clone(), gate.clone(), Limits::default())).unwrap());
        Self {
            store,
            gate,
            one,
            two,
            _root: root,
        }
    }
}

fn poll_pending<T>(future: &mut BoxFuture<'_, T>) {
    assert!(future
        .as_mut()
        .poll(&mut Context::from_waker(Waker::noop()))
        .is_pending());
}

#[test]
fn caller_precondition_is_rechecked_after_same_object_update_or_delete_recreate() {
    for recreate in [false, true] {
        let fixture = Fixture::new();
        let tenant = alice();
        let original = deployment("blue", "alice", &fixture.one);
        let changed = deployment("blue", "alice", &fixture.two);
        run(fixture
            .store
            .apply_versioned(&tenant, original.clone(), Some(0)))
        .unwrap();
        fixture.gate.arm();
        let mut paused = fixture.store.apply_versioned(&tenant, original, Some(1));
        poll_pending(&mut paused);
        if recreate {
            run(fixture
                .store
                .delete_versioned(&tenant, &changed.id, Some(1)))
            .unwrap();
        }
        let committed = run(fixture.store.apply_versioned(&tenant, changed, None)).unwrap();
        assert_conflict(run(paused), "deployment-generation-conflict");
        assert_eq!(record(&fixture.store, "blue"), committed.deployment);
        assert_eq!(fixture.store.generation(), committed.catalog_generation);
    }
}

#[test]
fn create_only_precondition_is_rechecked_after_a_concurrent_creation() {
    let fixture = Fixture::new();
    let tenant = alice();
    let proposed = deployment("blue", "alice", &fixture.one);
    fixture.gate.arm();
    let mut paused = fixture.store.apply_versioned(&tenant, proposed, Some(0));
    poll_pending(&mut paused);
    let committed = run(fixture.store.apply_versioned(
        &tenant,
        deployment("blue", "alice", &fixture.two),
        Some(0),
    ))
    .unwrap();
    assert_conflict(run(paused), "deployment-generation-conflict");
    assert_eq!(record(&fixture.store, "blue"), committed.deployment);
}

#[test]
fn paused_delete_cannot_remove_a_concurrently_updated_object() {
    let fixture = Fixture::new();
    let tenant = alice();
    let blue = deployment("blue", "alice", &fixture.one);
    run(fixture.store.apply_versioned(&tenant, blue.clone(), None)).unwrap();
    run(fixture
        .store
        .apply_versioned(&tenant, deployment("green", "alice", &fixture.one), None))
    .unwrap();
    fixture.gate.arm();
    let mut paused = fixture.store.delete_versioned(&tenant, &blue.id, Some(1));
    poll_pending(&mut paused); // Green keeps the post-delete compile nonempty.
    let committed = run(fixture.store.apply_versioned(
        &tenant,
        deployment("blue", "alice", &fixture.two),
        Some(1),
    ))
    .unwrap();
    assert_conflict(run(paused), "deployment-generation-conflict");
    assert_eq!(record(&fixture.store, "blue"), committed.deployment);
    assert_eq!(record(&fixture.store, "green").generation, 2);
}

#[test]
fn unrelated_compile_conflict_preserves_the_callers_object_stamp_for_retry() {
    let fixture = Fixture::new();
    let tenant = alice();
    run(fixture
        .store
        .apply_versioned(&tenant, deployment("blue", "alice", &fixture.one), None))
    .unwrap();
    let changed = deployment("blue", "alice", &fixture.two);
    fixture.gate.arm();
    let mut paused = fixture
        .store
        .apply_versioned(&tenant, changed.clone(), Some(1));
    poll_pending(&mut paused);
    let unrelated = run(fixture.store.apply_versioned(
        &tenant,
        deployment("green", "alice", &fixture.one),
        None,
    ))
    .unwrap();
    assert_conflict(run(paused), "stale-route-generation");
    assert_eq!(record(&fixture.store, "blue").generation, 1);
    let retried = run(fixture.store.apply_versioned(&tenant, changed, Some(1))).unwrap();
    assert_eq!(retried.deployment.generation, 3);
    assert_eq!(record(&fixture.store, "green"), unrelated.deployment);
}

#[test]
fn apply_receipt_retains_its_own_committed_state_when_another_writer_finishes_first() {
    let fixture = Fixture::new();
    let original = deployment("blue", "alice", &fixture.one);
    let updated = deployment("blue", "alice", &fixture.two);
    let owner = Arc::clone(&fixture.store);
    let expected_update = updated.clone();
    let guard = AfterCommitGuard::new(move || {
        let next = run(owner.apply_versioned(&alice(), updated, Some(1))).unwrap();
        assert_eq!(next.deployment.generation, 2);
    });
    let first = run(fixture
        .store
        .apply_versioned(&alice(), original.clone(), None))
    .unwrap();
    drop(guard);
    assert_eq!(first.deployment.manifest, original);
    assert_eq!(first.deployment.generation, 1);
    assert_eq!(first.catalog_generation, RouteGeneration(1));
    assert_eq!(record(&fixture.store, "blue").manifest, expected_update);
    assert_eq!(record(&fixture.store, "blue").generation, 2);
}

#[test]
fn delete_receipt_identifies_removed_state_even_when_recreation_precedes_its_response() {
    let fixture = Fixture::new();
    let original = deployment("blue", "alice", &fixture.one);
    let created = run(fixture
        .store
        .apply_versioned(&alice(), original.clone(), None))
    .unwrap();
    let recreated = deployment("blue", "alice", &fixture.two);
    let expected_recreated = recreated.clone();
    let owner = Arc::clone(&fixture.store);
    let guard = AfterCommitGuard::new(move || {
        let next = run(owner.apply_versioned(&alice(), recreated, Some(0))).unwrap();
        assert_eq!(next.deployment.generation, 3);
    });
    let deleted = run(fixture
        .store
        .delete_versioned(&alice(), &original.id, Some(1)))
    .unwrap();
    drop(guard);
    assert_eq!(deleted.deleted, created.deployment);
    assert_eq!(deleted.catalog_generation, RouteGeneration(2));
    assert_eq!(record(&fixture.store, "blue").manifest, expected_recreated);
    assert_eq!(record(&fixture.store, "blue").generation, 3);
}

#[test]
fn uncertain_durability_details_identify_the_commit_before_a_later_writers_response() {
    let fixture = Fixture::new();
    let original = deployment("blue", "alice", &fixture.one);
    run(fixture
        .store
        .apply_versioned(&alice(), original.clone(), None))
    .unwrap();
    let owner = Arc::clone(&fixture.store);
    let subsequent = deployment("blue", "alice", &fixture.two);
    let guard = AfterCommitGuard::new(move || {
        let next = run(owner.apply_versioned(&alice(), subsequent, Some(2))).unwrap();
        assert_eq!(next.deployment.generation, 3);
    });
    fixture.store.fail_parent_sync.store(true, Ordering::SeqCst);
    let failure = run(fixture.store.apply_versioned(&alice(), original, Some(1))).unwrap_err();
    drop(guard);
    super::persistence::assert_committed_error(&failure, "blue", "apply", 2, 2);
    assert_eq!(record(&fixture.store, "blue").generation, 3);
    assert_eq!(fixture.store.generation(), RouteGeneration(3));
}
