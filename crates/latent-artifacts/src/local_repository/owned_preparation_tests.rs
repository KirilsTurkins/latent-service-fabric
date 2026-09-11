use std::mem::size_of;
use std::sync::mpsc;

use latent_core::{BoxFuture, PlatformError};

use super::*;
use crate::{ArtifactPage, ArtifactPreparationReadLimits, OwnedArtifactPreparationSource};

#[path = "owned_preparation_tests/bounds.rs"]
mod bounds;

fn limits(
    source: &OwnedArtifactPreparationSource,
    release: &ReleaseDigest,
) -> ArtifactPreparationReadLimits {
    let bounds = source.read_bounds(release).unwrap();
    ArtifactPreparationReadLimits {
        maximum_component_bytes: usize::try_from(bounds.component_bytes).unwrap(),
        maximum_metadata_document_bytes: bounds.maximum_metadata_document_bytes,
        maximum_manifest_document_bytes: bounds.maximum_manifest_document_bytes,
    }
}

fn source(owner: &Arc<DirectoryArtifactRepository>) -> OwnedArtifactPreparationSource {
    let erased: Arc<dyn ArtifactRepository> = owner.clone();
    erased.owned_preparation_source().unwrap()
}

#[test]
fn dynamic_arc_source_matches_borrowed_reads_without_extra_verification() {
    let temp = TempRoot::new();
    let value = artifact("owned", b"abc");
    let release = value.descriptor.release_digest.clone();
    let owner = Arc::new(repository(temp.path()));
    block_on(owner.publish(value.clone())).unwrap();
    let owned = source(&owner);
    let before = owner.verification_snapshot();
    let old_future = owner.fetch(&release);
    drop(old_future);
    for _ in 0..3 {
        assert_eq!(
            owned.identity(&release).unwrap(),
            owner
                .preparation_source()
                .unwrap()
                .identity(&release)
                .unwrap()
        );
        assert_eq!(owned.read_bounds(&release).unwrap().component_bytes, 3);
    }
    assert_eq!(owner.verification_snapshot(), before);
    assert_eq!(block_on(owner.fetch(&release)).unwrap(), value);
    let middle = owner.verification_snapshot();
    assert_eq!(
        owned
            .fetch_blocking(&release, limits(&owned, &release))
            .unwrap(),
        value
    );
    let after = owner.verification_snapshot();
    for actual in [middle, after] {
        let attempts = actual.full_fetch_attempts - before.full_fetch_attempts;
        assert_eq!(
            actual.component_verification_attempts - before.component_verification_attempts,
            attempts
        );
        assert_eq!(
            actual.component_bytes_hashed - before.component_bytes_hashed,
            attempts * 3
        );
        assert_eq!(
            actual.metadata_fetch_attempts,
            before.metadata_fetch_attempts
        );
        assert_eq!(
            actual.metadata_fingerprint_attempts,
            before.metadata_fingerprint_attempts
        );
    }
    assert_eq!(after.full_fetch_attempts - before.full_fetch_attempts, 2);
}

#[test]
fn worker_owned_source_keeps_root_locked_until_actual_job_completion() {
    let temp = TempRoot::new();
    let value = artifact("worker", b"abc");
    let release = value.descriptor.release_digest.clone();
    let owner = Arc::new(repository(temp.path()));
    block_on(owner.publish(value.clone())).unwrap();
    let owned = source(&owner);
    let token = owned.identity(&release).unwrap().unwrap();
    let read_limits = limits(&owned, &release);
    let (ready_tx, ready_rx) = mpsc::channel();
    let (finish_tx, finish_rx) = mpsc::channel();
    let worker_release = release.clone();
    let worker = thread::spawn(move || {
        let fetched = owned.fetch_blocking(&worker_release, read_limits);
        ready_tx.send(()).unwrap();
        // Models a running compiler retaining its source after the last caller
        // has gone away. The test always releases this finite wait before join.
        let finished = finish_rx.recv_timeout(Duration::from_secs(5));
        drop(owned);
        (fetched, finished)
    });
    drop(owner);
    let ready = ready_rx.recv_timeout(Duration::from_secs(5));
    let competing = DirectoryArtifactRepository::open(
        temp.path(),
        DirectoryArtifactRepositoryConfig::default(),
    );
    let sent = finish_tx.send(());
    let (fetched, finished) = worker.join().unwrap();
    ready.unwrap();
    sent.unwrap();
    finished.unwrap();
    assert_eq!(competing.unwrap_err().code, PlatformErrorCode::Unavailable);
    assert_eq!(fetched.unwrap(), value);
    let reopened = Arc::new(repository(temp.path()));
    assert_ne!(
        source(&reopened).identity(&release).unwrap().unwrap(),
        token
    );
}

#[test]
fn cloned_sources_retain_one_owner_without_allocating_or_retaining_new_index_entries() {
    let temp = TempRoot::new();
    let owner = Arc::new(repository(temp.path()));
    let baseline = owner.index.read().unwrap().accounted_bytes;
    let weak = Arc::downgrade(&owner);
    let owned = source(&owner);
    let cloned = owned.clone();
    assert_eq!(
        size_of::<OwnedArtifactPreparationSource>(),
        size_of::<Arc<DirectoryArtifactRepository>>()
    );
    assert_eq!(Arc::strong_count(&owner), 3);
    assert_eq!(owner.index.read().unwrap().accounted_bytes, baseline);
    drop(owner);
    drop(owned);
    assert_eq!(weak.strong_count(), 1);
    drop(cloned);
    assert!(weak.upgrade().is_none());
    drop(repository(temp.path()));
}

struct Delegating {
    issuing: Arc<DirectoryArtifactRepository>,
    other: CapsuleArtifact,
    enabled: bool,
}

impl ArtifactRepository for Delegating {
    fn owned_preparation_source(self: Arc<Self>) -> Option<OwnedArtifactPreparationSource> {
        self.enabled.then(|| {
            Arc::clone(&self.issuing)
                .owned_preparation_source()
                .unwrap()
        })
    }
    fn fetch<'a>(
        &'a self,
        _: &'a ReleaseDigest,
    ) -> BoxFuture<'a, Result<CapsuleArtifact, PlatformError>> {
        Box::pin(async { Ok(self.other.clone()) })
    }
    fn resolve<'a>(
        &'a self,
        query: &'a ArtifactQuery,
    ) -> BoxFuture<'a, Result<Option<ArtifactDescriptor>, PlatformError>> {
        self.issuing.resolve(query)
    }
    fn publish(
        &self,
        value: CapsuleArtifact,
    ) -> BoxFuture<'_, Result<ArtifactDescriptor, PlatformError>> {
        self.issuing.publish(value)
    }
    fn list<'a>(
        &'a self,
        after: Option<&'a ReleaseDigest>,
        limit: usize,
    ) -> BoxFuture<'a, Result<ArtifactPage, PlatformError>> {
        self.issuing.list(after, limit)
    }
}

#[test]
fn delegated_owned_authority_never_mixes_other_fetch_with_either_stamp_state() {
    for eligible in [false, true] {
        let temp = TempRoot::new();
        let original = artifact("authoritative", b"abc");
        let other = artifact("foreign-descriptor", b"abc");
        let release = original.descriptor.release_digest.clone();
        let mut owner = repository(temp.path());
        if !eligible {
            owner.stamp_byte_limit = 1;
        }
        block_on(owner.publish(original.clone())).unwrap();
        let wrapper: Arc<dyn ArtifactRepository> = Arc::new(Delegating {
            issuing: Arc::new(owner),
            other: other.clone(),
            enabled: true,
        });
        assert_eq!(block_on(wrapper.fetch(&release)).unwrap(), other);
        let selected = Arc::clone(&wrapper).owned_preparation_source().unwrap();
        drop(wrapper);
        assert_eq!(selected.identity(&release).unwrap().is_some(), eligible);
        assert_eq!(
            selected
                .fetch_blocking(&release, limits(&selected, &release))
                .unwrap(),
            original
        );
    }
}

#[test]
fn unselected_owned_source_preserves_the_generic_repository_fetch() {
    let temp = TempRoot::new();
    let other = artifact("generic", b"abc");
    let release = other.descriptor.release_digest.clone();
    let wrapper: Arc<dyn ArtifactRepository> = Arc::new(Delegating {
        issuing: Arc::new(repository(temp.path())),
        other: other.clone(),
        enabled: false,
    });
    assert!(Arc::clone(&wrapper).owned_preparation_source().is_none());
    assert_eq!(block_on(wrapper.fetch(&release)).unwrap(), other);
}

#[test]
fn pending_and_noncanonical_keys_never_supply_owned_read_bounds() {
    let temp = TempRoot::new();
    let value = artifact("pending-owned", b"abc");
    let release = value.descriptor.release_digest.clone();
    let owner = Arc::new(repository(temp.path()));
    let owned = source(&owner);
    owner.inject_parent_sync_failure_once();
    assert_eq!(
        block_on(owner.publish(value.clone())).unwrap_err().code,
        PlatformErrorCode::Internal
    );
    let before = owner.verification_snapshot();
    assert_eq!(
        owned.identity(&release).unwrap_err().code,
        PlatformErrorCode::NotFound
    );
    assert_eq!(
        owned.read_bounds(&release).unwrap_err().code,
        PlatformErrorCode::NotFound
    );
    assert_eq!(owner.verification_snapshot(), before);
    block_on(owner.publish(value)).unwrap();
    assert_eq!(owned.read_bounds(&release).unwrap().component_bytes, 3);
    let upper = ReleaseDigest(release.0.to_ascii_uppercase());
    assert_eq!(
        owned.read_bounds(&upper).unwrap_err().code,
        PlatformErrorCode::NotFound
    );
    let ceiling = limits(&owned, &release);
    assert_eq!(
        owned.fetch_blocking(&upper, ceiling).unwrap_err().code,
        PlatformErrorCode::NotFound
    );
}
