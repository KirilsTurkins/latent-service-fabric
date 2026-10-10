use super::*;
use latent_artifacts::AdmissionAuthority;
use latent_manifest::{ManifestValidationProfile, RuntimeCompatibilityProfile};

fn profile() -> ManifestValidationProfile {
    ManifestValidationProfile::phase4(
        latent_core::BudgetProfile::Phase4,
        latent_core::PHASE4_HOST_ABI_V1,
        &latent_manifest::phase4_host_abi_digest(),
    )
    .unwrap()
}
fn owner(fixture: &Fixture, root: &std::path::Path) -> SupplyChainAuthority {
    SupplyChainAuthority::open_with_runtime_and_manifest_profile(
        root,
        fixture.approved(),
        fixture.clock.clone(),
        5,
        Arc::new(
            RuntimeCompatibilityProfile::new(
                "wasmtime",
                "48.0.3",
                "x86_64-unknown-linux-gnu",
                &["x86_64.sse2"],
                64 * 1024 * 1024,
                100_000_000,
            )
            .unwrap(),
        ),
        profile(),
    )
    .unwrap()
}

#[test]
fn signed_transaction_package_requires_explicit_profile_and_recovers_original_evidence() {
    let fixture = Fixture::transactional();
    let strict_root = tempfile::tempdir().unwrap();
    let strict = SupplyChainAuthority::open(
        strict_root.path(),
        fixture.approved(),
        fixture.clock.clone(),
        5,
    )
    .unwrap();
    let tenant = latent_core::TenantId("tests".into());
    assert!(strict.verify(&tenant, fixture.upload()).is_err());
    let root = tempfile::tempdir().unwrap();
    let selected = owner(&fixture, root.path());
    let admitted = selected.verify(&tenant, fixture.upload()).unwrap();
    admitted.grant.check_current().unwrap();
    let binding = admitted.grant.binding().clone();
    let release = admitted.artifact.descriptor.release_digest.clone();
    drop(admitted);
    selected.retire();
    drop(selected);
    fixture.clock.set(NOW + 5);
    let reopened = owner(&fixture, root.path());
    let recovered = reopened.recover(&binding, fixture.upload()).unwrap();
    assert_eq!(recovered.grant.binding(), &binding);
    assert_eq!(recovered.artifact.descriptor.release_digest, release);
    recovered.grant.check_current().unwrap();
}

#[test]
fn selected_transaction_profile_never_replaces_signatures_provenance_or_current_owner() {
    let fixture = Fixture::transactional();
    let root = tempfile::tempdir().unwrap();
    let selected = owner(&fixture, root.path());
    let tenant = latent_core::TenantId("tests".into());
    for which in ["publisher", "builder", "tamper"] {
        let mut upload = fixture.upload();
        match which {
            "publisher" => upload.signatures.clear(),
            "builder" => upload.provenance.clear(),
            "tamper" => upload.layers[0].1[0] ^= 1,
            _ => unreachable!(),
        }
        assert!(selected.verify(&tenant, upload).is_err(), "{which}");
    }
    let admitted = selected.verify(&tenant, fixture.upload()).unwrap();
    selected.retire();
    assert!(admitted.grant.check_current().is_err());
    assert!(selected.verify(&tenant, fixture.upload()).is_err());
}

#[test]
fn signed_transaction_history_cannot_select_its_own_restart_profile() {
    let fixture = Fixture::transactional();
    let root = tempfile::tempdir().unwrap();
    let selected = owner(&fixture, root.path());
    let admitted = selected
        .verify(&latent_core::TenantId("tests".into()), fixture.upload())
        .unwrap();
    let binding = admitted.grant.binding().clone();
    drop(admitted);
    selected.retire();
    drop(selected);
    fixture.clock.set(NOW + 5);
    let strict =
        SupplyChainAuthority::open(root.path(), fixture.approved(), fixture.clock.clone(), 5)
            .unwrap();
    assert!(strict.recover(&binding, fixture.upload()).is_err());
}
