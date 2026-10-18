//! Real retained catalog reopen with current publisher/builder/tenant policy.
use super::*;
use std::{fs, path::Path};

fn corrupt_reopen_refuses_before_current_policy_denial(
    catalog_root: &Path,
    directory: &Path,
    authority: &Arc<SupplyChainAuthority>,
) {
    let record: serde_json::Value =
        serde_json::from_slice(&fs::read(directory.join("admission.json")).unwrap()).unwrap();
    let file = record["signatures"][0]["payload"]["file"].as_str().unwrap();
    let path = directory.join(file);
    let original = fs::read(&path).unwrap();
    let mut changed = original.clone();
    changed[0] ^= 1;
    fs::write(&path, changed).unwrap();
    let configured: Arc<dyn AdmissionAuthority> = authority.clone();
    let result = DirectoryArtifactRepository::open_enforced(
        catalog_root,
        DirectoryArtifactRepositoryConfig::default(),
        AdmissionStorageLimits::default(),
        configured,
    );
    fs::write(path, original).unwrap();
    let error = result.err().unwrap();
    assert_eq!(error.code, PlatformErrorCode::CorruptArtifact);
}

#[test]
fn checked_catalog_recovery_keeps_current_revocations_tenant_policy_and_expiry() {
    for case in 0..4 {
        let mut fixture = Fixture::new();
        let root = tempfile::tempdir().unwrap();
        let authority = authority(&fixture, &root.path().join("trust"));
        let catalog_root = root.path().join("catalog");
        let repo = catalog(&catalog_root, &authority);
        let summary = admit(&repo, fixture.upload()).unwrap();
        let release = &summary.descriptor.release_digest;
        let directory = publication_directory(&repo, release);
        let original = repo.release_eligibility(release).unwrap().unwrap();
        let binding = original.binding().clone();
        let tenants = fixture.policy["tenants"].clone();
        drop(repo);
        if case == 3 {
            fixture.clock.set(2000);
            authority.renew_clock_lease().unwrap();
        } else {
            fixture.policy["generation"] = 2.into();
            match case {
                0 => {
                    fixture.policy["publisherRevocations"]["generation"] = 2.into();
                    fixture.policy["publisherRevocations"]["revokedPublishers"] =
                        serde_json::json!(["publisher-a"]);
                }
                1 => {
                    fixture.policy["builderRevocations"]["generation"] = 2.into();
                    fixture.policy["builderRevocations"]["revokedBuilders"] =
                        serde_json::json!(["builder-a"]);
                }
                _ => fixture.policy["tenants"] = serde_json::json!([]),
            }
            authority.replace_policy(fixture.approved()).unwrap();
        }
        let reopened = catalog(&catalog_root, &authority);
        assert_eq!(
            ready(reopened.get_catalog_entry(&tenant(), release)).unwrap(),
            Some(summary.clone())
        );
        assert_eq!(
            reopened.release_eligibility(release).unwrap_err().code,
            PlatformErrorCode::PermissionDenied
        );
        assert!(ready(reopened.fetch(release)).is_err());
        assert!(original.check_current().is_err());
        drop(reopened);
        corrupt_reopen_refuses_before_current_policy_denial(&catalog_root, &directory, &authority);
        if case == 3 {
            continue;
        }
        fixture.policy["generation"] = 3.into();
        fixture.policy["publisherRevocations"]["generation"] = 3.into();
        fixture.policy["publisherRevocations"]["revokedPublishers"] = serde_json::json!([]);
        fixture.policy["builderRevocations"]["generation"] = 3.into();
        fixture.policy["builderRevocations"]["revokedBuilders"] = serde_json::json!([]);
        fixture.policy["tenants"] = tenants;
        authority.replace_policy(fixture.approved()).unwrap();
        let recovered = catalog(&catalog_root, &authority);
        let current = recovered.release_eligibility(release).unwrap().unwrap();
        assert_eq!(current.binding(), &binding);
        current.check_current().unwrap();
        assert!(original.check_current().is_err());
        assert_eq!(
            ready(recovered.get_catalog_entry(&tenant(), release)).unwrap(),
            Some(summary)
        );
    }
}
