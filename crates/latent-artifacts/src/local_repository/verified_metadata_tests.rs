use super::*;
use crate::VerifiedArtifactMetadata;

#[test]
fn full_fetch_streamed_metadata_and_checked_constructor_agree_after_restart() {
    let temp = TempRoot::new();
    let expected = artifact("streamed", &vec![b'a'; 65_537]);
    let digest = expected.descriptor.release_digest.clone();
    let checked = VerifiedArtifactMetadata::from_artifact(expected.clone()).unwrap();
    let repo = repository(temp.path());
    block_on(repo.publish(expected.clone())).unwrap();
    assert_eq!(
        block_on(repo.fetch_verified_metadata(&digest)).unwrap(),
        checked
    );
    assert_eq!(block_on(repo.fetch(&digest)).unwrap(), expected);
    drop(repo);
    let repo = repository(temp.path());
    let metadata = block_on(repo.fetch_verified_metadata(&digest)).unwrap();
    assert_eq!(metadata, checked);
    assert_eq!(metadata.descriptor(), &expected.descriptor);
    assert_eq!(metadata.manifest(), &expected.manifest);
    assert_eq!(metadata.contracts(), &expected.contracts);
    assert_eq!(metadata.verified_digest(), &digest);
}

#[test]
fn streamed_metadata_detects_truncation_growth_and_equal_length_corruption() {
    for changed in [b"ab".as_slice(), b"abcd", b"abd"] {
        let temp = TempRoot::new();
        let expected = artifact("changed-stream", b"abc");
        let digest = expected.descriptor.release_digest.clone();
        let repo = repository(temp.path());
        block_on(repo.publish(expected.clone())).unwrap();
        fs::write(
            release_dir(temp.path(), &digest).join("component.wasm"),
            changed,
        )
        .unwrap();
        super::integrity::assert_fetch_retry_and_reopen_reject(
            repo,
            &expected,
            &release_dir(temp.path(), &digest),
            "manifest, release, and component content digests must agree",
        );
    }
}

#[test]
fn streamed_metadata_rejects_malformed_metadata_even_with_matching_completion_hash() {
    let temp = TempRoot::new();
    let expected = artifact("invalid-metadata", b"abc");
    let digest = expected.descriptor.release_digest.clone();
    let repo = repository(temp.path());
    block_on(repo.publish(expected.clone())).unwrap();
    let entry = release_dir(temp.path(), &digest);
    fs::write(entry.join("metadata.json"), b"{}").unwrap();
    let completion = super::super::integrity::CompletionRecord::from_payloads(
        &expected.descriptor,
        b"{}",
        &fs::read(entry.join("manifest.json")).unwrap(),
    );
    fs::write(entry.join("COMPLETE"), completion.encode().unwrap()).unwrap();
    super::integrity::assert_fetch_retry_and_reopen_reject(
        repo,
        &expected,
        &entry,
        "invalid catalog metadata",
    );
}

#[test]
fn checked_constructor_rejects_wrong_bytes_and_size_and_preserves_canonical_actual_digest() {
    let expected = artifact("checked", b"abc");
    let mut wrong = expected.clone();
    wrong.component_bytes[0] ^= 1;
    assert_eq!(
        VerifiedArtifactMetadata::from_artifact(wrong)
            .unwrap_err()
            .code,
        PlatformErrorCode::CorruptArtifact
    );
    let mut wrong = expected.clone();
    wrong.descriptor.size_bytes += 1;
    assert_eq!(
        VerifiedArtifactMetadata::from_artifact(wrong)
            .unwrap_err()
            .message,
        "artifact descriptor size does not match component bytes"
    );
    let mut case_variant = expected.clone();
    case_variant
        .descriptor
        .release_digest
        .0
        .make_ascii_uppercase();
    case_variant
        .manifest
        .component_digest
        .0
        .make_ascii_uppercase();
    let metadata = VerifiedArtifactMetadata::from_artifact(case_variant).unwrap();
    assert_eq!(
        metadata.verified_digest(),
        &expected.descriptor.release_digest
    );
    metadata
        .verify_requested(&expected.descriptor.release_digest)
        .unwrap();
    let mut uppercase = expected.descriptor.release_digest;
    uppercase.0.make_ascii_uppercase();
    assert_eq!(
        metadata.verify_requested(&uppercase).unwrap_err().message,
        "release-digest-mismatch"
    );
}
