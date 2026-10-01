use super::*;

struct CurrentManagement {
    allowed: AtomicBool,
    live: AtomicBool,
}
impl ProviderLookupAuthorization for CurrentManagement {
    fn with_current(
        &self,
        accept: &mut dyn FnMut() -> Result<(), AuthorityError>,
    ) -> Result<(), AuthorityError> {
        if !self.allowed.load(Ordering::Acquire) {
            return Err(AuthorityError::PolicyBlocked);
        }
        accept()
    }
    fn with_live(
        &self,
        accept: &mut dyn FnMut() -> Result<(), AuthorityError>,
    ) -> Result<(), AuthorityError> {
        if !self.live.load(Ordering::Acquire) {
            return Err(AuthorityError::Expired);
        }
        accept()
    }
}
fn gate() -> Arc<CurrentManagement> {
    Arc::new(CurrentManagement {
        allowed: AtomicBool::new(true),
        live: AtomicBool::new(true),
    })
}

#[test]
fn fresh_lookup_reads_revoked_expired_execution_without_becoming_send_authority() {
    let (owner, mut rule, authority) = setup();
    rule.enabled = false;
    rule.policy_revision += 1;
    owner.publish(rule).unwrap();
    let management = gate();
    let mut context = owner
        .accept_lookup(
            &authority,
            1,
            time(authority.expires_at_millis() + 1),
            Instant::now() + Duration::from_secs(1),
            management,
        )
        .unwrap();
    let grant = context
        .accept_with(
            &authority,
            1,
            time(authority.expires_at_millis() + 2),
            |grant| grant,
        )
        .unwrap();
    assert_eq!(grant.purpose(), DispatchPurpose::ReconcileOnly);
    assert_eq!(
        grant.require_execution(),
        Err(AuthorityError::PolicyBlocked)
    );
    assert_eq!(grant.expires_at_millis(), authority.expires_at_millis());
    assert_eq!(
        grant.check_current(time(authority.expires_at_millis() + 3)),
        Ok(())
    );
    assert!(matches!(
        owner.accept(&authority, 1, time(authority.expires_at_millis() + 4)),
        Err(AuthorityError::PolicyBlocked)
    ));
    context.retire().unwrap();
    assert_eq!(owner.owners().unwrap().physical, 0);
}

#[test]
fn lookup_prewrite_observes_original_management_revocation_and_native_deadline() {
    let (owner, _, authority) = setup();
    let management = gate();
    let mut context = owner
        .accept_lookup(
            &authority,
            1,
            time(101),
            Instant::now() + Duration::from_secs(1),
            management.clone(),
        )
        .unwrap();
    let grant = context
        .accept_with(&authority, 1, time(102), |grant| grant)
        .unwrap();
    management.allowed.store(false, Ordering::Release);
    assert_eq!(
        grant.check_current(time(103)),
        Err(AuthorityError::PolicyBlocked)
    );
    assert_eq!(owner.owners().unwrap().physical, 1);
    management.allowed.store(true, Ordering::Release);
    management.live.store(false, Ordering::Release);
    assert_eq!(grant.check_current(time(104)), Err(AuthorityError::Expired));
    context.retire().unwrap();
}

#[test]
fn lookup_preserves_provider_incarnation_credentials_payload_and_original_attempt() {
    let (owner, mut rule, authority) = setup();
    let management = gate();
    let mut context = owner
        .accept_lookup(
            &authority,
            1,
            time(101),
            Instant::now() + Duration::from_secs(1),
            management,
        )
        .unwrap();
    assert!(matches!(
        context.accept_with(&authority, 2, time(102), |_| ()),
        Err(AuthorityError::Invalid)
    ));
    let grant = context
        .accept_with(&authority, 1, time(103), |grant| grant)
        .unwrap();
    assert_eq!(grant.payload_digest(), authority.payload_digest());
    rule.policy_revision += 1;
    rule.credential_epoch += 1;
    owner.publish(rule.clone()).unwrap();
    assert_eq!(
        grant.check_current(time(104)),
        Err(AuthorityError::PolicyBlocked)
    );
    rule.policy_revision += 1;
    rule.profile.destination = "replacement".into();
    owner.publish(rule).unwrap();
    assert_eq!(
        grant.check_current(time(105)),
        Err(AuthorityError::UnsupportedFormat)
    );
    context.retire().unwrap();
}

#[test]
fn lookup_rejects_missing_or_repeated_current_gate_before_issuing_a_grant() {
    struct Missing;
    impl ProviderLookupAuthorization for Missing {
        fn with_current(
            &self,
            _: &mut dyn FnMut() -> Result<(), AuthorityError>,
        ) -> Result<(), AuthorityError> {
            Ok(())
        }
        fn with_live(
            &self,
            _: &mut dyn FnMut() -> Result<(), AuthorityError>,
        ) -> Result<(), AuthorityError> {
            Ok(())
        }
    }
    let (owner, _, authority) = setup();
    assert!(matches!(
        owner.accept_lookup(
            &authority,
            1,
            time(101),
            Instant::now() + Duration::from_secs(1),
            Arc::new(Missing)
        ),
        Err(AuthorityError::Invalid)
    ));
    assert_eq!(owner.owners().unwrap().physical, 0);
}
