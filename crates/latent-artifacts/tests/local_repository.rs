use std::fs;
use std::sync::Arc;

use latent_artifacts::{
    ArtifactDescriptor, ArtifactQuery, ArtifactRepository, CapsuleArtifact,
    DirectoryArtifactRepository, DirectoryArtifactRepositoryConfig,
};
use latent_core::{ArtifactReference, PlatformErrorCode, ReleaseDigest};
use latent_manifest::{JsonManifestCodec, ManifestCodec};
use sha2::{Digest, Sha256};

fn digest(bytes: &[u8]) -> ReleaseDigest {
    let hash = Sha256::digest(bytes);
    ReleaseDigest(format!(
        "sha256:{}",
        hash.iter()
            .map(|byte| format!("{byte:02x}"))
            .collect::<String>()
    ))
}

fn artifact(name: &str, bytes: &[u8]) -> CapsuleArtifact {
    let release_digest = digest(bytes);
    let mut document: serde_json::Value = serde_json::from_slice(include_bytes!(
        "../../../examples/echo-contract/capsule.json"
    ))
    .expect("fixture JSON must decode");
    document["metadata"]["name"] = serde_json::Value::String(format!("tests/{name}"));
    document["component"]["digest"] =
        serde_json::Value::String(release_digest.0.clone());
    let manifest_bytes = serde_json::to_vec(&document).expect("fixture JSON must encode");
    let manifest = JsonManifestCodec::default()
        .decode_capsule(&manifest_bytes)
        .expect("test capsule must validate structurally");

    CapsuleArtifact {
        descriptor: ArtifactDescriptor {
            reference: ArtifactReference(format!("local://tests/{name}")),
            release_digest,
            media_type: "application/vnd.wasm.component.v1+wasm".to_owned(),
            size_bytes: u64::try_from(bytes.len()).expect("test component length must fit u64"),
            publisher: None,
            layers: Vec::new(),
            annotations: Default::default(),
        },
        manifest,
        contracts: Vec::new(),
        component_bytes: bytes.to_vec(),
    }
}

fn repository(root: &std::path::Path) -> DirectoryArtifactRepository {
    DirectoryArtifactRepository::open(root, DirectoryArtifactRepositoryConfig::default())
        .expect("repository must open")
}

#[tokio::test]
async fn publish_duplicate_resolve_fetch_and_restart_round_trip() {
    let temp = tempfile::tempdir().expect("temporary directory must be created");
    let expected = artifact("round-trip", b"component-round-trip");
    let digest = expected.descriptor.release_digest.clone();

    let repo = repository(temp.path());
    let published = repo
        .publish(expected.clone())
        .await
        .expect("first publish must succeed");
    assert_eq!(published, expected.descriptor);
    assert_eq!(
        repo.publish(expected.clone())
            .await
            .expect("identical publish must be idempotent"),
        expected.descriptor
    );

    let resolved = repo
        .resolve(&ArtifactQuery {
            reference: Some(expected.descriptor.reference.clone()),
            release_digest: None,
            media_type: Some(expected.descriptor.media_type.clone()),
        })
        .await
        .expect("resolve must succeed")
        .expect("published descriptor must resolve");
    assert_eq!(resolved, expected.descriptor);
    assert_eq!(
        repo.fetch(&digest).await.expect("fetch must succeed"),
        expected
    );

    drop(repo);
    let reopened = repository(temp.path());
    assert_eq!(
        reopened
            .fetch(&digest)
            .await
            .expect("restart fetch must succeed"),
        expected
    );
}

#[tokio::test]
async fn digest_disagreement_is_corrupt_and_not_visible() {
    let temp = tempfile::tempdir().expect("temporary directory must be created");
    let repo = repository(temp.path());
    let mut invalid = artifact("bad-digest", b"component-one");
    invalid.manifest.component_digest = digest(b"component-two");

    let failure = repo
        .publish(invalid)
        .await
        .expect_err("digest disagreement must fail");
    assert_eq!(failure.code, PlatformErrorCode::CorruptArtifact);
    assert!(repo
        .list(None, 10)
        .await
        .expect("list must succeed")
        .entries
        .is_empty());
}

#[tokio::test]
async fn missing_and_corrupt_entries_are_rejected() {
    let temp = tempfile::tempdir().expect("temporary directory must be created");
    let repo = repository(temp.path());
    let missing = digest(b"missing");
    assert_eq!(
        repo.fetch(&missing)
            .await
            .expect_err("unknown release must fail")
            .code,
        PlatformErrorCode::NotFound
    );

    let expected = artifact("corrupt", b"component-before-corruption");
    let release = expected.descriptor.release_digest.clone();
    repo.publish(expected)
        .await
        .expect("publish before corruption must succeed");
    let release_dir = temp
        .path()
        .join("releases")
        .join(release.0.strip_prefix("sha256:").expect("sha256 digest"));
    fs::write(release_dir.join("component.wasm"), b"corrupted")
        .expect("test must corrupt stored component");

    assert_eq!(
        repo.fetch(&release)
            .await
            .expect_err("corrupt release must fail")
            .code,
        PlatformErrorCode::CorruptArtifact
    );
}

#[tokio::test]
async fn conflicting_metadata_under_existing_digest_is_rejected() {
    let temp = tempfile::tempdir().expect("temporary directory must be created");
    let repo = repository(temp.path());
    let expected = artifact("conflict", b"same-component");
    repo.publish(expected.clone())
        .await
        .expect("first publish must succeed");

    let mut conflicting = expected;
    conflicting.descriptor.reference = ArtifactReference("local://tests/other".to_owned());
    assert_eq!(
        repo.publish(conflicting)
            .await
            .expect_err("conflicting metadata must fail")
            .code,
        PlatformErrorCode::AlreadyExists
    );
}

#[tokio::test]
async fn listing_is_bounded_deterministic_and_paginated_from_memory() {
    let temp = tempfile::tempdir().expect("temporary directory must be created");
    let repo = DirectoryArtifactRepository::open(
        temp.path(),
        DirectoryArtifactRepositoryConfig {
            max_index_entries: 100,
            max_page_size: 2,
        },
    )
    .expect("repository must open");

    for index in 0..5 {
        repo.publish(artifact(
            &format!("page-{index}"),
            format!("component-{index}").as_bytes(),
        ))
        .await
        .expect("publish must succeed");
    }

    let first = repo.list(None, 100).await.expect("first page must list");
    assert_eq!(first.entries.len(), 2);
    assert!(first.next_after.is_some());
    assert!(first.entries[0].release_digest < first.entries[1].release_digest);

    let second = repo
        .list(first.next_after.as_ref(), 100)
        .await
        .expect("second page must list");
    assert_eq!(second.entries.len(), 2);
    assert!(second.next_after.is_some());
    assert!(first.entries[1].release_digest < second.entries[0].release_digest);

    let third = repo
        .list(second.next_after.as_ref(), 100)
        .await
        .expect("third page must list");
    assert_eq!(third.entries.len(), 1);
    assert!(third.next_after.is_none());
}

#[tokio::test]
async fn concurrent_identical_publishers_observe_one_complete_release() {
    let temp = tempfile::tempdir().expect("temporary directory must be created");
    let repo = Arc::new(repository(temp.path()));
    let expected = artifact("concurrent", b"concurrent-component");
    let digest = expected.descriptor.release_digest.clone();
    let mut tasks = Vec::new();

    for _ in 0..32 {
        let repo = Arc::clone(&repo);
        let artifact = expected.clone();
        tasks.push(tokio::spawn(async move { repo.publish(artifact).await }));
    }
    for task in tasks {
        assert_eq!(
            task.await
                .expect("publisher task must complete")
                .expect("identical concurrent publish must succeed"),
            expected.descriptor
        );
    }

    assert_eq!(
        repo.list(None, 10)
            .await
            .expect("list must succeed")
            .entries
            .len(),
        1
    );
    assert_eq!(
        repo.fetch(&digest).await.expect("fetch must succeed"),
        expected
    );
}

#[test]
fn restart_cleans_incomplete_temporary_writes_without_exposing_them() {
    let temp = tempfile::tempdir().expect("temporary directory must be created");
    let repo = repository(temp.path());
    drop(repo);

    let orphan = temp.path().join(".tmp").join("interrupted-publish");
    fs::create_dir_all(&orphan).expect("orphan directory must be created");
    fs::write(orphan.join("component.wasm"), b"partial")
        .expect("partial file must be created");

    let reopened = repository(temp.path());
    assert!(!orphan.exists());
    drop(reopened);
}
