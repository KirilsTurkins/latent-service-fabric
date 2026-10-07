use super::*;
use latent_core::authority_rejection::AuthorityRejection;

#[test]
fn disabled_then_reapproved_rule_never_revives_accepted_context_or_provider_grant() {
    let (owner, mut rule, authority) = setup();
    let mut context = owner.accept(&authority, 1, time(101)).unwrap();
    let grant = context
        .accept_with(&authority, 1, time(102), |grant| grant)
        .unwrap();
    rule.enabled = false;
    rule.policy_revision = 2;
    owner.publish(rule.clone()).unwrap();
    assert!(grant.check_current(time(103)).is_err());
    assert_eq!(owner.owners().unwrap().physical, 1);
    rule.enabled = true;
    rule.policy_revision = 3;
    owner.publish(rule.clone()).unwrap();
    assert_eq!(grant.check_current(time(104)), Err(AuthorityError::Stale));
    assert!(matches!(
        context.accept_with(&authority, 1, time(105), |_| ()),
        Err(AuthorityError::Stale)
    ));
    let mut fresh_link = authority.link.clone();
    fresh_link.command = "fresh-command".into();
    fresh_link.commit = "fresh-commit".into();
    fresh_link.effect = "fresh-effect".into();
    let fresh_authority = owner
        .capture(&rule.scope, fresh_link, 100, "a".repeat(64), time(106))
        .unwrap();
    let mut fresh = owner.accept(&fresh_authority, 1, time(106)).unwrap();
    let fresh_grant = fresh
        .accept_with(&fresh_authority, 1, time(107), |grant| grant)
        .unwrap();
    assert_eq!(fresh_grant.check_current(time(108)), Ok(()));
    fresh.retire().unwrap();
    context.retire().unwrap();
    assert_eq!(owner.owners().unwrap().physical, 0);
}

#[test]
fn scoped_owner_observer_rejects_original_installation_and_refuses_identical_stale_reinstall() {
    let (owner, mut current, authority) = setup();
    let mut other_rule = current.clone();
    other_rule.scope.tenant = "tenant-b".into();
    owner.publish(other_rule.clone()).unwrap();
    let other = owner
        .capture(
            &other_rule.scope,
            authority.link.clone(),
            100,
            "a".repeat(64),
            time(100),
        )
        .unwrap();
    let mut first = owner.accept(&authority, 1, time(101)).unwrap();
    let first_grant = first
        .accept_with(&authority, 1, time(102), |grant| grant)
        .unwrap();
    let mut second = owner.accept(&other, 1, time(102)).unwrap();
    let second_grant = second
        .accept_with(&other, 1, time(103), |grant| grant)
        .unwrap();
    owner
        .rejection_observer()
        .reject(AuthorityRejection::PolicyTenant("tenant-a"))
        .unwrap();
    assert_eq!(
        first_grant.check_current(time(104)),
        Err(AuthorityError::Stale)
    );
    assert_eq!(second_grant.check_current(time(104)), Ok(()));
    assert_eq!(owner.publish(current.clone()), Err(AuthorityError::Stale));
    assert!(matches!(
        owner.accept(&authority, 2, time(105)),
        Err(AuthorityError::PolicyBlocked)
    ));
    current.policy_revision = 2;
    owner.publish(current).unwrap();
    assert_eq!(
        first_grant.check_current(time(106)),
        Err(AuthorityError::Stale)
    );
    second.retire().unwrap();
    first.retire().unwrap();
}

#[test]
fn rejected_provider_grant_keeps_exact_original_native_reservation_until_physical_retirement() {
    use latent_core::native_capacity::{
        NativeAdmissionClass, NativeCapacityLimits, NativeCapacityOwner, NativeReservationRequest,
    };
    let capacity = NativeCapacityOwner::new(NativeCapacityLimits::default()).unwrap();
    let original = Arc::new(
        capacity
            .reserve(
                NativeAdmissionClass::Ordinary,
                NativeReservationRequest {
                    request_bytes: 4096,
                    work_bytes: 8192,
                    response_bytes: 4096,
                },
                Instant::now() + Duration::from_secs(30),
            )
            .unwrap(),
    );
    let witness = Arc::downgrade(&original);
    let (owner, mut current, authority) = setup();
    let mut context = owner.accept(&authority, 1, time(101)).unwrap();
    context
        .retain_owner(original.clone())
        .unwrap_or_else(|_| panic!("owner refused"));
    let grant = context
        .accept_with(&authority, 1, time(102), |grant| grant)
        .unwrap();
    drop(original);
    owner
        .rejection_observer()
        .reject(AuthorityRejection::Publication {
            tenant: Some("tenant-a"),
            publication: "publication-a",
        })
        .unwrap();
    current.policy_revision = 2;
    owner.publish(current).unwrap();
    assert_eq!(grant.check_current(time(103)), Err(AuthorityError::Stale));
    assert_eq!(owner.owners().unwrap().physical, 1);
    assert_eq!(capacity.snapshot().unwrap().ordinary.slots, 1);
    context.retire().unwrap();
    assert_eq!(capacity.snapshot().unwrap().ordinary.slots, 1);
    assert!(witness.upgrade().is_some());
    drop(grant);
    assert!(witness.upgrade().is_none());
    assert_eq!(capacity.snapshot().unwrap().ordinary.slots, 0);
    assert_eq!(owner.owners().unwrap().physical, 0);
}

#[test]
fn fresh_lookup_after_rejection_has_its_own_bounded_non_execution_stamp() {
    let (owner, _, authority) = setup();
    owner
        .rejection_observer()
        .reject(AuthorityRejection::PolicyTenant("tenant-a"))
        .unwrap();
    let gate = lookup::gate();
    let mut context = owner
        .accept_lookup(
            &authority,
            1,
            time(101),
            Instant::now() + Duration::from_secs(1),
            gate.clone(),
        )
        .unwrap();
    let grant = context
        .accept_with(&authority, 1, time(102), |grant| grant)
        .unwrap();
    assert_eq!(grant.check_current(time(103)), Ok(()));
    assert_eq!(
        grant.require_execution(),
        Err(AuthorityError::PolicyBlocked)
    );
    owner
        .rejection_observer()
        .reject(AuthorityRejection::PolicyTenant("tenant-a"))
        .unwrap();
    assert_eq!(grant.check_current(time(104)), Err(AuthorityError::Stale));
    let mut fresh = owner
        .accept_lookup(
            &authority,
            1,
            time(105),
            Instant::now() + Duration::from_secs(1),
            gate,
        )
        .unwrap();
    let fresh_grant = fresh
        .accept_with(&authority, 1, time(106), |grant| grant)
        .unwrap();
    assert_eq!(fresh_grant.check_current(time(107)), Ok(()));
    assert_eq!(grant.check_current(time(108)), Err(AuthorityError::Stale));
    fresh.retire().unwrap();
    context.retire().unwrap();
    assert_eq!(owner.owners().unwrap().physical, 0);
}
