use super::*;

fn prepare() -> (TempRoot, Arc<DirectoryArtifactRepository>, CapsuleArtifact) {
    let temp = TempRoot::new();
    let mut repo = repository(temp.path());
    // Exercise the path that has no normalized fingerprint size for admission.
    repo.stamp_byte_limit = 1;
    let value = artifact("bounds", b"abc");
    block_on(repo.publish(value.clone())).unwrap();
    (temp, Arc::new(repo), value)
}

#[test]
fn indexed_component_limit_rejects_before_any_disk_verification() {
    let (temp, repo, value) = prepare();
    let release = &value.descriptor.release_digest;
    let owned = source(&repo);
    let mut ceiling = limits(&owned, release);
    assert!(owned.identity(release).unwrap().is_none());
    ceiling.maximum_component_bytes -= 1;
    fs::remove_file(release_dir(temp.path(), release).join("COMPLETE")).unwrap();
    let before = repo.verification_snapshot();
    assert_eq!(
        owned.fetch_blocking(release, ceiling).unwrap_err().code,
        PlatformErrorCode::ResourceExhausted
    );
    let after = repo.verification_snapshot();
    assert_eq!(after.full_fetch_attempts, before.full_fetch_attempts + 1);
    assert_eq!(
        after.component_verification_attempts,
        before.component_verification_attempts
    );
    assert_eq!(after.component_bytes_hashed, before.component_bytes_hashed);
}

#[test]
fn grown_component_cannot_use_the_larger_repository_allowance() {
    let (temp, repo, value) = prepare();
    let release = &value.descriptor.release_digest;
    let owned = source(&repo);
    let ceiling = limits(&owned, release);
    assert!(repo.config.max_component_bytes > ceiling.maximum_component_bytes);
    fs::write(
        release_dir(temp.path(), release).join("component.wasm"),
        b"abcd",
    )
    .unwrap();
    let before = repo.verification_snapshot();
    assert_eq!(
        owned.fetch_blocking(release, ceiling).unwrap_err().code,
        PlatformErrorCode::ResourceExhausted
    );
    let after = repo.verification_snapshot();
    assert_eq!(
        after.component_verification_attempts,
        before.component_verification_attempts + 1
    );
    assert_eq!(after.component_bytes_hashed, before.component_bytes_hashed);
    // The compatible old fetch still applies its own configured limit and then
    // rejects the same file's integrity rather than trusting the indexed size.
    assert_eq!(
        block_on(repo.fetch(release)).unwrap_err().code,
        PlatformErrorCode::CorruptArtifact
    );
}

#[test]
fn exact_document_caps_succeed_and_one_byte_less_fails_before_component_read() {
    let (temp, repo, value) = prepare();
    let release = &value.descriptor.release_digest;
    let owned = source(&repo);
    let entry = release_dir(temp.path(), release);
    let mut ceiling = limits(&owned, release);
    ceiling.maximum_metadata_document_bytes = fs::read(entry.join("metadata.json")).unwrap().len();
    ceiling.maximum_manifest_document_bytes = fs::read(entry.join("manifest.json")).unwrap().len();
    assert_eq!(owned.fetch_blocking(release, ceiling).unwrap(), value);
    for metadata in [true, false] {
        let mut smaller = ceiling;
        if metadata {
            smaller.maximum_metadata_document_bytes -= 1;
        } else {
            smaller.maximum_manifest_document_bytes -= 1;
        }
        let before = repo.verification_snapshot();
        assert_eq!(
            owned.fetch_blocking(release, smaller).unwrap_err().code,
            PlatformErrorCode::ResourceExhausted
        );
        let after = repo.verification_snapshot();
        assert_eq!(
            after.component_verification_attempts,
            before.component_verification_attempts
        );
        assert_eq!(after.component_bytes_hashed, before.component_bytes_hashed);
    }
}

#[test]
fn caller_limits_cannot_raise_repository_document_or_component_limits() {
    let temp = TempRoot::new();
    let value = artifact("intersection", b"abc");
    let release = &value.descriptor.release_digest;
    let repo = repository(temp.path());
    block_on(repo.publish(value.clone())).unwrap();
    let entry = release_dir(temp.path(), release);
    let metadata = fs::read(entry.join("metadata.json")).unwrap();
    drop(repo);
    let repo = Arc::new(
        DirectoryArtifactRepository::open(
            temp.path(),
            DirectoryArtifactRepositoryConfig {
                max_component_bytes: 3,
                max_metadata_bytes: metadata.len(),
                max_descriptor_bytes: metadata.len(),
                ..DirectoryArtifactRepositoryConfig::default()
            },
        )
        .unwrap(),
    );
    let owned = source(&repo);
    let ceiling = ArtifactPreparationReadLimits {
        maximum_component_bytes: usize::MAX,
        maximum_metadata_document_bytes: usize::MAX,
        maximum_manifest_document_bytes: usize::MAX,
    };
    assert_eq!(owned.fetch_blocking(release, ceiling).unwrap(), value);
    let mut larger = metadata.clone();
    larger.push(b' ');
    fs::write(entry.join("metadata.json"), larger).unwrap();
    assert_eq!(
        owned.fetch_blocking(release, ceiling).unwrap_err().code,
        PlatformErrorCode::ResourceExhausted
    );
    fs::write(entry.join("metadata.json"), metadata).unwrap();
    fs::write(entry.join("component.wasm"), b"abcd").unwrap();
    assert_eq!(
        owned.fetch_blocking(release, ceiling).unwrap_err().code,
        PlatformErrorCode::ResourceExhausted
    );
}

#[test]
fn fresh_owned_fetch_preserves_complete_and_component_integrity_errors() {
    for target in [
        "COMPLETE",
        "metadata.json",
        "manifest.json",
        "component.wasm",
    ] {
        let (temp, repo, value) = prepare();
        let release = &value.descriptor.release_digest;
        let owned = source(&repo);
        let ceiling = limits(&owned, release);
        fs::write(release_dir(temp.path(), release).join(target), b"x").unwrap();
        let owned_error = owned.fetch_blocking(release, ceiling).unwrap_err();
        let old_error = block_on(repo.fetch(release)).unwrap_err();
        assert_eq!(owned_error, old_error, "{target}");
        assert_eq!(owned_error.code, PlatformErrorCode::CorruptArtifact);
    }
}

#[test]
fn noncanonical_whitespace_bounds_do_not_replace_lifecycle_content_identity() {
    use latent_manifest::__serde_json as json;
    let temp = TempRoot::new();
    let value = artifact("whitespace", b"abc");
    let release = &value.descriptor.release_digest;
    let repo = Arc::new(repository(temp.path()));
    block_on(repo.publish(value.clone())).unwrap();
    let owned = source(&repo);
    let proof = owned.identity(release).unwrap().unwrap();
    let entry = release_dir(temp.path(), release);
    let parsed: json::Value =
        json::from_slice(&fs::read(entry.join("metadata.json")).unwrap()).unwrap();
    let mut changed = json::to_vec_pretty(&parsed).unwrap();
    changed.resize(changed.len() + proof.metadata().charged_bytes(), b' ');
    let (descriptor, contracts) =
        super::super::super::metadata_codec::decode_metadata(&changed, changed.len()).unwrap();
    let equivalent = CapsuleArtifact {
        descriptor,
        contracts,
        ..value.clone()
    };
    proof
        .verify_metadata(
            &equivalent,
            proof.metadata().charged_bytes(),
            proof.metadata().required_type_depth(),
        )
        .unwrap();
    assert_eq!(equivalent, value);
    let completion = super::super::super::integrity::CompletionRecord::from_payloads(
        &value.descriptor,
        &changed,
        &fs::read(entry.join("manifest.json")).unwrap(),
    );
    fs::write(entry.join("metadata.json"), changed).unwrap();
    fs::write(entry.join("COMPLETE"), completion.encode().unwrap()).unwrap();
    assert_eq!(
        owned
            .fetch_blocking(release, limits(&owned, release))
            .expect_err("fresh reads bind the exact admitted COMPLETE")
            .code,
        PlatformErrorCode::CorruptArtifact
    );
}
