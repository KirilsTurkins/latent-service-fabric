//! Publication must preserve the directory budget used by the next startup.

use super::super::*;

fn config(entries: usize, directories: usize) -> DirectoryArtifactRepositoryConfig {
    DirectoryArtifactRepositoryConfig {
        max_index_entries: entries,
        max_recovery_directories: directories,
        ..DirectoryArtifactRepositoryConfig::default()
    }
}

fn assert_catalog(repo: &DirectoryArtifactRepository, expected: &[CapsuleArtifact]) {
    let mut descriptors = Vec::new();
    for release in expected {
        let descriptor = &release.descriptor;
        let query = ArtifactQuery {
            reference: Some(descriptor.reference.clone()),
            release_digest: Some(descriptor.release_digest.clone()),
            media_type: None,
        };
        assert_eq!(
            block_on(repo.resolve(&query)).expect("resolve complete release"),
            Some(descriptor.clone())
        );
        assert_eq!(
            block_on(repo.fetch(&descriptor.release_digest)).expect("fetch complete release"),
            *release
        );
        descriptors.push(descriptor.clone());
    }
    descriptors.sort_by(|left, right| left.release_digest.cmp(&right.release_digest));
    let page = block_on(repo.list(None, 16)).expect("list complete catalog");
    assert_eq!(page.entries, descriptors);
    assert_eq!(page.next_after, None);
}

fn assert_budget_rejected(repo: &DirectoryArtifactRepository, release: &CapsuleArtifact) {
    let failure = block_on(repo.publish(release.clone())).expect_err("directory budget");
    assert_eq!(failure.code, PlatformErrorCode::ResourceExhausted);
    assert!(
        failure.message.contains("recovery directory"),
        "{failure:?}"
    );
    let digest = &release.descriptor.release_digest;
    assert!(!release_dir(repo.root(), digest).exists());
    assert_eq!(
        block_on(repo.resolve(&ArtifactQuery {
            reference: Some(release.descriptor.reference.clone()),
            release_digest: None,
            media_type: None,
        }))
        .expect("rejected reference remains absent"),
        None
    );
    assert_eq!(
        block_on(repo.fetch(digest))
            .expect_err("not persisted")
            .code,
        PlatformErrorCode::NotFound
    );
    assert_eq!(
        fs::read_dir(repo.root().join(".tmp"))
            .expect("staging directory")
            .count(),
        0
    );
}

#[test]
fn clean_root_publication_respects_a_smaller_recovery_budget_and_reopens() {
    let temp = TempRoot::new();
    let limits = config(3, 2);
    let repo = DirectoryArtifactRepository::open(temp.path(), limits).expect("open");
    let expected = [artifact("one", b"one"), artifact("two", b"two")];
    for release in &expected {
        block_on(repo.publish(release.clone())).expect("within recovery capacity");
    }
    let excess = artifact("three", b"three");
    assert_budget_rejected(&repo, &excess);
    block_on(repo.publish(expected[0].clone())).expect("duplicate at full capacity");
    assert_catalog(&repo, &expected);
    drop(repo);

    let reopened = DirectoryArtifactRepository::open(temp.path(), limits).expect("same limits");
    assert_catalog(&reopened, &expected);
    assert_budget_rejected(&reopened, &excess);
    drop(reopened);
    assert!(DirectoryArtifactRepository::open(temp.path(), limits).is_ok());
}

#[test]
fn retained_incomplete_directory_reduces_publication_capacity_across_reopen() {
    let temp = TempRoot::new();
    let debris = temp.path().join("releases/incomplete");
    fs::create_dir_all(&debris).expect("incomplete final directory");
    let limits = config(2, 2);
    let repo = DirectoryArtifactRepository::open(temp.path(), limits).expect("open with debris");
    assert_catalog(&repo, &[]);
    let first = artifact("first", b"first");
    let second = artifact("second", b"second");
    block_on(repo.publish(first.clone())).expect("one directory remains available");
    assert_budget_rejected(&repo, &second);
    block_on(repo.publish(first.clone())).expect("duplicate does not need a new directory");
    assert_catalog(&repo, std::slice::from_ref(&first));
    assert!(debris.is_dir());
    assert!(!debris.join("COMPLETE").exists());
    drop(repo);

    let reopened = DirectoryArtifactRepository::open(temp.path(), limits).expect("same limits");
    assert_catalog(&reopened, std::slice::from_ref(&first));
    assert_budget_rejected(&reopened, &second);
    assert_eq!(
        fs::read_dir(temp.path().join("releases"))
            .expect("retained directories")
            .count(),
        2
    );
    drop(reopened);
    assert!(DirectoryArtifactRepository::open(temp.path(), limits).is_ok());
}

#[test]
fn incomplete_directories_can_exhaust_recovery_capacity_without_visible_releases() {
    let temp = TempRoot::new();
    for name in ["incomplete-one", "incomplete-two"] {
        fs::create_dir_all(temp.path().join("releases").join(name)).expect("debris");
    }
    let limits = config(3, 2);
    let repo = DirectoryArtifactRepository::open(temp.path(), limits).expect("open at scan limit");
    assert_budget_rejected(&repo, &artifact("blocked", b"blocked"));
    assert_catalog(&repo, &[]);
    drop(repo);
    let reopened = DirectoryArtifactRepository::open(temp.path(), limits).expect("empty reopen");
    assert_catalog(&reopened, &[]);
}

#[test]
fn recovery_capacity_rejection_precedes_staging_filesystem_access() {
    let temp = TempRoot::new();
    let limits = config(3, 1);
    let repo = DirectoryArtifactRepository::open(temp.path(), limits).expect("open");
    let first = artifact("first", b"first");
    block_on(repo.publish(first.clone())).expect("fill directory capacity");
    // Fault injection: staging would fail with Internal if publication reached it.
    let staging = temp.path().join(".tmp");
    fs::remove_dir(&staging).expect("remove empty staging directory");
    fs::write(&staging, b"not a directory").expect("block staging access");
    let failure = block_on(repo.publish(artifact("second", b"second")))
        .expect_err("budget checked before staging");
    assert_eq!(failure.code, PlatformErrorCode::ResourceExhausted);
    assert!(failure.message.contains("recovery directory"));
    fs::remove_file(&staging).expect("remove injected fault");
    fs::create_dir(&staging).expect("restore staging");
    drop(repo);
    let reopened = DirectoryArtifactRepository::open(temp.path(), limits).expect("same limits");
    assert_catalog(&reopened, &[first]);
}

#[test]
fn pending_release_keeps_its_directory_charge_through_retry_or_reopen() {
    for recover_by_retry in [false, true] {
        let temp = TempRoot::new();
        fs::create_dir_all(temp.path().join("releases/incomplete")).expect("debris");
        let limits = config(3, 2);
        let mut repo = DirectoryArtifactRepository::open(temp.path(), limits).expect("open");
        let first = artifact("pending", b"pending");
        let second = artifact("unrelated", b"unrelated");
        repo.inject_parent_sync_failure_once();
        assert_eq!(
            block_on(repo.publish(first.clone()))
                .expect_err("sync failure")
                .code,
            PlatformErrorCode::Internal
        );
        assert_catalog(&repo, &[]);
        assert_eq!(
            block_on(repo.publish(second.clone()))
                .expect_err("recovery gate")
                .code,
            PlatformErrorCode::Unavailable
        );
        if recover_by_retry {
            repo.inject_parent_sync_failure_once();
            assert_eq!(
                block_on(repo.publish(first.clone()))
                    .expect_err("repeat failure")
                    .code,
                PlatformErrorCode::Internal
            );
            block_on(repo.publish(first.clone())).expect("retry uses charged directory");
        } else {
            drop(repo);
            repo = DirectoryArtifactRepository::open(temp.path(), limits).expect("recover pending");
        }
        block_on(repo.publish(first.clone())).expect("duplicate never double charges");
        assert_budget_rejected(&repo, &second);
        assert_catalog(&repo, std::slice::from_ref(&first));
        drop(repo);
        let reopened = DirectoryArtifactRepository::open(temp.path(), limits).expect("same limits");
        assert_catalog(&reopened, &[first]);
    }
}

#[test]
fn failures_before_rename_do_not_consume_recovery_capacity() {
    for directory in [".tmp", "releases"] {
        let temp = TempRoot::new();
        let limits = config(3, 1);
        let repo = DirectoryArtifactRepository::open(temp.path(), limits).expect("open");
        // Inject either a staging-creation failure or a final-rename failure.
        let blocked = temp.path().join(directory);
        fs::remove_dir(&blocked).expect("empty directory");
        fs::write(&blocked, b"not a directory").expect("inject filesystem failure");
        assert_eq!(
            block_on(repo.publish(artifact("failed", b"failed")))
                .expect_err("pre-rename filesystem failure")
                .code,
            PlatformErrorCode::Internal
        );
        fs::remove_file(&blocked).expect("remove fault");
        fs::create_dir(&blocked).expect("restore directory");
        let accepted = artifact("accepted", b"accepted");
        block_on(repo.publish(accepted.clone())).expect("failed attempt left capacity available");
        assert_budget_rejected(&repo, &artifact("excess", b"excess"));
        drop(repo);
        let reopened = DirectoryArtifactRepository::open(temp.path(), limits).expect("same limits");
        assert_catalog(&reopened, &[accepted]);
    }
}

#[test]
fn concurrent_publishers_cannot_overcommit_the_last_recovery_directory() {
    let temp = TempRoot::new();
    fs::create_dir_all(temp.path().join("releases/incomplete")).expect("debris");
    let limits = config(16, 2);
    let repo = Arc::new(DirectoryArtifactRepository::open(temp.path(), limits).expect("open"));
    let barrier = Arc::new(Barrier::new(8));
    let mut writers = Vec::new();
    for index in 0..8 {
        let value = artifact(
            &format!("writer-{index}"),
            format!("bytes-{index}").as_bytes(),
        );
        let writer_repo = Arc::clone(&repo);
        let start = Arc::clone(&barrier);
        writers.push(thread::spawn(move || {
            start.wait();
            let result = block_on(writer_repo.publish(value.clone()));
            (value, result)
        }));
    }
    let mut accepted = Vec::new();
    for writer in writers {
        let (value, result) = writer.join().expect("writer must finish");
        match result {
            Ok(descriptor) => {
                assert_eq!(descriptor, value.descriptor);
                accepted.push(value);
            }
            Err(failure) => {
                assert_eq!(failure.code, PlatformErrorCode::ResourceExhausted);
                assert!(failure.message.contains("recovery directory"));
                assert!(!release_dir(temp.path(), &value.descriptor.release_digest).exists());
            }
        }
    }
    assert_eq!(accepted.len(), 1);
    assert_catalog(&repo, &accepted);
    assert_eq!(
        fs::read_dir(temp.path().join("releases"))
            .expect("directories")
            .count(),
        2
    );
    drop(repo);
    let reopened = DirectoryArtifactRepository::open(temp.path(), limits).expect("same limits");
    assert_catalog(&reopened, &accepted);
}

#[test]
fn offline_debris_removal_reclaims_directory_capacity_on_reopen() {
    let temp = TempRoot::new();
    let debris = temp.path().join("releases/incomplete");
    fs::create_dir_all(&debris).expect("debris");
    let limits = config(2, 2);
    let first = artifact("first", b"first");
    let second = artifact("second", b"second");
    let repo = DirectoryArtifactRepository::open(temp.path(), limits).expect("open");
    block_on(repo.publish(first.clone())).expect("first release");
    assert_budget_rejected(&repo, &second);
    drop(repo);
    fs::remove_dir(&debris).expect("offline cleanup of known incomplete directory");
    let reopened = DirectoryArtifactRepository::open(temp.path(), limits).expect("recount root");
    block_on(reopened.publish(second.clone())).expect("reclaimed directory slot");
    drop(reopened);
    let reopened = DirectoryArtifactRepository::open(temp.path(), limits).expect("same limits");
    assert_catalog(&reopened, &[first, second]);
}
