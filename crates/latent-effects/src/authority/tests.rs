use super::*;

#[test]
fn final_adapter_admission_refreshes_credential_and_narrows_original_deadline_under_fence() {
    let (owner, mut rule, authority) = setup();
    let mut context = owner.accept(&authority, 1, time(101)).unwrap();
    let deadline = context.deadline();
    rule.policy_revision = 2;
    rule.credential_epoch = 2;
    rule.protected_credential_reference = "rotated-secret".into();
    rule.ceiling.maximum_response_bytes = 128;
    rule.ceiling.attempt_timeout_millis = 50;
    rule.ceiling.maximum_age_millis = 500;
    owner.publish(rule).unwrap();
    context
        .accept_with(&authority, 1, time(102), |grant| {
            assert_eq!(grant.effect(), authority.link().effect);
            assert_eq!(grant.attempt(), 1);
            assert_eq!(grant.scope(), authority.scope());
            assert_eq!(grant.profile(), authority.profile());
            assert_eq!(grant.credential_epoch(), 2);
            assert_eq!(grant.protected_credential_reference(), "rotated-secret");
            assert_eq!(grant.ceiling().maximum_response_bytes, 128);
            assert_eq!(grant.ceiling().maximum_age_millis, 500);
            assert_eq!(grant.committed_at_millis(), 100);
            assert_eq!(grant.expires_at_millis(), 1100);
            assert_eq!(grant.expires_at_millis(), authority.expires_at_millis());
            assert!(grant.deadline() <= deadline);
            assert!(matches!(
                owner.0.state.try_lock(),
                Err(std::sync::TryLockError::WouldBlock)
            ));
        })
        .unwrap();
    assert_eq!(owner.owners().unwrap().physical, 1);
    context.retire().unwrap();
    assert_eq!(owner.owners().unwrap(), DispatchOwners::default());
}

#[test]
fn revocation_between_claim_and_adapter_acceptance_prevents_io_without_refunding_physical_owner() {
    let (owner, mut rule, authority) = setup();
    let mut context = owner.accept(&authority, 1, time(101)).unwrap();
    assert_eq!(
        context.accept_with(&authority, 2, time(102), |_| panic!(
            "wrong attempt accepted"
        )),
        Err(AuthorityError::Invalid)
    );
    rule.policy_revision = 2;
    rule.enabled = false;
    owner.publish(rule).unwrap();
    assert_eq!(
        context.accept_with(&authority, 1, time(103), |_| panic!(
            "revoked adapter accepted"
        )),
        Err(AuthorityError::PolicyBlocked)
    );
    assert_eq!(owner.owners().unwrap().physical, 1);
    context.retire().unwrap();
    assert_eq!(owner.owners().unwrap(), DispatchOwners::default());
}

fn rule() -> EffectRule {
    EffectRule {
        scope: EffectScope {
            tenant: "tenant-a".into(),
            namespace: "orders".into(),
            incarnation: 1,
            publication: "publication-a".into(),
            binding: "events".into(),
            operation: "publish".into(),
        },
        profile: DispatchProfile {
            provider: "jetstream-a".into(),
            destination: "orders.subject".into(),
            adapter: "jetstream.v1".into(),
            intent_format: 1,
            payload_format: "bytes.v1".into(),
            idempotency_profile: "bounded-message-id.v1".into(),
        },
        policy_revision: 1,
        credential_epoch: 1,
        protected_credential_reference: "provider-a".into(),
        ceiling: DispatchCeiling {
            maximum_payload_bytes: 1024,
            maximum_response_bytes: 1024,
            maximum_attempts: 3,
            maximum_age_millis: 1000,
            attempt_timeout_millis: 100,
        },
        enabled: true,
    }
}

fn time(now: u64) -> EffectTime {
    EffectTime {
        unix_millis: now,
        continuity_proven: true,
    }
}

fn setup() -> (EffectAuthorityOwner, EffectRule, DurableEffectAuthority) {
    let owner = EffectAuthorityOwner::new(2, 2, 100).unwrap();
    let grant = rule();
    owner.publish(grant.clone()).unwrap();
    let link = CommitLink {
        command: "command-a".into(),
        caller_scope: "user-a".into(),
        attempt: 1,
        commit: "commit-a".into(),
        effect: "effect-a".into(),
        sequence: 0,
    };
    let captured = owner
        .capture(&grant.scope, link, 100, "a".repeat(64), time(100))
        .unwrap();
    (owner, grant, captured)
}

#[test]
fn final_commit_fence_linearizes_revocation_without_allocating_dispatch_work() {
    use std::sync::mpsc;
    let (owner, mut grant, captured) = setup();
    let fence = owner
        .commit_fence(std::slice::from_ref(&captured), time(101))
        .unwrap();
    assert!(matches!(
        owner.0.state.try_lock(),
        Err(std::sync::TryLockError::WouldBlock)
    ));
    let worker_owner = owner.clone();
    grant.policy_revision = 2;
    grant.enabled = false;
    let (started_tx, started_rx) = mpsc::channel();
    let (finished_tx, finished_rx) = mpsc::channel();
    let worker = std::thread::spawn(move || {
        started_tx.send(()).unwrap();
        finished_tx.send(worker_owner.publish(grant)).unwrap();
    });
    started_rx.recv_timeout(Duration::from_secs(3)).unwrap();
    assert_eq!(finished_rx.try_recv(), Err(mpsc::TryRecvError::Empty));
    drop(fence);
    assert_eq!(
        finished_rx.recv_timeout(Duration::from_secs(3)).unwrap(),
        Ok(())
    );
    worker.join().unwrap();
    assert!(matches!(
        owner.commit_fence(&[captured], time(102)),
        Err(AuthorityError::PolicyBlocked)
    ));
    assert_eq!(owner.owners().unwrap(), DispatchOwners::default());
}

#[test]
fn final_commit_checks_every_intent_against_current_format_bounds_and_clock() {
    let (owner, mut grant, captured) = setup();
    grant.policy_revision = 2;
    grant.ceiling.maximum_payload_bytes = 99;
    owner.publish(grant.clone()).unwrap();
    assert!(matches!(
        owner.commit_fence(std::slice::from_ref(&captured), time(101)),
        Err(AuthorityError::Capacity)
    ));
    grant.policy_revision = 3;
    grant.ceiling.maximum_payload_bytes = 100;
    grant.profile.intent_format = 2;
    owner.publish(grant).unwrap();
    assert!(matches!(
        owner.commit_fence(&[captured], time(102)),
        Err(AuthorityError::UnsupportedFormat)
    ));
    assert!(matches!(
        owner.commit_fence(&[], time(101)),
        Err(AuthorityError::ClockDiscontinuity)
    ));
    assert_eq!(owner.owners().unwrap(), DispatchOwners::default());
}

#[test]
fn requested_expiry_only_narrows_and_malformed_typed_envelopes_grant_nothing() {
    let (owner, grant, captured) = setup();
    let short = owner
        .capture_until(
            &grant.scope,
            captured.link.clone(),
            100,
            "a".repeat(64),
            time(100),
            Some(200),
        )
        .unwrap();
    assert_eq!(short.ceiling().maximum_age_millis, 100);
    assert_eq!(
        DurableEffectAuthority::decode(&short.encode().unwrap()),
        Ok(short.clone())
    );
    let long = owner
        .capture_until(
            &grant.scope,
            captured.link.clone(),
            100,
            "a".repeat(64),
            time(100),
            Some(u64::MAX),
        )
        .unwrap();
    assert_eq!(long.ceiling(), captured.ceiling());
    assert_eq!(
        owner.capture_until(
            &grant.scope,
            captured.link.clone(),
            100,
            "a".repeat(64),
            time(100),
            Some(100)
        ),
        Err(AuthorityError::Invalid)
    );
    assert!(matches!(
        owner.commit_fence(&[short], time(200)),
        Err(AuthorityError::Expired)
    ));
    let mut forged = captured;
    forged.policy_revision = 0;
    assert_eq!(forged.encode(), Err(AuthorityError::Invalid));
    assert!(matches!(
        owner.accept(&forged, 1, time(201)),
        Err(AuthorityError::Invalid)
    ));
}

#[test]
fn guest_selected_alias_does_not_grant_cross_tenant_or_publication_authority() {
    let (owner, grant, captured) = setup();
    for forged in [
        EffectScope {
            tenant: "tenant-b".into(),
            ..grant.scope.clone()
        },
        EffectScope {
            publication: "publication-b".into(),
            ..grant.scope.clone()
        },
        EffectScope {
            incarnation: 2,
            ..grant.scope.clone()
        },
    ] {
        assert_eq!(
            owner.capture(
                &forged,
                captured.link.clone(),
                100,
                "a".repeat(64),
                time(101)
            ),
            Err(AuthorityError::PolicyBlocked)
        );
    }
    assert_eq!(owner.owners().unwrap(), DispatchOwners::default());
}

#[test]
fn current_ceiling_can_narrow_but_never_widen_a_committed_intent() {
    let (owner, mut grant, captured) = setup();
    grant.policy_revision = 2;
    grant.ceiling.maximum_payload_bytes = 100_000;
    grant.ceiling.maximum_attempts = 10;
    grant.ceiling.maximum_age_millis = 10_000;
    owner.publish(grant.clone()).unwrap();
    assert!(matches!(
        owner.accept(&captured, 4, time(101)),
        Err(AuthorityError::Capacity)
    ));
    let context = owner.accept(&captured, 1, time(102)).unwrap();
    assert_eq!(context.ceiling(), captured.ceiling);
    context.retire().unwrap();
    grant.policy_revision = 3;
    grant.ceiling.maximum_payload_bytes = 99;
    owner.publish(grant).unwrap();
    assert!(matches!(
        owner.accept(&captured, 2, time(103)),
        Err(AuthorityError::Capacity)
    ));
}

#[test]
fn revocation_after_acceptance_does_not_refund_live_physical_work() {
    let (owner, mut grant, captured) = setup();
    let context = owner.accept(&captured, 1, time(101)).unwrap();
    grant.enabled = false;
    grant.policy_revision = 2;
    owner.publish(grant).unwrap();
    assert!(matches!(
        owner.accept(&captured, 2, time(102)),
        Err(AuthorityError::PolicyBlocked)
    ));
    assert_eq!(owner.owners().unwrap().physical, 1);
    context.retire().unwrap();
    assert_eq!(owner.owners().unwrap(), DispatchOwners::default());
}

#[test]
fn credential_rotation_preserves_destination_and_envelope_provenance() {
    let (owner, mut grant, captured) = setup();
    grant.credential_epoch = 2;
    grant.policy_revision = 2;
    grant.protected_credential_reference = "protected-reference-b".into();
    owner.publish(grant).unwrap();
    let context = owner.accept(&captured, 1, time(101)).unwrap();
    assert_eq!(context.credential_epoch(), 2);
    assert_eq!(
        context.protected_credential_reference(),
        "protected-reference-b"
    );
    assert_eq!(context.profile(), &captured.profile);
    assert!(!format!("{captured:?}").contains("protected-reference"));
    context.retire().unwrap();
}

#[test]
fn provider_replacement_and_old_decoder_removal_block_instead_of_redirecting() {
    let (owner, grant, captured) = setup();
    for profile in [
        DispatchProfile {
            destination: "another.subject".into(),
            ..grant.profile.clone()
        },
        DispatchProfile {
            intent_format: 2,
            ..grant.profile.clone()
        },
        DispatchProfile {
            idempotency_profile: "unqualified.v1".into(),
            ..grant.profile.clone()
        },
    ] {
        let changed = EffectRule {
            policy_revision: 2,
            profile,
            ..grant.clone()
        };
        let replacement = EffectAuthorityOwner::new(2, 2, 100).unwrap();
        replacement.publish(changed).unwrap();
        assert!(matches!(
            replacement.accept(&captured, 1, time(101)),
            Err(AuthorityError::UnsupportedFormat)
        ));
    }
    assert_eq!(owner.owners().unwrap(), DispatchOwners::default());
}

#[test]
fn expiry_and_uncertain_restart_clock_never_renew_durable_lifetime() {
    let (owner, _, captured) = setup();
    assert!(matches!(
        owner.accept(
            &captured,
            1,
            EffectTime {
                unix_millis: 101,
                continuity_proven: false
            }
        ),
        Err(AuthorityError::ClockDiscontinuity)
    ));
    assert!(matches!(
        owner.accept(&captured, 1, time(99)),
        Err(AuthorityError::ClockDiscontinuity)
    ));
    assert!(matches!(
        owner.accept(&captured, 1, time(1100)),
        Err(AuthorityError::Expired)
    ));
    assert!(matches!(
        owner.accept(&captured, 1, time(101)),
        Err(AuthorityError::ClockDiscontinuity)
    ));
}

#[test]
fn dropped_context_quarantines_capacity_instead_of_refunding_live_io() {
    let (owner, _, captured) = setup();
    let first = owner.accept(&captured, 1, time(101)).unwrap();
    let second = owner.accept(&captured, 2, time(102)).unwrap();
    drop(first);
    assert_eq!(
        owner.owners().unwrap(),
        DispatchOwners {
            physical: 2,
            quarantined: 1
        }
    );
    assert!(matches!(
        owner.accept(&captured, 3, time(103)),
        Err(AuthorityError::Capacity)
    ));
    second.retire().unwrap();
    assert_eq!(
        owner.owners().unwrap(),
        DispatchOwners {
            physical: 1,
            quarantined: 1
        }
    );
}

#[test]
fn bounded_rule_publication_rejects_rollback_and_same_revision_mutation() {
    let (owner, mut grant, _) = setup();
    grant.enabled = false;
    assert_eq!(owner.publish(grant.clone()), Err(AuthorityError::Stale));
    grant.policy_revision = 2;
    owner.publish(grant.clone()).unwrap();
    grant.policy_revision = 1;
    assert_eq!(owner.publish(grant), Err(AuthorityError::Stale));
    let mut extra = rule();
    extra.scope.tenant = "tenant-b".into();
    owner.publish(extra.clone()).unwrap();
    extra.scope.tenant = "tenant-c".into();
    assert_eq!(owner.publish(extra), Err(AuthorityError::Capacity));
}

#[test]
fn bounded_retained_record_roundtrip_never_restores_current_authority() {
    let (owner, mut grant, captured) = setup();
    let bytes = captured.encode().unwrap();
    let retained = DurableEffectAuthority::decode(&bytes).unwrap();
    assert_eq!(retained, captured);
    grant.enabled = false;
    grant.policy_revision = 2;
    owner.publish(grant).unwrap();
    assert!(matches!(
        owner.accept(&retained, 1, time(101)),
        Err(AuthorityError::PolicyBlocked)
    ));
    let mut newer = bytes.clone();
    newer[4] = 2;
    assert_eq!(
        DurableEffectAuthority::decode(&newer),
        Err(AuthorityError::UnsupportedFormat)
    );
    assert_eq!(
        DurableEffectAuthority::decode(&vec![0; 8198]),
        Err(AuthorityError::Capacity)
    );
    let mut body: serde_json::Value = serde_json::from_slice(&bytes[5..]).unwrap();
    body["ceiling"]["maximum_attempts"] = serde_json::json!(0);
    let mut corrupt = b"LEA\0\x01".to_vec();
    corrupt.extend(serde_json::to_vec(&body).unwrap());
    assert_eq!(
        DurableEffectAuthority::decode(&corrupt),
        Err(AuthorityError::Invalid)
    );
    body["ceiling"]["maximum_attempts"] = serde_json::json!(3);
    body["credential"] = serde_json::json!("untrusted");
    corrupt.truncate(5);
    corrupt.extend(serde_json::to_vec(&body).unwrap());
    assert_eq!(
        DurableEffectAuthority::decode(&corrupt),
        Err(AuthorityError::Invalid)
    );
}
