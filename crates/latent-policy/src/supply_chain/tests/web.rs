use super::*;
use latent_artifacts::{web::WEB_MANIFEST_PATH, AdmissionAuthority, PackageAdmissionUpload};
use latent_core::{PlatformErrorCode, TenantId};

mod angular_build;
mod preparation;

fn fixture() -> Fixture {
    let mut fixture = Fixture::new();
    fixture.enable_web_builder();
    fixture
}
fn upload(fixture: &Fixture) -> PackageAdmissionUpload {
    fixture.web_upload(support::web_input(None), true, false)
}
fn authority(fixture: &Fixture, path: &std::path::Path) -> SupplyChainAuthority {
    SupplyChainAuthority::open(path, fixture.approved(), fixture.clock.clone(), 5).unwrap()
}

#[test]
fn componentless_web_admission_reverifies_on_restart_and_old_owner_grants_stay_retired() {
    let fixture = fixture();
    let directory = tempfile::tempdir().unwrap();
    let owner = authority(&fixture, directory.path());
    let admitted = owner
        .verify_web(&TenantId("tests".into()), upload(&fixture))
        .unwrap();
    let binding = admitted.grant.binding().clone();
    assert_eq!(binding.package, *admitted.layout.package());
    assert_eq!(binding.assets, *admitted.layout.assets_digest());
    assert!(!std::str::from_utf8(&binding.receipt)
        .unwrap()
        .contains("\"release\""));
    admitted.grant.check_current().unwrap();
    drop(owner);
    assert!(admitted.grant.check_current().is_err());
    fixture.clock.set(NOW + 5);
    let fresh = authority(&fixture, directory.path());
    let recovered = fresh.recover_web(&binding, upload(&fixture)).unwrap();
    assert_eq!(recovered.grant.binding(), &binding);
    recovered.grant.check_current().unwrap();
    assert!(admitted.grant.check_current().is_err());
}

#[test]
fn web_requires_publisher_builder_inventory_and_allowed_tenant() {
    let fixture = fixture();
    let directory = tempfile::tempdir().unwrap();
    let owner = authority(&fixture, directory.path());
    let tenant = TenantId("tests".into());
    for index in 0..6 {
        let mut input = upload(&fixture);
        match index {
            0 => input.signatures.clear(),
            1 => input.provenance.clear(),
            2 => input.layers[0].1[0] ^= 1,
            3 => input.signatures[0].payload[0] ^= 1,
            4 => input.provenance[0].payload[0] ^= 1,
            _ => input.signatures.reserve_exact(20),
        }
        assert!(owner.verify_web(&tenant, input).is_err(), "{index}");
    }
    assert!(owner
        .verify_web(&TenantId("other".into()), upload(&fixture))
        .is_err());
    let missing = fixture.web_upload(support::web_input(None), false, false);
    assert_eq!(
        owner.verify_web(&tenant, missing).err().unwrap().message,
        "required-embedded-sbom-missing"
    );
    let old_fixture = Fixture::new();
    let old_root = tempfile::tempdir().unwrap();
    let old = authority(&old_fixture, old_root.path());
    assert_eq!(
        old.verify_web(&tenant, upload(&old_fixture))
            .err()
            .unwrap()
            .message,
        "provenance-predicate-disallowed"
    );
}

#[test]
fn valid_signatures_cannot_make_a_wrong_asset_tree_or_incompatible_renderer_eligible() {
    let fixture = fixture();
    let directory = tempfile::tempdir().unwrap();
    let owner = authority(&fixture, directory.path());
    let tenant = TenantId("tests".into());
    let mut input = support::web_input(None);
    let metadata = input
        .layers
        .iter_mut()
        .find(|value| value.path == WEB_MANIFEST_PATH)
        .unwrap();
    let mut value: serde_json::Value = serde_json::from_slice(&metadata.bytes).unwrap();
    value["assetsDigest"] = format!("sha256:{}", "a".repeat(64)).into();
    metadata.bytes = serde_json::to_vec(&value).unwrap();
    assert!(owner
        .verify_web(&tenant, fixture.web_upload(input, true, false))
        .is_err());
    let bad_renderer = support::web_input(Some(b"\0asm\x0d\0\x01\0"));
    assert!(owner
        .verify_web(&tenant, fixture.web_upload(bad_renderer, true, false))
        .is_err());
}

#[test]
fn web_and_capsule_grants_share_the_same_nonblocking_policy_fence_and_reject_foreign_owners() {
    let fixture = fixture();
    let directory = tempfile::tempdir().unwrap();
    let owner = authority(&fixture, directory.path());
    let tenant = TenantId("tests".into());
    let web = owner.verify_web(&tenant, upload(&fixture)).unwrap();
    let capsule = owner.verify(&tenant, fixture.upload()).unwrap();
    let other_root = tempfile::tempdir().unwrap();
    let other = authority(&fixture, other_root.path());
    let foreign = other.verify_web(&tenant, upload(&fixture)).unwrap();
    web.grant
        .with_current(&mut |checker| {
            checker.check()?;
            checker.check_grant(capsule.grant.as_ref())?;
            checker.check_web_grant(web.grant.as_ref())?;
            assert!(checker.check_web_grant(foreign.grant.as_ref()).is_err());
            assert_eq!(
                web.grant.check_current().unwrap_err().message,
                "admission-authority-busy"
            );
            assert!(owner.verify_web(&tenant, upload(&fixture)).is_err());
            Ok(())
        })
        .unwrap();
    capsule
        .grant
        .with_current(&mut |checker| checker.check_web_grant(web.grant.as_ref()))
        .unwrap();
    let mut next = fixture.policy.clone();
    next["generation"] = 2.into();
    next["tenants"] = serde_json::json!([]);
    owner
        .replace_policy(SupplyChainPolicy::from_json(&serde_json::to_vec(&next).unwrap()).unwrap())
        .unwrap();
    assert!(web.grant.check_current().is_err());
    assert!(capsule.grant.check_current().is_err());
}

#[test]
fn malformed_web_history_is_rejected_before_expired_evidence_can_leave_history() {
    let fixture = fixture();
    let directory = tempfile::tempdir().unwrap();
    let owner = authority(&fixture, directory.path());
    let admitted = owner
        .verify_web(&TenantId("tests".into()), upload(&fixture))
        .unwrap();
    let binding = admitted.grant.binding().clone();
    fixture.clock.set(2000);
    let mut tampered = upload(&fixture);
    tampered.layers[0].1[0] ^= 1;
    assert_eq!(
        owner.recover_web(&binding, tampered).err().unwrap().code,
        PlatformErrorCode::CorruptArtifact
    );
    assert_eq!(
        owner
            .recover_web(&binding, upload(&fixture))
            .err()
            .unwrap()
            .code,
        PlatformErrorCode::PermissionDenied
    );
    assert!(admitted.grant.check_current().is_err());
}

#[test]
fn corrected_inventory_retains_distinct_package_and_receipt_with_same_web_outputs() {
    let fixture = fixture();
    let directory = tempfile::tempdir().unwrap();
    let owner = authority(&fixture, directory.path());
    let tenant = TenantId("tests".into());
    let original = owner.verify_web(&tenant, upload(&fixture)).unwrap();
    let corrected = owner
        .verify_web(
            &tenant,
            fixture.web_upload(support::web_input(None), true, true),
        )
        .unwrap();
    assert_ne!(original.layout.package(), corrected.layout.package());
    assert_eq!(
        original.layout.assets_digest(),
        corrected.layout.assets_digest()
    );
    assert_ne!(original.grant.binding(), corrected.grant.binding());
    assert!(owner
        .recover_web(
            original.grant.binding(),
            fixture.web_upload(support::web_input(None), true, true)
        )
        .is_err());
    original.grant.check_current().unwrap();
    corrected.grant.check_current().unwrap();
}

#[test]
#[ignore = "Built public async web component; required by tools/validate_contracts.sh"]
fn actual_web_component_passes_signed_ssr_admission_and_restart() {
    let path = std::env::var_os("LSF_WEB_COMPONENT").expect("built public async web component");
    let component = std::fs::read(path).unwrap();
    assert!(component.len() < 1024 * 1024);
    let checked = latent_packaging::validate_web_renderer(
        &component,
        latent_artifacts::web::WebRendererProfile::WasmWebBufferedV1,
        latent_packaging::SemanticLimits::default(),
    )
    .unwrap();
    assert_eq!(checked.world(), latent_artifacts::web::WEB_WORLD);
    let fixture = fixture();
    let directory = tempfile::tempdir().unwrap();
    let owner = authority(&fixture, directory.path());
    let input = || fixture.web_upload(support::web_input(Some(&component)), true, false);
    let admitted = owner
        .verify_web(&TenantId("tests".into()), input())
        .unwrap();
    let binding = admitted.grant.binding().clone();
    assert_eq!(
        admitted.layout.manifest().renderer.as_ref().unwrap().digest,
        checked.component_digest().as_str()
    );
    drop(owner);
    fixture.clock.set(NOW + 5);
    let fresh = authority(&fixture, directory.path());
    let recovered = fresh.recover_web(&binding, input()).unwrap();
    recovered.grant.check_current().unwrap();
    assert_eq!(recovered.layout, admitted.layout);
    assert!(admitted.grant.check_current().is_err());
}
