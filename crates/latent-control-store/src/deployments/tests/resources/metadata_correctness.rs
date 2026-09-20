//! Small production-persistence correctness fixture. No physical resource claim.

use std::collections::BTreeMap;
use std::fs;
use std::sync::{Arc, Mutex};
use std::time::Instant;

use latent_artifacts::{
    ArtifactDescriptor, ArtifactPage, ArtifactQuery, ArtifactRepository, CapsuleArtifact,
    DirectoryArtifactRepository, DirectoryArtifactRepositoryConfig, VerifiedArtifactMetadata,
};
use latent_core::{BoxFuture, PlatformError, PublicationId, ReleaseDigest, RouteGeneration};
use latent_manifest::DeploymentManifest;
use latent_routing::RouteResolver;

use super::super::fixtures::*;
use crate::deployments::compiler::ownership::{Counter, Fault, Kind, Session};
use crate::DeploymentStore;

const RELEASES: usize = 4;
const ROUTES: usize = 8;
const DOCUMENTATION_BYTES: usize = 16 * 1024;

// Delegate the metadata read to the real directory repository; do not replace its
// streaming verification with the trait's full-artifact convenience implementation.
struct CountedRepository {
    inner: DirectoryArtifactRepository,
    fetches: Mutex<BTreeMap<ReleaseDigest, usize>>,
}

impl CountedRepository {
    fn observe(&self, digest: &ReleaseDigest) {
        *self.fetches.lock().unwrap().entry(digest.clone()).or_default() += 1;
    }

    fn take_fetches(&self) -> BTreeMap<ReleaseDigest, usize> {
        std::mem::take(&mut *self.fetches.lock().unwrap())
    }
}

impl ArtifactRepository for CountedRepository {
    fn resolve<'a>(
        &'a self,
        query: &'a ArtifactQuery,
    ) -> BoxFuture<'a, Result<Option<ArtifactDescriptor>, PlatformError>> {
        self.inner.resolve(query)
    }

    fn fetch<'a>(
        &'a self,
        _digest: &'a ReleaseDigest,
    ) -> BoxFuture<'a, Result<CapsuleArtifact, PlatformError>> {
        panic!("compilation must use production verified metadata, not a full-artifact adapter")
    }

    fn fetch_verified_metadata<'a>(
        &'a self,
        digest: &'a ReleaseDigest,
    ) -> BoxFuture<'a, Result<VerifiedArtifactMetadata, PlatformError>> {
        self.observe(digest);
        self.inner.fetch_verified_metadata(digest)
    }

    fn fetch_verified_metadata_selected<'a>(
        &'a self,
        digest: &'a ReleaseDigest,
        publication: Option<&'a PublicationId>,
    ) -> BoxFuture<'a, Result<VerifiedArtifactMetadata, PlatformError>> {
        self.observe(digest);
        self.inner.fetch_verified_metadata_selected(digest, publication)
    }

    fn publish<'a>(
        &'a self,
        artifact: CapsuleArtifact,
    ) -> BoxFuture<'a, Result<ArtifactDescriptor, PlatformError>> {
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

fn fixture(root: &TempRoot) -> (Arc<CountedRepository>, Vec<ReleaseDigest>) {
    let started = Instant::now();
    let inner = DirectoryArtifactRepository::open(
        root.0.join("releases"),
        DirectoryArtifactRepositoryConfig::default(),
    )
    .unwrap();
    let digests = (0..RELEASES)
        .map(|index| {
            let mut value = artifact(&format!("small-metadata-{index}"));
            value.contracts[0].interfaces[0].documentation = Some("d".repeat(DOCUMENTATION_BYTES));
            let expected = value.descriptor.release_digest.clone();
            let descriptor = run(inner.publish(value)).unwrap();
            assert_eq!(descriptor.release_digest, expected);
            let restored = run(inner.fetch(&expected)).unwrap();
            assert_eq!(
                restored.contracts[0].interfaces[0].documentation.as_deref(),
                Some("d".repeat(DOCUMENTATION_BYTES).as_str())
            );
            expected
        })
        .collect();
    println!(
        "metadata-correctness mode=publish releases={RELEASES} documentation_bytes={} elapsed_ns={}",
        RELEASES * DOCUMENTATION_BYTES,
        started.elapsed().as_nanos()
    );
    (
        Arc::new(CountedRepository {
            inner,
            fetches: Mutex::new(BTreeMap::new()),
        }),
        digests,
    )
}

fn desired(digests: &[ReleaseDigest], distinct: bool) -> Vec<DeploymentManifest> {
    (0..ROUTES)
        .map(|index| {
            let tenant = if distinct {
                "alice".to_owned()
            } else {
                format!("tenant-{index}")
            };
            // IDs interleave the four digests instead of accidentally pre-grouping them.
            deployment(
                &format!("route-{index:02}"),
                &tenant,
                &digests[if distinct { index % RELEASES } else { 0 }],
            )
        })
        .collect()
}

fn validate_ownership(counters: [Counter; 2], groups: usize) -> Result<(), &'static str> {
    for (kind, growth_error, drop_error) in [
        (Kind::Release, "release-ownership-growth", "release-not-dropped"),
        (
            Kind::Canonical,
            "canonical-ownership-growth",
            "canonical-not-dropped",
        ),
    ] {
        let counter = counters[kind as usize];
        if counter.peak_bytes != DOCUMENTATION_BYTES {
            return Err(growth_error);
        }
        if counter.live_bytes != 0 || counter.dropped != counter.acquired {
            return Err(drop_error);
        }
        if counter.acquired != groups {
            return Err("grouped-metadata-or-fingerprint-count");
        }
    }
    Ok(())
}

fn check_routes(store: &Store, desired: &[DeploymentManifest]) {
    assert_eq!(store.generation(), RouteGeneration(1));
    assert_eq!(run(store.list()).unwrap().len(), ROUTES);
    for deployment in desired {
        let resolved = store
            .resolve(
                &target(
                    &deployment.metadata.tenant.as_ref().unwrap().0,
                    Some(&deployment.id.0),
                ),
                Some("stable"),
            )
            .unwrap();
        assert_eq!(resolved.release, deployment.release);
        assert_eq!(resolved.route_generation, RouteGeneration(1));
    }
}

#[test]
fn small_metadata_releases_and_scopes_do_not_accumulate_owned_documentation() {
    let root = TempRoot::new();
    let (releases, digests) = fixture(&root);
    let limits = Limits {
        max_state_bytes: 512 * 1024,
        ..Limits::default()
    };
    for distinct in [true, false] {
        let path = root.0.join(if distinct { "distinct" } else { "shared" });
        let desired = desired(&digests, distinct);
        let expected_fetches: BTreeMap<_, _> = desired
            .iter()
            .map(|value| (value.release.clone(), 1))
            .collect();
        let groups = expected_fetches.len();
        let store = run(Store::open(path.clone(), releases.clone(), limits)).unwrap();
        assert!(releases.take_fetches().is_empty());
        let started = Instant::now();
        let observation = Session::start(Fault::None);
        run(store.apply_many(desired.clone())).unwrap();
        let counters = observation.counters();
        assert_eq!(validate_ownership(counters, groups), Ok(()), "{counters:?}");
        assert_eq!(releases.take_fetches(), expected_fetches);
        check_routes(&store, &desired);
        let expected_snapshot = snapshot(&store);
        let state = fs::read(path.join("catalog.json")).unwrap();
        assert!(!state.is_empty() && state.len() < limits.max_state_bytes);
        println!(
            "metadata-correctness mode=apply distinct={distinct} groups={groups} routes={ROUTES} elapsed_ns={} counters={counters:?}",
            started.elapsed().as_nanos()
        );
        drop(observation);
        drop(store);

        let started = Instant::now();
        let observation = Session::start(Fault::None);
        let store = run(Store::open(path.clone(), releases.clone(), limits)).unwrap();
        let counters = observation.counters();
        assert_eq!(validate_ownership(counters, groups), Ok(()), "{counters:?}");
        assert_eq!(releases.take_fetches(), expected_fetches);
        check_routes(&store, &desired);
        assert_eq!(snapshot(&store), expected_snapshot);
        assert_eq!(fs::read(path.join("catalog.json")).unwrap(), state);
        println!(
            "metadata-correctness mode=reopen distinct={distinct} groups={groups} routes={ROUTES} elapsed_ns={} counters={counters:?}",
            started.elapsed().as_nanos()
        );
    }
}

#[test]
fn retained_real_metadata_and_canonical_values_fail_the_same_small_assertion() {
    for (kind, reason) in [
        (Kind::Release, "release-ownership-growth"),
        (Kind::Canonical, "canonical-ownership-growth"),
    ] {
        let root = TempRoot::new();
        let (releases, digests) = fixture(&root);
        let store = run(Store::open(root.0.join("catalog"), releases, Limits::default())).unwrap();
        let observation = Session::start(Fault::Retain(kind));
        let desired = desired(&digests, true);
        run(store.apply_many(desired.clone())).unwrap();
        check_routes(&store, &desired);
        let counters = observation.counters();
        // This is the very same validator used above, not an arbitrary expected panic.
        assert_eq!(validate_ownership(counters, RELEASES), Err(reason));
        let retained = counters[kind as usize];
        assert_eq!(retained.acquired, RELEASES);
        assert_eq!(retained.dropped, 0);
        assert_eq!(retained.live_bytes, RELEASES * DOCUMENTATION_BYTES);
        assert_eq!(retained.peak_bytes, RELEASES * DOCUMENTATION_BYTES);
    }
}
