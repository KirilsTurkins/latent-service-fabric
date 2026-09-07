use std::future::{poll_fn, Future};
use std::sync::atomic::{AtomicUsize, Ordering};
use std::task::{Context, Poll, Waker};

use latent_artifacts::{
    ArtifactDescriptor, ArtifactPage, ArtifactQuery, ArtifactRepository, CapsuleArtifact,
};
use latent_core::{BoxFuture, PlatformError, ReleaseDigest, RouteGeneration};

use super::*;

struct YieldOnceReleases {
    inner: Arc<Releases>,
    fetches: AtomicUsize,
}

impl ArtifactRepository for YieldOnceReleases {
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
            self.fetches.fetch_add(1, Ordering::Relaxed);
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

#[test]
fn relative_root_stays_owned_while_open_is_suspended_at_release_fetch() {
    supervise(
        "deployments::tests::root_identity::during_open::relative_root_stays_owned_while_open_is_suspended_at_release_fetch",
        exercise_suspended_open,
    );
}

fn catalog_files(root: &Path) -> [Vec<u8>; 3] {
    ["catalog.json", "INITIALIZED", ".catalog.lock"]
        .map(|name| fs::read(root.join(name)).expect("persisted catalog file"))
}

fn assert_route(store: &Store, tenant: &str, release: &ReleaseDigest) {
    assert_eq!(
        &store
            .resolve(&target(tenant, None), Some("stable"))
            .expect("owned route")
            .release,
        release
    );
}

fn seed_catalog(
    root: &Path,
    releases: &Arc<Releases>,
    tenant: &str,
    release: &ReleaseDigest,
) -> Store {
    let store = run(Store::open(root, releases.clone(), Limits::default())).unwrap();
    run(store.apply(deployment("blue", tenant, release))).unwrap();
    store
}

fn assert_owned(root: &Path, releases: &Arc<Releases>) {
    let failure = run(Store::open(root, releases.clone(), Limits::default()))
        .err()
        .expect("another opener cannot acquire the original catalog lock");
    assert_eq!(failure.code, Code::Unavailable);
    assert_eq!(failure.message, "catalog-root-already-owned");
}

fn exercise_suspended_open(root: &Path) {
    let directory_a = root.join("a");
    let directory_b = root.join("b");
    fs::create_dir(&directory_a).unwrap();
    fs::create_dir(&directory_b).unwrap();
    let root_a = directory_a.join("catalog");
    let root_b = directory_b.join("catalog");
    let releases = Arc::new(Releases::default());
    let first_a = releases.add("initial-a");
    let first_b = releases.add("initial-b");
    let updated_a = releases.add("updated-a");
    drop(seed_catalog(&root_a, &releases, "alice", &first_a));
    let catalog_b = seed_catalog(&root_b, &releases, "bob", &first_b);
    let original_b = catalog_files(&root_b);
    let marker_a = fs::read(root_a.join("INITIALIZED")).unwrap();
    // This is the supported interruption after state publication but before
    // initialization-marker publication. Restoring it happens after the await.
    fs::remove_file(root_a.join("INITIALIZED")).unwrap();
    let suspended = Arc::new(YieldOnceReleases {
        inner: releases.clone(),
        fetches: AtomicUsize::new(0),
    });

    std::env::set_current_dir(&directory_a).unwrap();
    let mut opening = Box::pin(Store::open("catalog", suspended.clone(), Limits::default()));
    assert!(opening
        .as_mut()
        .poll(&mut Context::from_waker(Waker::noop()))
        .is_pending());
    assert_eq!(suspended.fetches.load(Ordering::Relaxed), 1);
    assert!(!root_a.join("INITIALIZED").exists());
    assert_owned(&root_a, &releases);

    // The shared supervisor runs this scenario in an exact-test child, so no
    // parent process or unrelated parallel test observes these cwd changes.
    std::env::set_current_dir(&directory_b).unwrap();
    let catalog_a = run(opening).expect("resume the original catalog initialization");
    assert_eq!(fs::read(root_a.join("INITIALIZED")).unwrap(), marker_a);
    assert_eq!(catalog_a.root, root_a);
    assert_eq!(catalog_files(&root_b), original_b);
    assert_route(&catalog_a, "alice", &first_a);
    assert_route(&catalog_b, "bob", &first_b);

    run(catalog_a.apply(deployment("blue", "alice", &updated_a))).unwrap();
    assert_route(&catalog_a, "alice", &updated_a);
    assert_eq!(catalog_a.generation(), RouteGeneration(2));
    assert_eq!(catalog_b.generation(), RouteGeneration(1));
    assert_eq!(catalog_files(&root_b), original_b);
    for owned in [&root_a, &root_b] {
        assert_owned(owned, &releases);
    }

    drop(catalog_a);
    let restarted_a = run(Store::open(&root_a, releases.clone(), Limits::default())).unwrap();
    assert_route(&restarted_a, "alice", &updated_a);
    assert_eq!(restarted_a.generation(), RouteGeneration(2));
    assert_eq!(catalog_files(&root_b), original_b);
    drop(catalog_b);
    let restarted_b = run(Store::open(&root_b, releases, Limits::default())).unwrap();
    assert_route(&restarted_b, "bob", &first_b);
    assert_eq!(restarted_b.generation(), RouteGeneration(1));
    assert_eq!(catalog_files(&root_b), original_b);
}
