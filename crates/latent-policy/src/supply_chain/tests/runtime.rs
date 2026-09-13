use super::catalog::ready;
use super::*;
use latent_artifacts::{AdmissionAuthority, ArtifactRepository, DirectoryArtifactRepository};
use latent_core::{PlatformErrorCode, TenantId};
use latent_manifest::RuntimeCompatibilityProfile;

fn profile(version: &str, target: &str, cpu: &[&str]) -> Arc<RuntimeCompatibilityProfile> {
    Arc::new(
        RuntimeCompatibilityProfile::new(
            "wasmtime",
            version,
            target,
            cpu,
            64 * 1024 * 1024,
            10_000_000,
        )
        .unwrap(),
    )
}
fn requirements() -> serde_json::Value {
    serde_json::json!({
        "runtime": {"engine": "wasmtime", "minimumVersion": "47.0.3"},
        "targetTriples": ["x86_64-unknown-linux-gnu"],
        "cpuFeatures": ["x86_64.avx2"]
    })
}

#[test]
fn signed_package_requires_matching_current_runtime_target_and_cpu() {
    let fixture = Fixture::with_runtime_requirements(requirements());
    let tenant = TenantId("tests".to_owned());
    for (version, target, cpu) in [
        ("47.0.2", "x86_64-unknown-linux-gnu", &["x86_64.avx2"][..]),
        ("47.0.3", "x86_64-pc-windows-msvc", &["x86_64.avx2"][..]),
        ("47.0.3", "x86_64-unknown-linux-gnu", &[][..]),
    ] {
        let root = tempfile::tempdir().unwrap();
        let authority = SupplyChainAuthority::open_with_runtime(
            root.path(),
            fixture.approved(),
            fixture.clock.clone(),
            5,
            profile(version, target, cpu),
        )
        .unwrap();
        assert_eq!(
            authority
                .verify(&tenant, fixture.upload())
                .err()
                .unwrap()
                .code,
            PlatformErrorCode::IncompatibleContract
        );
    }
    let root = tempfile::tempdir().unwrap();
    let authority = SupplyChainAuthority::open_with_runtime(
        root.path(),
        fixture.approved(),
        fixture.clock.clone(),
        5,
        profile("47.0.3", "x86_64-unknown-linux-gnu", &["x86_64.avx2"]),
    )
    .unwrap();
    authority
        .verify(&tenant, fixture.upload())
        .unwrap()
        .grant
        .check_current()
        .unwrap();
}

#[test]
fn explicit_requirements_without_host_profile_cannot_acquire_authority() {
    let fixture = Fixture::with_runtime_requirements(requirements());
    let root = tempfile::tempdir().unwrap();
    let authority =
        SupplyChainAuthority::open(root.path(), fixture.approved(), fixture.clock.clone(), 5)
            .unwrap();
    assert_eq!(
        authority
            .verify(&TenantId("tests".to_owned()), fixture.upload())
            .err()
            .unwrap()
            .code,
        PlatformErrorCode::IncompatibleContract
    );
}

#[test]
fn incompatible_restart_retains_exact_history_but_no_live_eligibility() {
    let fixture = Fixture::with_runtime_requirements(requirements());
    let root = tempfile::tempdir().unwrap();
    let authority_root = root.path().join("authority");
    let catalog_root = root.path().join("catalog");
    let authority = Arc::new(
        SupplyChainAuthority::open_with_runtime(
            &authority_root,
            fixture.approved(),
            fixture.clock.clone(),
            5,
            profile("47.0.3", "x86_64-unknown-linux-gnu", &["x86_64.avx2"]),
        )
        .unwrap(),
    );
    let catalog = DirectoryArtifactRepository::open_enforced(
        &catalog_root,
        Default::default(),
        Default::default(),
        authority.clone(),
    )
    .unwrap();
    let admitted = ready(catalog.admit_package(
        &TenantId("tests".to_owned()),
        fixture.upload(),
        &mut |_| Ok(()),
    ))
    .unwrap();
    let release = admitted.descriptor.release_digest.clone();
    let binding = catalog
        .release_eligibility(&release)
        .unwrap()
        .unwrap()
        .binding()
        .clone();
    let complete_path = catalog
        .root()
        .join("releases")
        .join(release.0.strip_prefix("sha256:").unwrap())
        .join("COMPLETE");
    let complete = std::fs::read(&complete_path).unwrap();
    drop(catalog);
    authority.retire();
    drop(authority);
    fixture.clock.set(NOW + 5);
    let authority = Arc::new(
        SupplyChainAuthority::open_with_runtime(
            &authority_root,
            fixture.approved(),
            fixture.clock.clone(),
            5,
            profile("47.0.3", "x86_64-unknown-linux-gnu", &[]),
        )
        .unwrap(),
    );
    let catalog = DirectoryArtifactRepository::open_enforced(
        &catalog_root,
        Default::default(),
        Default::default(),
        authority.clone(),
    )
    .unwrap();
    assert_eq!(
        ready(catalog.get_catalog_entry(&TenantId("tests".to_owned()), &release)).unwrap(),
        Some(admitted)
    );
    assert_eq!(std::fs::read(complete_path).unwrap(), complete);
    assert!(catalog.release_eligibility(&release).is_err());
    assert!(ready(catalog.fetch(&release)).is_err());
    assert_eq!(
        authority
            .recover(&binding, fixture.upload())
            .err()
            .unwrap()
            .code,
        PlatformErrorCode::IncompatibleContract
    );
}
