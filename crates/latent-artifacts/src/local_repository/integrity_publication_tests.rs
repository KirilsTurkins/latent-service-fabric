//! Completion records must be verified before adoption, including the first publish.

use std::cell::RefCell;
use std::rc::Rc;

use latent_core::PlatformError;
use latent_manifest::__serde_json as json;

use super::super::integrity::faults::AfterRenameGuard;
use super::*;

#[derive(Clone, Copy)]
enum Damage {
    Metadata,
    MissingCompletion,
    TruncatedCompletion,
}

type OriginalFile = RefCell<Option<(PathBuf, Vec<u8>)>>;

fn assert_corruption(failure: &PlatformError) {
    assert_eq!(failure.code, PlatformErrorCode::CorruptArtifact);
    assert_eq!(failure.message, "invalid catalog completion record");
    assert!(!failure.retryable);
}

fn damage_completed_entry(path: &Path, damage: Damage, original: &OriginalFile) {
    let name = match damage {
        Damage::Metadata => "metadata.json",
        Damage::MissingCompletion | Damage::TruncatedCompletion => "COMPLETE",
    };
    let path = path.join(name);
    let mut bytes = fs::read(&path).expect("newly renamed payload exists");
    *original.borrow_mut() = Some((path.clone(), bytes.clone()));
    match damage {
        Damage::Metadata => {
            let needle = b"initial-a";
            let offset = bytes
                .windows(needle.len())
                .position(|window| window == needle)
                .expect("published reference");
            bytes[offset + needle.len() - 1] = b'b';
            json::from_slice::<json::Value>(&bytes).expect("mutation preserves valid JSON");
            fs::write(path, bytes).expect("inject metadata corruption");
        }
        Damage::MissingCompletion => fs::remove_file(path).expect("inject missing completion"),
        Damage::TruncatedCompletion => {
            fs::write(path, &bytes[..bytes.len() / 2]).expect("inject truncated completion");
        }
    }
}

fn assert_invisible(repo: &DirectoryArtifactRepository, value: &CapsuleArtifact) {
    assert_eq!(
        block_on(repo.fetch(&value.descriptor.release_digest))
            .expect_err("unverified artifact must not become fetchable")
            .code,
        PlatformErrorCode::NotFound
    );
    assert_eq!(
        block_on(repo.fetch_verified_metadata(&value.descriptor.release_digest))
            .expect_err("unverified metadata must not become fetchable")
            .code,
        PlatformErrorCode::NotFound
    );
    assert_eq!(
        block_on(repo.resolve(&ArtifactQuery {
            reference: Some(value.descriptor.reference.clone()),
            release_digest: Some(value.descriptor.release_digest.clone()),
            media_type: None,
        }))
        .expect("resolve remains usable"),
        None
    );
}

fn assert_initial_adoption_rejects(damage: Damage) {
    let temp = TempRoot::new();
    let config = DirectoryArtifactRepositoryConfig {
        max_index_entries: 3,
        max_recovery_directories: 2,
        ..DirectoryArtifactRepositoryConfig::default()
    };
    let repo = DirectoryArtifactRepository::open(temp.path(), config).expect("open");
    let prior = artifact("prior", b"prior");
    let candidate = artifact("initial-a", b"initial");
    let unrelated = artifact("unrelated", b"unrelated");
    block_on(repo.publish(prior.clone())).expect("prior publication");
    let original = Rc::new(RefCell::new(None));
    let captured = Rc::clone(&original);
    let guard = AfterRenameGuard::new(move |path| {
        damage_completed_entry(path, damage, &captured);
    });
    let failure = block_on(repo.publish(candidate.clone()))
        .expect_err("initial adoption verifies the persisted entry");
    assert_corruption(&failure);
    drop(guard);
    let (damaged_path, original_bytes) = original
        .borrow_mut()
        .take()
        .expect("post-rename corruption hook fired");
    assert!(release_dir(temp.path(), &candidate.descriptor.release_digest).is_dir());
    for _ in 0..2 {
        assert_invisible(&repo, &candidate);
        let failure = block_on(repo.publish(candidate.clone()))
            .expect_err("corrupt retry cannot adopt or clear the pending gate");
        assert_corruption(&failure);
        let gated = block_on(repo.publish(unrelated.clone()))
            .expect_err("failed initial verification keeps the mutation gate closed");
        assert_eq!(gated.code, PlatformErrorCode::Unavailable);
        assert_eq!(
            gated.message,
            "catalog needs publication recovery: retry the pending release or reopen the root"
        );
        assert!(!release_dir(temp.path(), &unrelated.descriptor.release_digest).exists());
    }
    assert_eq!(
        block_on(repo.fetch(&prior.descriptor.release_digest)).expect("prior stays readable"),
        prior
    );
    assert_eq!(
        block_on(repo.list(None, 10))
            .expect("prior remains indexed")
            .entries,
        vec![prior.descriptor.clone()]
    );
    drop(repo);
    let failure = DirectoryArtifactRepository::open(temp.path(), config)
        .expect_err("restart must not silently skip a damaged final directory");
    assert_corruption(&failure);
    // Restore captured original bytes offline; recovery must not invent a new record.
    fs::write(damaged_path, original_bytes).expect("restore the exact original file offline");
    let reopened =
        DirectoryArtifactRepository::open(temp.path(), config).expect("verified recovery");
    assert_eq!(
        block_on(reopened.fetch(&candidate.descriptor.release_digest)).expect("recovered artifact"),
        candidate
    );
    block_on(reopened.publish(candidate)).expect("identical retry at directory capacity");
    assert_eq!(
        block_on(reopened.publish(unrelated))
            .expect_err("recovered final directory retains its capacity charge")
            .code,
        PlatformErrorCode::ResourceExhausted
    );
}

#[test]
fn initial_adoption_checks_persisted_metadata_and_completion_before_acknowledging() {
    for damage in [
        Damage::Metadata,
        Damage::MissingCompletion,
        Damage::TruncatedCompletion,
    ] {
        assert_initial_adoption_rejects(damage);
    }
}

#[test]
fn restart_discards_staging_at_every_completion_record_boundary_without_adoption() {
    let source = TempRoot::new();
    let candidate = artifact("staged", b"staged");
    let source_repo = repository(source.path());
    block_on(source_repo.publish(candidate.clone())).expect("production-format source");
    drop(source_repo);
    let source_dir = release_dir(source.path(), &candidate.descriptor.release_digest);
    let complete = fs::read(source_dir.join("COMPLETE")).expect("production completion record");
    for record_length in [
        None,
        Some(0),
        Some(complete.len() / 2),
        Some(complete.len()),
    ] {
        let temp = TempRoot::new();
        let config = DirectoryArtifactRepositoryConfig {
            max_index_entries: 3,
            max_recovery_directories: 2,
            ..DirectoryArtifactRepositoryConfig::default()
        };
        let prior = artifact("prior", b"prior");
        let repo = DirectoryArtifactRepository::open(temp.path(), config).expect("open");
        block_on(repo.publish(prior.clone())).expect("prior publication");
        drop(repo);
        // Model a process interruption before rename, even with a fully written record.
        let stage = temp.path().join(".tmp/interrupted-integrity");
        fs::create_dir(&stage).expect("abandoned staging directory");
        for name in ["metadata.json", "manifest.json", "component.wasm"] {
            fs::copy(source_dir.join(name), stage.join(name)).expect("staged payload");
        }
        if let Some(length) = record_length {
            fs::write(stage.join("COMPLETE"), &complete[..length]).expect("staged record prefix");
        }
        let reopened = DirectoryArtifactRepository::open(temp.path(), config).expect("restart");
        assert!(!stage.exists(), "abandoned stage must be cleaned");
        assert_invisible(&reopened, &candidate);
        assert_eq!(
            block_on(reopened.list(None, 10))
                .expect("prior index")
                .entries,
            vec![prior.descriptor.clone()]
        );
        assert_eq!(
            block_on(reopened.fetch(&prior.descriptor.release_digest)).expect("prior artifact"),
            prior
        );
        block_on(reopened.publish(candidate.clone())).expect("staging did not consume capacity");
        block_on(reopened.publish(candidate.clone())).expect("duplicate remains idempotent");
        drop(reopened);
        let recovered =
            DirectoryArtifactRepository::open(temp.path(), config).expect("final reopen");
        assert_eq!(
            block_on(recovered.fetch(&candidate.descriptor.release_digest))
                .expect("final artifact"),
            candidate
        );
    }
}
