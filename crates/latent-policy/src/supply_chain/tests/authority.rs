use super::*;
use latent_artifacts::AdmissionAuthority;
use latent_core::{PlatformErrorCode, TenantId};

fn owner(fixture: &Fixture, root: &std::path::Path) -> SupplyChainAuthority {
    SupplyChainAuthority::open(root, fixture.approved(), fixture.clock.clone(), 5).unwrap()
}

#[test]
fn valid_admission_derives_publisher_and_historical_receipt_reverifies_on_reopen() {
    let fixture = Fixture::new();
    let directory = tempfile::tempdir().unwrap();
    let authority = owner(&fixture, directory.path());
    let admitted = authority
        .verify(&TenantId("tests".into()), fixture.upload())
        .unwrap();
    assert_eq!(
        admitted.artifact.descriptor.publisher.as_ref().unwrap().0,
        "publisher-a"
    );
    admitted.grant.check_current().unwrap();
    let binding = admitted.grant.binding().clone();
    assert!(binding.receipt.len() < 4096);
    if let Some(path) = std::env::var_os("LSF_ADMISSION_RECEIPT_OUTPUT") {
        std::fs::write(path, &binding.receipt).unwrap();
    }
    drop(admitted);
    drop(authority);
    // The durable future ceiling deliberately rejects immediate restart.
    assert!(SupplyChainAuthority::open(
        directory.path(),
        fixture.approved(),
        fixture.clock.clone(),
        5
    )
    .is_err());
    fixture.clock.set(NOW + 5);
    let reopened = owner(&fixture, directory.path());
    let fresh = reopened.recover(&binding, fixture.upload()).unwrap();
    assert_eq!(fresh.grant.binding(), &binding);
    fresh.grant.check_current().unwrap();
}

#[test]
fn required_evidence_tamper_wrong_tenant_and_spare_capacity_reject() {
    let fixture = Fixture::new();
    let directory = tempfile::tempdir().unwrap();
    let authority = owner(&fixture, directory.path());
    let tenant = TenantId("tests".into());
    assert_eq!(
        authority
            .verify(&tenant, fixture.wrong_subject_upload())
            .err()
            .unwrap()
            .message,
        "signature-subject-mismatch"
    );
    let mut unsigned = fixture.upload();
    unsigned.signatures.clear();
    assert!(authority.verify(&tenant, unsigned).is_err());
    let mut missing = fixture.upload();
    missing.provenance.clear();
    assert!(authority.verify(&tenant, missing).is_err());
    let mut tampered = fixture.upload();
    tampered.layers[0].1[0] ^= 1;
    assert!(authority.verify(&tenant, tampered).is_err());
    let mut signature = fixture.upload();
    signature.signatures[0].payload[0] ^= 1;
    assert!(authority.verify(&tenant, signature).is_err());
    assert!(authority
        .verify(&TenantId("someone-else".into()), fixture.upload())
        .is_err());
    let mut excessive = fixture.upload();
    excessive.signatures.reserve(20);
    assert_eq!(
        authority.verify(&tenant, excessive).err().unwrap().code,
        PlatformErrorCode::ResourceExhausted
    );
}

#[test]
fn uncovered_time_never_advances_clock_and_failed_covered_requests_do() {
    let fixture = Fixture::new();
    let directory = tempfile::tempdir().unwrap();
    let authority = owner(&fixture, directory.path());
    fixture.clock.set(NOW + 5);
    assert!(authority
        .verify(&TenantId("tests".into()), fixture.upload())
        .is_err());
    assert_eq!(authority.inner.lock().unwrap().observed_at, NOW);
    fixture.clock.set(NOW + 3);
    let mut unsigned = fixture.upload();
    unsigned.signatures.clear();
    assert!(authority
        .verify(&TenantId("tests".into()), unsigned)
        .is_err());
    assert_eq!(authority.inner.lock().unwrap().observed_at, NOW + 3);
    fixture.clock.set(NOW + 2);
    assert!(authority
        .verify(&TenantId("tests".into()), fixture.upload())
        .is_err());
    fixture.clock.set(NOW + 5);
    authority.renew_clock_lease().unwrap();
    authority
        .verify(&TenantId("tests".into()), fixture.upload())
        .unwrap();
}

#[test]
fn grant_fence_is_nonblocking_and_currentness_rechecks_inside_commit() {
    let fixture = Fixture::new();
    let directory = tempfile::tempdir().unwrap();
    let authority = owner(&fixture, directory.path());
    let admitted = authority
        .verify(&TenantId("tests".into()), fixture.upload())
        .unwrap();
    admitted
        .grant
        .with_current(&mut |checker| {
            assert_eq!(
                admitted.grant.check_current().unwrap_err().code,
                PlatformErrorCode::Unavailable
            );
            assert!(authority.renew_clock_lease().is_err());
            checker.check()?;
            fixture.clock.set(NOW + 5);
            assert!(checker.check().is_err());
            Ok(())
        })
        .unwrap();
    assert!(admitted.grant.check_current().is_err());
}

#[test]
fn policy_change_revokes_old_grants_and_exact_original_evidence_can_refresh() {
    let mut fixture = Fixture::new();
    let directory = tempfile::tempdir().unwrap();
    let authority = owner(&fixture, directory.path());
    let admitted = authority
        .verify(&TenantId("tests".into()), fixture.upload())
        .unwrap();
    fixture.policy["generation"] = serde_json::json!(2);
    authority.replace_policy(fixture.approved()).unwrap();
    assert!(admitted.grant.check_current().is_err());
    let fresh = authority
        .recover(admitted.grant.binding(), fixture.upload())
        .unwrap();
    fresh.grant.check_current().unwrap();
    fixture.policy["generation"] = serde_json::json!(3);
    fixture.policy["publisherRevocations"]["generation"] = serde_json::json!(2);
    fixture.policy["publisherRevocations"]["revokedPublishers"] =
        serde_json::json!(["publisher-a"]);
    authority.replace_policy(fixture.approved()).unwrap();
    assert!(fresh.grant.check_current().is_err());
    assert!(authority
        .recover(admitted.grant.binding(), fixture.upload())
        .is_err());
}

#[test]
fn proof_age_expiry_requires_fresh_verification_without_rewriting_history() {
    let fixture = Fixture::new();
    let directory = tempfile::tempdir().unwrap();
    let authority = owner(&fixture, directory.path());
    let admitted = authority
        .verify(&TenantId("tests".into()), fixture.upload())
        .unwrap();
    fixture.clock.set(NOW + 60);
    authority.renew_clock_lease().unwrap();
    assert!(admitted.grant.check_current().is_err());
    let fresh = authority
        .recover(admitted.grant.binding(), fixture.upload())
        .unwrap();
    fresh.grant.check_current().unwrap();
    assert_eq!(
        fresh.grant.binding().receipt,
        admitted.grant.binding().receipt
    );
}

#[test]
fn corruption_and_exclusive_ledger_ownership_fail_closed() {
    let fixture = Fixture::new();
    let directory = tempfile::tempdir().unwrap();
    let authority = owner(&fixture, directory.path());
    assert!(SupplyChainAuthority::open(
        directory.path(),
        fixture.approved(),
        fixture.clock.clone(),
        5
    )
    .is_err());
    let admitted = authority
        .verify(&TenantId("tests".into()), fixture.upload())
        .unwrap();
    let mut binding = admitted.grant.binding().clone();
    binding.receipt[0] ^= 1;
    assert_eq!(
        authority
            .recover(&binding, fixture.upload())
            .err()
            .unwrap()
            .code,
        PlatformErrorCode::CorruptArtifact
    );
    drop(admitted);
    drop(authority);
    fixture.clock.set(NOW + 5);
    std::fs::write(directory.path().join("floor.json"), b"{}").unwrap();
    assert!(SupplyChainAuthority::open(
        directory.path(),
        fixture.approved(),
        fixture.clock.clone(),
        5
    )
    .is_err());
}

#[test]
fn every_policy_durability_cut_halts_current_authority_and_preserves_restart_floors() {
    for cut in 1..=4 {
        let mut fixture = Fixture::new();
        let original = fixture.policy.clone();
        let directory = tempfile::tempdir().unwrap();
        let authority = owner(&fixture, directory.path());
        authority
            .inner
            .lock()
            .unwrap()
            .ledger
            .fault
            .store(cut, std::sync::atomic::Ordering::SeqCst);
        fixture.policy["generation"] = serde_json::json!(2);
        assert!(authority.replace_policy(fixture.approved()).is_err());
        assert!(authority
            .verify(&TenantId("tests".into()), fixture.upload())
            .is_err());
        assert!(authority.renew_clock_lease().is_err());
        drop(authority);
        fixture.clock.set(NOW + 5);
        if cut >= 3 {
            let old =
                SupplyChainPolicy::from_json(&serde_json::to_vec(&original).unwrap()).unwrap();
            assert!(
                SupplyChainAuthority::open(directory.path(), old, fixture.clock.clone(), 5)
                    .is_err()
            );
        }
        let recovered = owner(&fixture, directory.path());
        recovered
            .verify(&TenantId("tests".into()), fixture.upload())
            .unwrap();
    }
}

#[test]
fn retired_node_denies_held_grants_and_never_renews() {
    let fixture = Fixture::new();
    let directory = tempfile::tempdir().unwrap();
    let authority = owner(&fixture, directory.path());
    let admitted = authority
        .verify(&TenantId("tests".into()), fixture.upload())
        .unwrap();
    authority.retire();
    assert!(admitted.grant.check_current().is_err());
    assert!(authority.renew_clock_lease().is_err());
    assert!(authority
        .verify(&TenantId("tests".into()), fixture.upload())
        .is_err());
}

#[test]
fn initialized_ledger_missing_floor_cannot_restart_as_fresh() {
    let fixture = Fixture::new();
    let directory = tempfile::tempdir().unwrap();
    drop(owner(&fixture, directory.path()));
    std::fs::remove_file(directory.path().join("floor.json")).unwrap();
    fixture.clock.set(NOW + 5);
    assert!(SupplyChainAuthority::open(
        directory.path(),
        fixture.approved(),
        fixture.clock.clone(),
        5
    )
    .is_err());
}

#[test]
fn existing_builder_identifier_profile_round_trips_historical_receipt() {
    let fixture = Fixture::with_builder("build@source/v1");
    let directory = tempfile::tempdir().unwrap();
    let authority = owner(&fixture, directory.path());
    let admitted = authority
        .verify(&TenantId("tests".into()), fixture.upload())
        .unwrap();
    authority
        .recover(admitted.grant.binding(), fixture.upload())
        .unwrap();
}

#[test]
fn fresh_replacement_recovers_expired_outer_policy_but_identical_expired_child_is_not_refresh() {
    let mut fixture = Fixture::new();
    fixture.policy["validUntil"] = serde_json::json!(NOW + 1);
    let directory = tempfile::tempdir().unwrap();
    let authority = owner(&fixture, directory.path());
    fixture.clock.set(NOW + 2);
    fixture.policy["generation"] = serde_json::json!(2);
    fixture.policy["validUntil"] = serde_json::json!(3000);
    authority.replace_policy(fixture.approved()).unwrap();
    authority
        .verify(&TenantId("tests".into()), fixture.upload())
        .unwrap();
    fixture.policy["generation"] = serde_json::json!(3);
    fixture.policy["builderRevocations"]["generation"] = serde_json::json!(2);
    fixture.policy["builderRevocations"]["validUntil"] = serde_json::json!(NOW + 3);
    authority.replace_policy(fixture.approved()).unwrap();
    fixture.clock.set(NOW + 4);
    assert!(authority.replace_policy(fixture.approved()).is_err());
}

#[test]
fn newly_required_inventory_is_ineligible_history_not_storage_corruption() {
    let mut fixture = Fixture::without_inventory();
    fixture.policy["sbom"]["embedded"] = serde_json::json!("optional");
    let directory = tempfile::tempdir().unwrap();
    let authority = owner(&fixture, directory.path());
    let admitted = authority
        .verify(&TenantId("tests".into()), fixture.upload())
        .unwrap();
    fixture.policy["generation"] = serde_json::json!(2);
    fixture.policy["sbom"]["embedded"] = serde_json::json!("required");
    authority.replace_policy(fixture.approved()).unwrap();
    let error = authority
        .recover(admitted.grant.binding(), fixture.upload())
        .err()
        .unwrap();
    assert_eq!(error.code, PlatformErrorCode::PermissionDenied);
    assert_eq!(error.message, "required-embedded-sbom-missing");
}
