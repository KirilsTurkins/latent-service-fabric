use super::*;

#[test]
fn legacy_and_mixed_catalogs_are_rejected_without_rewriting_committed_bytes() {
    for mixed in [false, true] {
        let temp = TempRoot::new();
        let repo = repository(temp.path());
        let legacy = artifact("legacy", b"old format component");
        block_on(repo.publish(legacy.clone())).unwrap();
        let legacy_path = release_dir(repo.root(), &legacy.descriptor.release_digest);
        let modern_path = if mixed {
            let modern = artifact("modern", b"new format component");
            block_on(repo.publish(modern.clone())).unwrap();
            Some(release_dir(repo.root(), &modern.descriptor.release_digest))
        } else {
            None
        };
        fs::write(legacy_path.join("COMPLETE"), b"complete\n").unwrap();
        let modern_files = modern_path.as_ref().map(|path| entry_files(path));
        assert_fetch_retry_and_reopen_reject(repo, &legacy, &legacy_path, LEGACY_RECORD);
        assert_eq!(
            fs::read(legacy_path.join("COMPLETE")).unwrap(),
            b"complete\n"
        );
        if let Some(path) = modern_path {
            assert_eq!(Some(entry_files(&path)), modern_files);
        }
    }
}

fn assert_pending_gate(
    repo: &DirectoryArtifactRepository,
    prior: &CapsuleArtifact,
    pending: &CapsuleArtifact,
    unrelated: &CapsuleArtifact,
) {
    for _ in 0..2 {
        assert_corrupt(block_on(repo.publish(pending.clone())), INVALID_RECORD);
        let failure = block_on(repo.publish(unrelated.clone())).unwrap_err();
        assert_eq!(failure.code, PlatformErrorCode::Unavailable);
        assert_eq!(
            failure.message,
            "catalog needs publication recovery: retry the pending release or reopen the root"
        );
    }
    assert_eq!(
        block_on(repo.fetch(&prior.descriptor.release_digest)).unwrap(),
        *prior
    );
    assert_eq!(
        block_on(repo.list(None, 10)).unwrap().entries,
        vec![prior.descriptor.clone()]
    );
    assert_eq!(
        block_on(repo.fetch(&pending.descriptor.release_digest))
            .unwrap_err()
            .code,
        PlatformErrorCode::NotFound
    );
    assert!(!release_dir(repo.root(), &unrelated.descriptor.release_digest).exists());
}

#[test]
fn corruption_of_a_pending_release_retains_the_gate_until_exact_bytes_are_restored() {
    for reopen in [false, true] {
        let temp = TempRoot::new();
        let mut repo = repository(temp.path());
        let prior = artifact("prior", b"prior component");
        let pending = artifact("pending", b"pending component");
        let unrelated = artifact("unrelated", b"unrelated component");
        block_on(repo.publish(prior.clone())).unwrap();
        repo.inject_parent_sync_failure_once();
        assert_eq!(
            block_on(repo.publish(pending.clone())).unwrap_err().code,
            PlatformErrorCode::Internal
        );
        let path = release_dir(repo.root(), &pending.descriptor.release_digest);
        let original = fs::read(path.join("COMPLETE")).unwrap();
        let corrupted = replace_once(&original, "\"format_version\":1", "\"format_version\":2");
        fs::write(path.join("COMPLETE"), corrupted).unwrap();
        let persisted = entry_files(&path);
        assert_pending_gate(&repo, &prior, &pending, &unrelated);
        assert_eq!(entry_files(&path), persisted);

        if reopen {
            drop(repo);
            assert_corrupt(
                DirectoryArtifactRepository::open(
                    temp.path(),
                    DirectoryArtifactRepositoryConfig::default(),
                ),
                INVALID_RECORD,
            );
            assert_eq!(entry_files(&path), persisted);
            // Restore the exact bytes captured from this fixture's successful
            // write, never manufacture a checksum over corrupted metadata.
            fs::write(path.join("COMPLETE"), &original).unwrap();
            repo = repository(temp.path());
        } else {
            fs::write(path.join("COMPLETE"), &original).unwrap();
        }
        block_on(repo.publish(pending.clone())).expect("identical retry reconciles integrity");
        block_on(repo.publish(pending.clone())).expect("reconciled retry remains idempotent");
        block_on(repo.publish(unrelated.clone())).expect("successful recovery releases the gate");
        assert_eq!(fs::read(path.join("COMPLETE")).unwrap(), original);
        drop(repo);
        let restarted = repository(temp.path());
        for expected in [&prior, &pending, &unrelated] {
            assert_eq!(
                block_on(restarted.fetch(&expected.descriptor.release_digest)).unwrap(),
                *expected
            );
        }
    }
}
