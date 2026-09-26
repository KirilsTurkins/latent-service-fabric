use super::*;

#[test]
fn structural_web_work_retains_one_shared_verification_slot_without_blocking_clock_renewal() {
    let fixture = fixture();
    let directory = tempfile::tempdir().unwrap();
    let owner = authority(&fixture, directory.path());
    let tenant = TenantId("tests".into());
    let admitted = owner.verify_web(&tenant, upload(&fixture)).unwrap();
    let reservation = owner.inner.verification().unwrap();
    assert_eq!(
        owner
            .verify_web(&tenant, upload(&fixture))
            .err()
            .unwrap()
            .message,
        "admission-verification-busy"
    );
    assert_eq!(
        owner
            .verify(&tenant, fixture.upload())
            .err()
            .unwrap()
            .message,
        "admission-verification-busy"
    );
    fixture.clock.set(NOW + 6);
    owner.renew_clock_lease().unwrap();
    admitted.grant.check_current().unwrap();
    drop(reservation);
    owner.verify_web(&tenant, upload(&fixture)).unwrap();
}

#[test]
fn decoded_web_bytes_cannot_mint_authority_after_policy_replacement_or_retirement() {
    let fixture = fixture();
    let directory = tempfile::tempdir().unwrap();
    let owner = authority(&fixture, directory.path());
    let tenant = TenantId("tests".into());
    let reservation = owner.inner.verification().unwrap();
    let prepared = crate::supply_chain::web::prepare(upload(&fixture)).unwrap();
    let mut next = fixture.policy.clone();
    next["generation"] = 2.into();
    next["tenants"] = serde_json::json!([]);
    owner
        .replace_policy(SupplyChainPolicy::from_json(&serde_json::to_vec(&next).unwrap()).unwrap())
        .unwrap();
    assert_eq!(
        crate::supply_chain::web::with_state(
            &owner.inner,
            &tenant,
            prepared,
            None,
            &mut owner.inner.lock().unwrap()
        )
        .err()
        .unwrap()
        .message,
        "admission-tenant-denied"
    );
    drop(reservation);
    owner.retire();
    assert_eq!(
        owner
            .verify_web(&tenant, upload(&fixture))
            .err()
            .unwrap()
            .message,
        "admission-owner-retired"
    );
}

#[test]
fn failed_structural_validation_releases_the_shared_reservation() {
    let fixture = fixture();
    let directory = tempfile::tempdir().unwrap();
    let owner = authority(&fixture, directory.path());
    let tenant = TenantId("tests".into());
    let mut corrupted = upload(&fixture);
    corrupted.layers[0].1[0] ^= 1;
    assert!(owner.verify_web(&tenant, corrupted).is_err());
    owner.verify_web(&tenant, upload(&fixture)).unwrap();
}
