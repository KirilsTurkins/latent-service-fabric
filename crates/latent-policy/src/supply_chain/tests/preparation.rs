use super::*;
use crate::supply_chain::verify::{prepare, with_preparation};
use latent_artifacts::AdmissionAuthority;
use latent_core::TenantId;

fn owner(fixture: &Fixture, root: &std::path::Path) -> SupplyChainAuthority {
    SupplyChainAuthority::open(root, fixture.approved(), fixture.clock.clone(), 5).unwrap()
}

#[test]
fn capsule_preparation_retains_one_slot_and_renews_after_work_exceeds_the_lease() {
    let fixture = Fixture::new();
    let directory = tempfile::tempdir().unwrap();
    let authority = owner(&fixture, directory.path());
    let tenant = TenantId("tests".into());
    let existing = authority.verify(&tenant, fixture.upload()).unwrap();
    let admitted = with_preparation(&authority, &tenant, fixture.upload(), |upload| {
        let prepared = prepare(upload)?;
        assert_eq!(
            authority
                .verify(&tenant, fixture.upload())
                .err()
                .unwrap()
                .message,
            "admission-verification-busy"
        );
        assert_eq!(
            authority
                .verify_web(&tenant, fixture.upload())
                .err()
                .unwrap()
                .message,
            "admission-verification-busy"
        );
        assert_eq!(
            authority
                .recover(existing.grant.binding(), fixture.upload())
                .err()
                .unwrap()
                .message,
            "admission-verification-busy"
        );
        existing.grant.check_current().unwrap();
        // The real sampler remains usable while structural bytes are owned.
        fixture.clock.set(NOW + 6);
        authority.renew_clock_lease().unwrap();
        existing.grant.check_current().unwrap();
        // Finish beyond even that renewed five-second lease, without sleeping.
        fixture.clock.set(NOW + 12);
        Ok(prepared)
    })
    .unwrap();
    admitted.grant.check_current().unwrap();
    existing.grant.check_current().unwrap();
    let receipt: serde_json::Value =
        serde_json::from_slice(&admitted.grant.binding().receipt).unwrap();
    assert_eq!(receipt["verifiedAt"], NOW + 12);
    assert_eq!(
        authority.inner.lock().unwrap().floor.restart_not_before,
        NOW + 17
    );
    assert!(!authority.inner.verifying.load(Ordering::Acquire));
}

#[test]
fn prepared_capsules_recheck_policy_replacement_and_both_role_revocations() {
    for case in 0..3 {
        let fixture = Fixture::new();
        let directory = tempfile::tempdir().unwrap();
        let authority = owner(&fixture, directory.path());
        let tenant = TenantId("tests".into());
        let mut next = fixture.policy.clone();
        next["generation"] = 2.into();
        match case {
            0 => next["tenants"] = serde_json::json!([]),
            1 => {
                next["publisherRevocations"]["generation"] = 2.into();
                next["publisherRevocations"]["revokedPublishers"] =
                    serde_json::json!(["publisher-a"]);
            }
            _ => {
                next["builderRevocations"]["generation"] = 2.into();
                next["builderRevocations"]["revokedBuilders"] = serde_json::json!(["builder-a"]);
            }
        }
        let rejected = with_preparation(&authority, &tenant, fixture.upload(), |upload| {
            let prepared = prepare(upload)?;
            authority.replace_policy(
                SupplyChainPolicy::from_json(&serde_json::to_vec(&next).unwrap()).unwrap(),
            )?;
            Ok(prepared)
        });
        assert_eq!(
            rejected.err().unwrap().message,
            if case == 0 {
                "admission-tenant-denied"
            } else {
                "signature-revoked"
            }
        );
        assert!(!authority.inner.verifying.load(Ordering::Acquire));
    }
}

#[test]
fn prepared_capsules_reject_expiry_retirement_clock_regression_and_uncertain_durability() {
    for case in 0..4 {
        let mut fixture = Fixture::new();
        if case == 0 {
            fixture.policy["validUntil"] = (NOW + 4).into();
        }
        let directory = tempfile::tempdir().unwrap();
        let authority = owner(&fixture, directory.path());
        let rejected = with_preparation(
            &authority,
            &TenantId("tests".into()),
            fixture.upload(),
            |upload| {
                let prepared = prepare(upload)?;
                match case {
                    0 => fixture.clock.set(NOW + 6),
                    1 => authority.retire(),
                    2 => fixture.clock.set(NOW - 1),
                    _ => {
                        fixture.clock.set(NOW + 6);
                        authority
                            .inner
                            .ledger
                            .lock()
                            .unwrap()
                            .fault
                            .store(2, Ordering::SeqCst);
                    }
                }
                Ok(prepared)
            },
        );
        let expected = [
            "admission-policy-expired",
            "admission-owner-retired",
            "admission-clock-regression",
            "admission-durability-uncertain",
        ][case];
        assert_eq!(rejected.err().unwrap().message, expected);
        assert!(!authority.inner.verifying.load(Ordering::Acquire));
    }
}

#[test]
fn uncovered_or_denied_admission_never_enters_structural_preparation() {
    let fixture = Fixture::new();
    let directory = tempfile::tempdir().unwrap();
    let authority = owner(&fixture, directory.path());
    let denied = with_preparation(
        &authority,
        &TenantId("other".into()),
        fixture.upload(),
        |_| panic!("denied tenant must not enter preparation"),
    );
    assert_eq!(denied.err().unwrap().message, "admission-tenant-denied");
    fixture.clock.set(NOW + 5);
    let uncovered = with_preparation(
        &authority,
        &TenantId("tests".into()),
        fixture.upload(),
        |_| panic!("uncovered authority must not enter preparation"),
    );
    assert_eq!(
        uncovered.err().unwrap().message,
        "admission-clock-lease-uncovered"
    );
    assert_eq!(
        authority.inner.lock().unwrap().floor.restart_not_before,
        NOW + 5
    );
    assert!(!authority.inner.verifying.load(Ordering::Acquire));
}

#[test]
fn invalid_capsule_preparation_releases_ownership_without_renewing_the_floor() {
    let fixture = Fixture::new();
    let directory = tempfile::tempdir().unwrap();
    let authority = owner(&fixture, directory.path());
    let tenant = TenantId("tests".into());
    let floor = std::fs::read(directory.path().join("floor.json")).unwrap();
    let mut corrupted = fixture.upload();
    corrupted.layers[0].1[0] ^= 1;
    let rejected = with_preparation(&authority, &tenant, corrupted, |upload| {
        fixture.clock.set(NOW + 6);
        prepare(upload)
    });
    assert!(rejected.is_err());
    assert_eq!(
        std::fs::read(directory.path().join("floor.json")).unwrap(),
        floor
    );
    assert!(!authority.inner.verifying.load(Ordering::Acquire));
    authority.renew_clock_lease().unwrap();
    authority.verify(&tenant, fixture.upload()).unwrap();
}
