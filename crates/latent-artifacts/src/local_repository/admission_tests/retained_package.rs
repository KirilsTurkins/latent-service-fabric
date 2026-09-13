use super::*;

const LIMIT: usize = 1024 * 1024;

#[test]
fn historical_package_source_preserves_exact_input_and_grant_owner() {
    let root = TempRoot::new();
    let authority = Authority::new();
    let repo = open(&root, &authority);
    let summary = admit(&repo).unwrap();
    let release = &summary.descriptor.release_digest;
    let before = repo.release_eligibility(release).unwrap().unwrap();
    let source = block_on(repo.retained_package_source(&tenant(), release, LIMIT))
        .unwrap()
        .unwrap();
    assert_eq!(source.tenant(), &tenant());
    assert_eq!(source.component(), release);
    assert_eq!(
        source.package(),
        &crate::package::package_digest(&upload().manifest)
    );
    assert!(source.retained_bytes() <= LIMIT);
    let (manifest, configuration, layers) = source.into_parts();
    let expected = upload();
    assert_eq!(manifest, expected.manifest);
    assert_eq!(configuration, expected.configuration);
    assert_eq!(layers, expected.layers);
    before.check_current().unwrap();
    let after = repo.release_eligibility(release).unwrap().unwrap();
    assert_eq!(before, after);
    assert_eq!(before.cache_digest(), after.cache_digest());
}

#[test]
fn foreign_scope_and_invalid_limits_do_not_read_package_bytes() {
    let root = TempRoot::new();
    let authority = Authority::new();
    let repo = open(&root, &authority);
    let summary = admit(&repo).unwrap();
    let release = &summary.descriptor.release_digest;
    let before = repo.verification_snapshot();
    assert!(
        block_on(repo.retained_package_source(&TenantId("foreign".into()), release, LIMIT))
            .unwrap()
            .is_none()
    );
    for limit in [0, 64 * 1024 * 1024 + 1] {
        assert_eq!(
            block_on(repo.retained_package_source(&tenant(), release, limit))
                .unwrap_err()
                .code,
            PlatformErrorCode::InvalidArgument
        );
    }
    assert_eq!(repo.verification_snapshot(), before);
}

#[test]
fn historical_read_does_not_renew_expired_execution_authority() {
    let root = TempRoot::new();
    let authority = Authority::new();
    let repo = open(&root, &authority);
    let summary = admit(&repo).unwrap();
    let release = &summary.descriptor.release_digest;
    let grant = repo.release_eligibility(release).unwrap().unwrap();
    authority.allowed.store(false, Ordering::Release);
    assert!(grant.check_current().is_err());
    assert!(
        block_on(repo.retained_package_source(&tenant(), release, LIMIT))
            .unwrap()
            .is_some()
    );
    assert!(grant.check_current().is_err());
    assert!(block_on(repo.fetch(release)).is_err());
}

#[test]
fn undersized_budget_and_corrupt_retained_package_fail_closed() {
    let root = TempRoot::new();
    let authority = Authority::new();
    let repo = open(&root, &authority);
    let summary = admit(&repo).unwrap();
    let release = &summary.descriptor.release_digest;
    assert_eq!(
        block_on(repo.retained_package_source(&tenant(), release, 1))
            .unwrap_err()
            .code,
        PlatformErrorCode::ResourceExhausted
    );
    let directory = release_dir(root.path(), release);
    let record: serde_json::Value =
        serde_json::from_slice(&std::fs::read(directory.join("admission.json")).unwrap()).unwrap();
    let file = record["manifest"]["file"].as_str().unwrap();
    let path = directory.join(file);
    let mut bytes = std::fs::read(&path).unwrap();
    bytes[0] ^= 1;
    std::fs::write(path, bytes).unwrap();
    assert!(block_on(repo.retained_package_source(&tenant(), release, LIMIT)).is_err());
}
