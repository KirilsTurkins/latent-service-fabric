use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::{Arc, Mutex};

use latent_artifacts::{
    ArtifactDescriptor, ArtifactPage, ArtifactQuery, ArtifactRepository, CapsuleArtifact,
    VerifiedArtifactMetadata,
};
use latent_core::{BoxFuture, PlatformError, ReleaseDigest, RouteGeneration};
use latent_routing::RouteResolver;

use super::fixtures::*;
use crate::DeploymentStore;

/// This adapter deliberately offers no full-fetch path. Checked construction
/// proves actual byte identity; the compiler must consume the additive API.
#[derive(Default)]
struct MetadataOnly {
    releases: Releases,
    requested: Mutex<Vec<ReleaseDigest>>,
    full_fetches: AtomicUsize,
    substitute: Option<ReleaseDigest>,
}

impl ArtifactRepository for MetadataOnly {
    fn resolve<'a>(
        &'a self,
        query: &'a ArtifactQuery,
    ) -> BoxFuture<'a, Result<Option<ArtifactDescriptor>, PlatformError>> {
        self.releases.resolve(query)
    }

    fn fetch<'a>(
        &'a self,
        _digest: &'a ReleaseDigest,
    ) -> BoxFuture<'a, Result<CapsuleArtifact, PlatformError>> {
        Box::pin(async move {
            self.full_fetches.fetch_add(1, Ordering::Relaxed);
            Err(super::super::error(
                Code::Unavailable,
                "full-fetch-disabled",
            ))
        })
    }

    fn fetch_verified_metadata<'a>(
        &'a self,
        digest: &'a ReleaseDigest,
    ) -> BoxFuture<'a, Result<VerifiedArtifactMetadata, PlatformError>> {
        Box::pin(async move {
            self.requested.lock().unwrap().push(digest.clone());
            let artifact = self
                .releases
                .values
                .read()
                .unwrap()
                .get(self.substitute.as_ref().unwrap_or(digest))
                .cloned()
                .ok_or_else(|| super::super::error(Code::NotFound, "release-not-found"))?;
            VerifiedArtifactMetadata::from_artifact(artifact)
        })
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

#[test]
fn compilation_uses_verified_metadata_once_per_release_and_preserves_routes() {
    let root = TempRoot::new();
    let reference_root = TempRoot::new();
    let repository = Arc::new(MetadataOnly::default());
    let one = repository.releases.add("one");
    let two = repository.releases.add("two");
    let store = run(Store::open(
        root.0.clone(),
        repository.clone(),
        Limits::default(),
    ))
    .unwrap();
    let releases = Arc::new(Releases::default());
    releases.add("one");
    releases.add("two");
    let reference = open(&reference_root, &releases);
    // Interleaved deployment IDs must still verify each shared release once.
    let desired = vec![
        deployment("blue", "alice", &one),
        deployment("green", "alice", &two),
        deployment("red", "alice", &one),
    ];
    run(store.apply_many(desired.clone())).unwrap();
    run(reference.apply_many(desired)).unwrap();
    let mut digests = vec![one, two];
    digests.sort();
    assert_eq!(*repository.requested.lock().unwrap(), digests);
    assert_eq!(repository.full_fetches.load(Ordering::Relaxed), 0);
    assert_eq!(releases.fetches.load(Ordering::Relaxed), 2);
    assert_eq!(snapshot(&store).services, snapshot(&reference).services);
    for route in [None, Some("blue"), Some("green"), Some("red")] {
        for key in [None, Some("stable-key"), Some("another-key")] {
            assert_eq!(
                store.resolve(&target("alice", route), key).unwrap(),
                reference.resolve(&target("alice", route), key).unwrap()
            );
        }
    }
    drop(store);
    repository.requested.lock().unwrap().clear();
    let restored = run(Store::open(
        root.0.clone(),
        repository.clone(),
        Limits::default(),
    ))
    .unwrap();
    assert_eq!(*repository.requested.lock().unwrap(), digests);
    assert_eq!(repository.full_fetches.load(Ordering::Relaxed), 0);
    assert_eq!(snapshot(&restored).services, snapshot(&reference).services);
}

#[test]
fn valid_verified_metadata_for_another_release_is_not_adopted() {
    let root = TempRoot::new();
    let releases = Releases::default();
    let requested = releases.add("requested");
    let replacement = releases.add("replacement");
    let repository = Arc::new(MetadataOnly {
        releases,
        substitute: Some(replacement),
        ..MetadataOnly::default()
    });
    let store = run(Store::open(
        root.0.clone(),
        repository.clone(),
        Limits::default(),
    ))
    .unwrap();
    let error = run(store.apply(deployment("blue", "alice", &requested))).unwrap_err();
    assert_eq!(error.code, Code::CorruptArtifact);
    assert_eq!(error.message, "release-digest-mismatch");
    assert_eq!(store.generation(), RouteGeneration(0));
    assert!(snapshot(&store).services.is_empty());
    assert_eq!(repository.full_fetches.load(Ordering::Relaxed), 0);
}

#[test]
fn default_metadata_fetch_verifies_fresh_bytes_length_and_requested_identity() {
    for damage in [
        "bytes",
        "length",
        "descriptor",
        "manifest",
        "another-valid-release",
    ] {
        let root = TempRoot::new();
        let releases = Arc::new(Releases::default());
        let digest = releases.add("one");
        let store = open(&root, &releases);
        run(store.apply(deployment("blue", "alice", &digest))).unwrap();
        let original = snapshot(&store);
        {
            let mut values = releases.values.write().unwrap();
            let value = values.get_mut(&digest).unwrap();
            match damage {
                "bytes" => value.component_bytes[0] ^= 1,
                "length" => value.descriptor.size_bytes += 1,
                "descriptor" => {
                    value.descriptor.release_digest = latent_artifacts::content_digest(b"other")
                }
                "manifest" => {
                    value.manifest.component_digest = latent_artifacts::content_digest(b"other")
                }
                "another-valid-release" => *value = artifact("other"),
                _ => unreachable!(),
            }
        }
        let result = run(store.apply(deployment("green", "alice", &digest)));
        assert_eq!(result.unwrap_err().code, Code::CorruptArtifact, "{damage}");
        assert_eq!(releases.fetches.load(Ordering::Relaxed), 2, "{damage}");
        assert_eq!(snapshot(&store), original, "{damage}");
    }
}

#[test]
fn checked_metadata_still_requires_deployment_compatibility_validation() {
    let root = TempRoot::new();
    let repository = Arc::new(MetadataOnly::default());
    let digest = repository.releases.add("one");
    let store = run(Store::open(
        root.0.clone(),
        repository.clone(),
        Limits::default(),
    ))
    .unwrap();
    let mut incompatible = deployment("blue", "alice", &digest);
    incompatible.resources.memory_bytes += 1;
    assert_code(run(store.apply(incompatible)), Code::InvalidArgument);
    assert_eq!(store.generation(), RouteGeneration(0));
    assert_eq!(repository.full_fetches.load(Ordering::Relaxed), 0);
}
